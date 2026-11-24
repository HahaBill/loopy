"""The code-agent loop: the model writes Python, the environment runs it, the output goes back to the model.

The prompt is AppWorld's published minimal ReAct prompt (notebooks/minimal_agent.ipynb in
github.com/StonyBrookNLP/appworld, Apache 2.0), unchanged, in `prompts/appworld_minimal_react.txt`.
Loopy's own additions are separate, optional blocks placed before the task statement:

- `guidance`: a coach note (text the bigger model wrote once for this kind of task);
- `preload_code` + `guidance`: a compiled workflow (a function defined in the environment before step 1).

Nothing here knows about AppWorld beyond the `Environment` protocol, so the same loop can drive other tools.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from loopy.agent.llm import ChatModel, Message, Reply
from loopy.eval.runlog import ledger_add, ledger_total

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "appworld_minimal_react.txt"

FORECAST_QUESTION = (
    "Before you begin, one question about yourself. Estimate the probability that you will NOT complete the "
    "task above correctly (a correct result means the apps end in exactly the requested state, nothing else "
    "is changed, and the answer is right if one is asked for). Do not start the task and do not write code. "
    "Reply with a single number between 0 and 100 and nothing else."
)

NO_CODE_MESSAGE = "No code found in your reply. Reply with Python code only; put any thoughts in code comments."
EXECUTION_FAILED_PREFIX = "Execution failed."

_ROLE_MARKER = re.compile(r"^(USER|ASSISTANT|SYSTEM):\n", re.M)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\n(.*?)```", re.S)
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")


class Environment(Protocol):
    def execute(self, code: str) -> Any: ...  # returns an object with .output (str) and .task_completed (bool)


class CostCapReached(RuntimeError):
    pass


@dataclass
class Budget:
    """A hard dollar cap, checked right before every model request.

    With a ledger, every priced request is written to the shared ledger as soon as it returns, and the shared cap is
    read before the next one. Parallel jobs then see each other's spend, so the most the total can pass the cap by is
    one request in flight per job. A hard kill loses at most the request in flight.
    """

    max_usd: float | None = None
    spent_usd: float = 0.0
    ledger: Path | str | None = None
    provider: str = ""
    run_name: str = ""
    note: str = ""
    ledger_cap: float | None = None

    def check(self) -> None:
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            raise CostCapReached(f"spent ${self.spent_usd:.4f} of the ${self.max_usd:.2f} cap")
        if self.ledger is not None and self.ledger_cap is not None:
            total = ledger_total(self.ledger, self.provider)
            if total >= self.ledger_cap:
                raise CostCapReached(f"{self.provider} ledger at ${total:.4f} of the ${self.ledger_cap:.2f} cap")

    def add(self, usd: float) -> None:
        self.spent_usd += usd
        if self.ledger is not None and usd > 0:
            ledger_add(self.ledger, self.provider, usd, self.run_name, self.note)


@dataclass
class Step:
    index: int
    code: str
    output: str
    execution_failed: bool
    had_code: bool
    input_tokens: int
    output_tokens: int
    seconds: float
    cost_usd: float
    raw_reply: str
    thinking: str = ""
    finish_reason: str | None = None
    attempts: int = 1
    dropped_messages: int = 0


@dataclass
class Forecast:
    probability_of_failure: float | None
    raw_reply: str
    input_tokens: int
    output_tokens: int
    seconds: float
    cost_usd: float


@dataclass
class PaidReply:
    """A model reply that was charged but never became a step, because the run broke before the step was stored."""

    input_tokens: int
    output_tokens: int
    seconds: float
    cost_usd: float
    raw_reply: str


@dataclass
class RunTrace:
    stop_reason: str  # completed | max_steps | context_overflow | cost_cap | model_error | preload_error
    task_completed: bool
    steps: list[Step] = field(default_factory=list)
    forecast: Forecast | None = None
    messages: list[Message] = field(default_factory=list)
    preload_output: str | None = None
    error: str | None = None
    unfinished: list[PaidReply] = field(default_factory=list)

    @property
    def n_execution_failures(self) -> int:
        return sum(1 for step in self.steps if step.execution_failed)

    def totals(self) -> dict[str, float]:
        """Every request the budget was charged for: the steps, the forecast and any reply that never became a step."""
        parts = list(self.steps) + ([self.forecast] if self.forecast else []) + list(self.unfinished)
        return {
            "requests": len(parts),
            "input_tokens": sum(part.input_tokens for part in parts),
            "output_tokens": sum(part.output_tokens for part in parts),
            "model_seconds": sum(part.seconds for part in parts),
            "cost_usd": sum(part.cost_usd for part in parts),
        }


def build_messages(instruction: str, supervisor: dict[str, Any], guidance: str | None = None) -> list[Message]:
    """AppWorld's minimal ReAct prompt for one task. `guidance`, if given, goes right before the task."""
    template = PROMPT_PATH.read_text(encoding="utf-8")
    for key in ("first_name", "last_name", "email", "phone_number"):
        template = template.replace("{{ supervisor." + key + " }}", str(supervisor.get(key, "")))
    template = template.replace("{{ instruction }}", instruction)

    messages: list[Message] = []
    matches = list(_ROLE_MARKER.finditer(template))
    if not matches or matches[0].start() != 0:
        raise ValueError("the prompt template must start with a role marker")
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(template)
        messages.append({"role": match.group(1).lower(), "content": template[match.end() : end].strip()})
    if guidance:
        messages.insert(len(messages) - 1, {"role": "user", "content": guidance.strip()})
    return messages


def extract_code(text: str) -> str:
    """The code to run from a model reply: drop thinking, unwrap ``` fences if the model used them."""
    text = _THINK_BLOCK.sub("", text)
    if "<think>" in text:  # a reply cut off in the middle of thinking
        text = text.split("<think>", 1)[0]
    blocks = _FENCE.findall(text)
    if blocks:
        return "\n".join(block.strip("\n") for block in blocks).strip()
    return text.strip()


def truncate_output(output: str, limit_chars: int) -> str:
    if limit_chars <= 0 or len(output) <= limit_chars:
        return output
    head, tail = limit_chars * 2 // 3, limit_chars // 3
    omitted = len(output) - head - tail
    return f"{output[:head]}\n... [{omitted} characters omitted] ...\n{output[-tail:]}"


def estimate_tokens(messages: list[Message]) -> int:
    """A deliberately high estimate (code and JSON run about 3 characters per token)."""
    return int(sum(len(message["content"]) for message in messages) / 3.0) + 4 * len(messages)


def trim_history(messages: list[Message], n_fixed: int, budget_tokens: int | None) -> tuple[list[Message] | None, int]:
    """Drop the oldest (code, output) pairs after the fixed prompt until the estimate fits the budget.

    Returns (messages to send, number of dropped messages), or (None, dropped) if even the fixed prompt
    plus the latest pair does not fit.
    """
    if budget_tokens is None:
        return messages, 0
    fixed, steps = messages[:n_fixed], messages[n_fixed:]
    dropped = 0
    while estimate_tokens(fixed + steps) > budget_tokens and len(steps) > 2:
        steps = steps[2:]
        dropped += 2
    if estimate_tokens(fixed + steps) > budget_tokens:
        return None, dropped
    return fixed + steps, dropped


def parse_forecast(text: str) -> float | None:
    """Probability of failure in [0, 1] from a reply that should be one number between 0 and 100."""
    text = _THINK_BLOCK.sub("", text)
    numbers = [float(value) for value in _NUMBER.findall(text)]
    numbers = [value for value in numbers if 0.0 <= value <= 100.0]
    if not numbers:
        return None
    value = numbers[-1]
    if 0.0 < value < 1.0:  # answered as a probability, not a percentage
        return value
    return value / 100.0


def ask_forecast(model: ChatModel, messages: list[Message], budget: Budget) -> Forecast:
    budget.check()
    reply = model.complete(messages + [{"role": "user", "content": FORECAST_QUESTION}])
    cost = model.spec.cost_usd(reply.input_tokens, reply.output_tokens)
    budget.add(cost)
    return Forecast(
        probability_of_failure=parse_forecast(reply.text),
        raw_reply=reply.text,
        input_tokens=reply.input_tokens,
        output_tokens=reply.output_tokens,
        seconds=reply.seconds,
        cost_usd=cost,
    )


def run_task(
    environment: Environment,
    model: ChatModel,
    instruction: str,
    supervisor: dict[str, Any],
    *,
    max_steps: int = 50,
    output_char_limit: int = 8000,
    guidance: str | None = None,
    preload_code: str | None = None,
    forecast: bool = True,
    budget: Budget | None = None,
) -> RunTrace:
    """Run one task to completion, the step limit or a stop condition. Grading is the caller's job."""
    budget = budget or Budget()
    messages = build_messages(instruction, supervisor, guidance)
    n_fixed = len(messages)
    trace = RunTrace(stop_reason="max_steps", task_completed=False, messages=messages)

    try:
        if forecast:
            trace.forecast = ask_forecast(model, messages, budget)
        if preload_code:
            preload = environment.execute(preload_code)
            trace.preload_output = preload.output
            if preload.output.startswith(EXECUTION_FAILED_PREFIX):
                trace.stop_reason = "preload_error"
                return trace

        for index in range(1, max_steps + 1):
            budget.check()
            prompt, dropped = trim_history(messages, n_fixed, model.spec.context_budget_tokens)
            if prompt is None:
                trace.stop_reason = "context_overflow"
                return trace
            reply: Reply = model.complete(prompt)
            cost = model.spec.cost_usd(reply.input_tokens, reply.output_tokens)
            budget.add(cost)
            # Counted from the moment it is charged. If the environment raises below, the step is never stored, and
            # without this the run's totals would be one request short of what the budget and the ledger recorded.
            paid = PaidReply(reply.input_tokens, reply.output_tokens, reply.seconds, cost, reply.text)
            trace.unfinished.append(paid)

            code = extract_code(reply.text)
            completed = False
            if code:
                execution = environment.execute(code)
                output, completed = execution.output, bool(execution.task_completed)
            else:
                output = NO_CODE_MESSAGE
            shown = truncate_output(output, output_char_limit)
            messages.append({"role": "assistant", "content": code or reply.text.strip()[:2000] or "(empty reply)"})
            messages.append({"role": "user", "content": shown})
            trace.steps.append(
                Step(
                    index=index,
                    code=code,
                    output=output,
                    execution_failed=output.startswith(EXECUTION_FAILED_PREFIX),
                    had_code=bool(code),
                    input_tokens=reply.input_tokens,
                    output_tokens=reply.output_tokens,
                    seconds=reply.seconds,
                    cost_usd=cost,
                    raw_reply=reply.text,
                    thinking=reply.thinking,
                    finish_reason=reply.finish_reason,
                    attempts=reply.attempts,
                    dropped_messages=dropped,
                )
            )
            trace.unfinished.remove(paid)  # it is a step now
            if completed:
                trace.stop_reason = "completed"
                trace.task_completed = True
                return trace
    except CostCapReached as error:
        trace.stop_reason = "cost_cap"
        trace.error = str(error)
    except Exception as error:  # a model or bridge failure: keep what we have and say why we stopped
        trace.stop_reason = "model_error"
        trace.error = f"{type(error).__name__}: {error}"
    return trace


def classify_failure(success: bool, trace: RunTrace) -> str | None:
    """The proposal's two failure levels, decided from what the run looked like, not from the checker's detail.

    bug     : the run broke. It never declared the task done (step limit, context overflow, model error),
              or its last executed step raised an error.
    quality : the run finished normally and said it was done, but the result is wrong.
    """
    if success:
        return None
    if trace.stop_reason != "completed":
        return "bug"
    if trace.steps and trace.steps[-1].execution_failed:
        return "bug"
    return "quality"
