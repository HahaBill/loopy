"""Coach notes and compiled workflows: prompt building and reply parsing. No model needed."""

import pytest

from loopy.skills.coach import MAX_NOTE_LINES, build_coach_prompt, parse_coach_reply, render_run
from loopy.skills.compile import build_compile_prompt, build_repair_prompt, parse_compile_reply

STEPS = [
    {"index": 1, "code": "print(apis.api_docs.show_app_descriptions())", "output": "[...]", "had_code": True},
    {"index": 2, "code": "", "output": "No code found in your reply.", "had_code": False},
    {"index": 3, "code": "x = 1", "output": "y" * 5000, "had_code": True},
]

COMPILE_REPLY = '''Here you go.
```python
def workflow(apis, playlist_title, genre="rock"):
    """Like every song of a genre in a playlist.

    playlist_title: the playlist's title, for example "Road Trip".
    genre: the genre to like, for example "rock".
    """
    token = apis.spotify.login(username="u", password="p")["access_token"]
    return None
```
CALL_FOR_THIS_TASK:
```python
result = workflow(apis, playlist_title="Road Trip")
```
'''


def test_render_run_shortens_outputs_and_marks_missing_code():
    text = render_run(STEPS, output_limit=100)
    assert "--- Step 1 code ---" in text and "(no code in the reply)" in text
    assert "4900 more characters" in text
    assert "1 more steps" in render_run(STEPS, max_steps=2)


def test_coach_prompt_contains_both_runs_and_the_task():
    prompt = build_coach_prompt("Like my most played song.", STEPS, STEPS[:1])
    assert "Like my most played song." in prompt and "It FAILED" in prompt and "This PASSED" in prompt
    assert "DIVERGENCE_STEP:" in prompt


def test_parse_coach_reply_reads_the_three_fields_and_caps_the_note():
    reply = "<think>hm</think>DIVERGENCE_STEP: 4\nFAILURE_KIND: Procedural\nNOTE:\n" + "\n".join(
        f"line {index}" for index in range(30))
    note = parse_coach_reply(reply)
    assert note.divergence_step == 4 and note.failure_kind == "procedural"
    assert len(note.note.splitlines()) == MAX_NOTE_LINES
    assert note.guidance().startswith("**A note from an expert") and "line 0" in note.guidance()


def test_parse_coach_reply_without_headers_keeps_the_text_and_rejects_empty():
    note = parse_coach_reply("Log in first, then pass access_token to every call.")
    assert note.divergence_step is None and note.failure_kind is None and "access_token" in note.note
    with pytest.raises(ValueError):
        parse_coach_reply("NOTE:\n")


def test_parse_compile_reply_and_guidance():
    workflow = parse_compile_reply(COMPILE_REPLY)
    assert workflow.source.startswith("def workflow(apis, playlist_title")
    assert workflow.call == 'result = workflow(apis, playlist_title="Road Trip")'
    assert workflow.signature() == 'def workflow(apis, playlist_title, genre="rock"):'
    guidance = workflow.guidance()
    assert "already defined in your Python environment" in guidance and "playlist_title: the playlist" in guidance
    assert "login(" not in guidance  # the small model sees the signature and docstring, not the body
    code = workflow.validation_code()
    assert code.index("def workflow") < code.index("result = workflow") < code.index("complete_task")


def test_parse_compile_reply_rejects_bad_replies():
    with pytest.raises(ValueError):
        parse_compile_reply("no code here")
    with pytest.raises(ValueError):
        parse_compile_reply("```python\ndef workflow(apis):\n    return 1\n```")
    with pytest.raises(ValueError):
        parse_compile_reply(COMPILE_REPLY.replace("return None", "apis.supervisor.complete_task()"))
    with pytest.raises(SyntaxError):
        parse_compile_reply(COMPILE_REPLY.replace("return None", "return ((("))


def test_compile_and_repair_prompts():
    assert "def workflow(apis, ...)" in build_compile_prompt("Do it.", STEPS)
    assert "raised an error" in build_repair_prompt("Execution failed. Traceback: boom", False)
    assert "did not end in the right state" in build_repair_prompt("None", False)
