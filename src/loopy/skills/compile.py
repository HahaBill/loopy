"""Compile: save the bigger model's working solution as one function the small model only has to call.

The function is checked before it counts as bought: it must solve the task it was built from again, in a
fresh copy of the apps. A function that fails that check is a failed compile, and its cost still counts.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any, Sequence

from loopy.skills.coach import render_run

FUNCTION_NAME = "workflow"

COMPILE_PROMPT = """\
You solved this task and your solution PASSED. The user gives this KIND of task often, each time with
different details (names, amounts, dates, items).

The version you just solved:

{instruction}

== Your working run, step by step ==
{cloud_run}

Write ONE Python function that does this kind of task from start to finish, so that a smaller assistant
only has to call it with the right arguments.

Rules:
- The signature is `def {name}(apis, ...)` with one parameter for every value that can change between
  versions of the task. Nothing that only fits this version may be hard-coded.
- Inside, use only `apis.<app>.<api>(...)` calls and the Python standard library. The function must get
  the passwords it needs from `apis.supervisor.show_account_passwords()`, log in, and read every page of
  paged results.
- Do NOT call `apis.supervisor.complete_task` inside the function. Return the answer if the task asks for
  information, otherwise return None.
- Give it a docstring that explains every parameter with an example value.

Reply in exactly this format and nothing else:
```python
def {name}(apis, ...):
    ...
```
CALL_FOR_THIS_TASK:
```python
result = {name}(apis, ...)
```
"""

REPAIR_PROMPT = """\
The function was run on the same task in a fresh copy of the apps with your call, and it did not pass.

Output of running it:
{output}

Result: {verdict}

Fix the function and reply again in exactly the same format (the function, then CALL_FOR_THIS_TASK).
"""

GUIDANCE_TEMPLATE = """\
**A saved workflow for this kind of task is already defined in your Python environment.** You do not need to write it:

{signature}
    \"\"\"{docstring}\"\"\"

To do the task:
1. Call it with the right arguments for THIS task: `result = {name}(apis, ...)`, then `print(result)`.
2. Then call `apis.supervisor.complete_task(answer=result)` if the task asks for information, or `apis.supervisor.complete_task()` if it does not.
If the call raises an error, read it, fix the arguments and call it again. Do not rewrite the workflow yourself unless it keeps failing."""

# Stage 2, part B: the same function handed over as text inside a note, not loaded. Fixed on Nov 24, 2026, before any
# run of that arm. The student has to do whatever it does with the code itself.
TEXT_NOTE_TEMPLATE = """\
The expert wrote the Python function below for this kind of task. It is NOT defined in your environment. You can copy \
it into your code and call it with the right arguments for this task, change it, or use it only as a guide to the steps.

```python
{source}
```"""


def as_text_note(source: str) -> str:
    """The body of a note that carries a compiled function as text."""
    return TEXT_NOTE_TEMPLATE.format(source=source.strip())


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_FENCE = re.compile(r"```[A-Za-z0-9_+-]*[ \t]*\n(.*?)```", re.S)


@dataclass(frozen=True)
class CompiledWorkflow:
    source: str  # the function definition
    call: str  # the call that solves the task it was built from

    def signature(self) -> str:
        return _function_parts(self.source)[0]

    def docstring(self) -> str:
        return _function_parts(self.source)[1]

    def guidance(self) -> str:
        signature, docstring = _function_parts(self.source)
        return GUIDANCE_TEMPLATE.format(signature=signature, docstring=docstring, name=FUNCTION_NAME)

    def validation_code(self) -> str:
        """Define the function, make the call it was built with, and declare the task done."""
        return (
            f"{self.source}\n\n{self.call}\n"
            "if result is None:\n    apis.supervisor.complete_task()\n"
            "else:\n    apis.supervisor.complete_task(answer=result)\n"
        )


def _function_parts(source: str) -> tuple[str, str]:
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == FUNCTION_NAME]
    if not functions:
        raise ValueError(f"no top-level function named {FUNCTION_NAME}")
    function = functions[0]
    first_line = source.splitlines()[function.lineno - 1 : function.body[0].lineno - 1]
    signature = "\n".join(first_line).rstrip() or f"def {FUNCTION_NAME}(apis, ...):"
    docstring = ast.get_docstring(function) or "(no description)"
    return signature, docstring


def build_compile_prompt(instruction: str, cloud_steps: Sequence[dict[str, Any]]) -> str:
    return COMPILE_PROMPT.format(instruction=instruction.strip(), cloud_run=render_run(cloud_steps),
                                 name=FUNCTION_NAME)


def build_repair_prompt(output: str, passed_checker: bool, output_limit: int = 3000) -> str:
    verdict = "it ran, but the apps did not end in the right state" if not passed_checker else "passed"
    if output.startswith("Execution failed."):
        verdict = "it raised an error"
    return REPAIR_PROMPT.format(output=output[:output_limit], verdict=verdict)


def parse_compile_reply(text: str) -> CompiledWorkflow:
    text = _THINK_BLOCK.sub("", text)
    blocks = [block.strip("\n") for block in _FENCE.findall(text)]
    sources = [block for block in blocks if re.search(rf"^def {FUNCTION_NAME}\(", block, re.M)]
    calls = [block for block in blocks if re.search(rf"\b{FUNCTION_NAME}\(apis", block)
             and not re.search(rf"^def {FUNCTION_NAME}\(", block, re.M)]
    if not sources:
        raise ValueError(f"the reply has no `def {FUNCTION_NAME}(` block")
    if not calls:
        raise ValueError("the reply has no CALL_FOR_THIS_TASK block")
    source, call = sources[0].strip(), calls[0].strip()
    ast.parse(source)
    ast.parse(call)
    if "complete_task" in source:
        raise ValueError("the function must not call complete_task")
    if not re.search(r"^result\s*=", call, re.M):
        call = "result = " + call
    _function_parts(source)
    return CompiledWorkflow(source=source, call=call)
