"""Coach: the bigger model writes a short note once, from the step where the small model went wrong.

The note is built from a contrast, as the proposal says: the small model's failed run and the bigger
model's passing run on the same task. It is then shown to the small model on later versions of the task.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

MAX_NOTE_LINES = 12

COACH_PROMPT = """\
You are helping a smaller AI assistant that failed a task you solved.

The user gives this KIND of task often, each time with different details (names, amounts, dates, items).
Here is the version both of you just tried:

{instruction}

== How the smaller assistant tried. It FAILED. Its code and the environment's output, step by step ==
{small_run}

== How you did it. This PASSED ==
{cloud_run}

Find the first step where the smaller assistant went wrong, meaning where its approach first departs from
one that works. Then write a short note that will be shown to it the next time it gets this kind of task.

Rules for the note:
- At most {max_lines} lines of plain text.
- Say what to do at the point where it went wrong, and the order of the key steps and API calls that worked.
- Name the mistakes it made that it must avoid.
- The next version will have different details, so do not include values that only fit this version.
- Do not write the full solution code.

Reply in exactly this format and nothing else:
DIVERGENCE_STEP: <the number of the smaller assistant's first wrong step>
FAILURE_KIND: <procedural or capability or unclear>
NOTE:
<the note>

(procedural = it took wrong steps, wrong APIs or a wrong order; capability = it had the right steps but
could not carry them out, for example it kept writing broken code)
"""

GUIDANCE_TEMPLATE = """\
**A note from an expert who has done this kind of task before.** Follow it unless it clearly does not apply to this task:

{note}"""

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)


@dataclass(frozen=True)
class CoachNote:
    note: str
    divergence_step: int | None
    failure_kind: str | None

    def guidance(self) -> str:
        return GUIDANCE_TEMPLATE.format(note=self.note)


def render_run(steps: Sequence[dict[str, Any]], output_limit: int = 1500, max_steps: int | None = None) -> str:
    """A run as text for the bigger model: each step's code and a shortened output."""
    lines: list[str] = []
    shown = steps if max_steps is None else steps[:max_steps]
    for step in shown:
        output = step["output"]
        if len(output) > output_limit:
            output = output[:output_limit] + f"\n... [{len(step['output']) - output_limit} more characters]"
        code = step["code"] if step.get("had_code", True) else "(no code in the reply)"
        lines.append(f"--- Step {step['index']} code ---\n{code}\n--- Step {step['index']} output ---\n{output}")
    if max_steps is not None and len(steps) > max_steps:
        lines.append(f"... [{len(steps) - max_steps} more steps of the same kind, not shown]")
    return "\n\n".join(lines)


def build_coach_prompt(instruction: str, small_steps: Sequence[dict[str, Any]],
                       cloud_steps: Sequence[dict[str, Any]], max_small_steps: int = 30) -> str:
    return COACH_PROMPT.format(
        instruction=instruction.strip(),
        small_run=render_run(small_steps, max_steps=max_small_steps),
        cloud_run=render_run(cloud_steps),
        max_lines=MAX_NOTE_LINES,
    )


def parse_coach_reply(text: str) -> CoachNote:
    text = _THINK_BLOCK.sub("", text).strip()
    step_match = re.search(r"DIVERGENCE_STEP:\s*(\d+)", text)
    kind_match = re.search(r"FAILURE_KIND:\s*(procedural|capability|unclear)", text, re.I)
    note_match = re.search(r"NOTE:\s*\n?(.*)", text, re.S)
    note = (note_match.group(1) if note_match else text).strip()
    note = "\n".join(note.splitlines()[:MAX_NOTE_LINES]).strip()
    if not note:
        raise ValueError("the coach reply has no note")
    return CoachNote(
        note=note,
        divergence_step=int(step_match.group(1)) if step_match else None,
        failure_kind=kind_match.group(1).lower() if kind_match else None,
    )


REVISION_PROMPT = """The smaller assistant tried the same task again with your note in front of it, and it still FAILED.

== Its new run, with your note. Code and output, step by step ==
{run}

Work out why the note was not enough. Either it left something out, or the assistant could not do what the
note said. Then write a better note for this kind of task, under the same rules, and reply in exactly the
same format (DIVERGENCE_STEP, FAILURE_KIND, NOTE).
"""


def build_revision_prompt(student_steps: Sequence[dict[str, Any]], max_steps: int = 30) -> str:
    return REVISION_PROMPT.format(run=render_run(student_steps, max_steps=max_steps))


# The control for "this note" against "any note". Fixed on Nov 23, 2026, before any student ran. It is general advice
# about these apps, written without looking at any task or failure, and shown in the same wrapper as a real note.
GENERIC_NOTE = """Read the task statement carefully and work out exactly what must change and what must stay as it is.
Look at the available apps and their API documentation before you call an API.
Check the required arguments of each API before calling it.
When an API returns results in pages, retrieve every page.
After you change something, read it back to confirm the change.
Do not change anything the task does not ask you to change.
When you are done, call the API that marks the task complete, with the answer if the task asks for one."""


def generic_guidance() -> str:
    return GUIDANCE_TEMPLATE.format(note=GENERIC_NOTE)
