"""The agent loop, tested with a scripted model and a fake environment. No model or AppWorld needed."""

from dataclasses import dataclass

import pytest

from loopy.agent.llm import ModelSpec, ScriptedChat, merge_same_role
from loopy.agent.react import (
    FORECAST_QUESTION,
    NO_CODE_MESSAGE,
    Budget,
    build_messages,
    classify_failure,
    estimate_tokens,
    extract_code,
    parse_forecast,
    run_task,
    trim_history,
    truncate_output,
)

SUPERVISOR = {"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "phone_number": "5550100"}
SPEC = ModelSpec(key="small", role="small", name="scripted", usd_per_mtok_in=1.0, usd_per_mtok_out=2.0)


@dataclass
class FakeExecution:
    output: str
    task_completed: bool


class FakeEnvironment:
    """Completes when the code calls complete_task; raises a fake error on code containing 'boom'."""

    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, code: str) -> FakeExecution:
        self.executed.append(code)
        if "boom" in code:
            return FakeExecution("Execution failed. Traceback:\nException: boom", False)
        if "complete_task" in code:
            return FakeExecution("Marked the active task complete.", True)
        return FakeExecution("Execution successful.", False)


def test_prompt_has_the_task_last_and_roles_from_the_template():
    messages = build_messages("Like my most played song.", SUPERVISOR)
    assert messages[0]["role"] == "user" and messages[1]["role"] == "assistant"
    assert messages[-1]["content"].endswith("Like my most played song.")
    assert "Ada Lovelace" in messages[-1]["content"]
    assert "{{" not in "".join(message["content"] for message in messages)


def test_guidance_goes_right_before_the_task_and_merges_into_one_user_turn():
    messages = build_messages("Do the thing.", SUPERVISOR, guidance="NOTE: log in first.")
    assert messages[-2]["content"] == "NOTE: log in first."
    merged = merge_same_role(messages)
    assert [message["role"] for message in merged][-1] == "user"
    roles = [message["role"] for message in merged]
    assert all(first != second for first, second in zip(roles, roles[1:]))
    assert "NOTE: log in first." in merged[-1]["content"] and merged[-1]["content"].endswith("Do the thing.")


def test_extract_code_unwraps_fences_and_drops_thinking():
    assert extract_code("print(1)") == "print(1)"
    assert extract_code("Sure:\n```python\nprint(1)\n```\ndone") == "print(1)"
    assert extract_code("<think>hmm</think>\n```\nx = 2\n```") == "x = 2"
    assert extract_code("<think>cut off before any code") == ""
    assert extract_code("```python\na = 1\n```\ntext\n```python\nb = 2\n```") == "a = 1\nb = 2"


def test_truncate_output_keeps_head_and_tail():
    text = "A" * 100 + "B" * 100
    short = truncate_output(text, 60)
    assert short.startswith("A" * 40) and short.endswith("B" * 20) and "140 characters omitted" in short
    assert truncate_output("abc", 60) == "abc"


def test_trim_history_drops_oldest_pairs_and_reports_overflow():
    fixed = [{"role": "user", "content": "x" * 300}]
    steps = [{"role": "assistant" if index % 2 == 0 else "user", "content": "y" * 300} for index in range(8)]
    budget = estimate_tokens(fixed + steps[-4:])
    trimmed, dropped = trim_history(fixed + steps, 1, budget)
    assert dropped == 4 and trimmed == fixed + steps[-4:]
    assert trim_history(fixed + steps, 1, None) == (fixed + steps, 0)
    assert trim_history(fixed + steps, 1, 10)[0] is None


@pytest.mark.parametrize(
    ("reply", "expected"),
    [("35", 0.35), ("About 80%.", 0.80), ("0.2", 0.2), ("100", 1.0), ("0", 0.0), ("no idea", None),
     ("<think>maybe 90</think>15", 0.15), ("I'd say 10 to 20, so 15", 0.15)],
)
def test_parse_forecast(reply, expected):
    assert parse_forecast(reply) == expected


def test_run_completes_logs_forecast_and_counts_cost():
    model = ScriptedChat(SPEC, ["40", "print('look')", "```python\napis.supervisor.complete_task()\n```"])
    environment = FakeEnvironment()
    trace = run_task(environment, model, "Do it.", SUPERVISOR, max_steps=5)
    assert trace.stop_reason == "completed" and trace.task_completed
    assert trace.forecast.probability_of_failure == 0.40
    assert model.calls[0][-1]["content"] == FORECAST_QUESTION
    assert FORECAST_QUESTION not in "".join(message["content"] for message in model.calls[1])
    assert environment.executed == ["print('look')", "apis.supervisor.complete_task()"]
    totals = trace.totals()
    assert totals["requests"] == 3 and totals["cost_usd"] > 0
    assert classify_failure(False, trace) == "quality" and classify_failure(True, trace) is None


def test_step_limit_and_execution_errors_are_bug_level():
    model = ScriptedChat(SPEC, lambda messages: "boom()")
    trace = run_task(FakeEnvironment(), model, "Do it.", SUPERVISOR, max_steps=3, forecast=False)
    assert trace.stop_reason == "max_steps" and not trace.task_completed
    assert trace.n_execution_failures == 3 and len(trace.steps) == 3
    assert classify_failure(False, trace) == "bug"


def test_reply_without_code_is_not_executed():
    model = ScriptedChat(SPEC, ["<think>only thoughts", "apis.supervisor.complete_task()"])
    environment = FakeEnvironment()
    trace = run_task(environment, model, "Do it.", SUPERVISOR, max_steps=3, forecast=False)
    assert trace.steps[0].had_code is False and trace.steps[0].output == NO_CODE_MESSAGE
    assert environment.executed == ["apis.supervisor.complete_task()"]


def test_cost_cap_stops_before_the_next_request():
    model = ScriptedChat(SPEC, lambda messages: "print(1)")
    budget = Budget(max_usd=0.0001)
    trace = run_task(FakeEnvironment(), model, "Do it.", SUPERVISOR, max_steps=50, forecast=False, budget=budget)
    assert trace.stop_reason == "cost_cap" and len(trace.steps) < 50
    assert classify_failure(False, trace) == "bug"


def test_preload_runs_first_and_a_broken_preload_stops_the_run():
    environment = FakeEnvironment()
    model = ScriptedChat(SPEC, ["apis.supervisor.complete_task()"])
    trace = run_task(environment, model, "Do it.", SUPERVISOR, forecast=False, preload_code="def workflow(): pass")
    assert environment.executed[0] == "def workflow(): pass" and trace.task_completed
    broken = run_task(FakeEnvironment(), ScriptedChat(SPEC, []), "Do it.", SUPERVISOR, forecast=False,
                      preload_code="boom")
    assert broken.stop_reason == "preload_error" and not broken.steps
