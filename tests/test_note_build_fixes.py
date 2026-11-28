"""Review items 4, 5 and 7 of experiments/stage1/OPEN_REVIEW_FINDINGS.md, in the note builder. No model, no AppWorld."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder = load("note_builder_under_test", "experiments/pilot/build_coach_checked.py")
audit = load("ledger_audit_for_note_builds", "experiments/stage1/ledger_vs_rows.py")


def write_rows(folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_the_runs_own_row_wins_over_the_source_run(tmp_path):  # item 5
    local, source = tmp_path / "local", tmp_path / "source"
    row = {"task_id": "s_1", "condition": "small_alone", "model_key": "m", "repeat": 1}
    write_rows(local, [{**row, "success": True}])
    write_rows(source, [{**row, "success": False}, {"task_id": "s_1", "condition": "cloud_alone", "model_key": "t",
                                                    "repeat": 1, "success": True}])
    records = builder.load_records([local, source])
    picked = builder.find_record(records, "s_1", "small_alone", "m")
    assert picked["success"] is True and picked["_folder"] == str(local)
    teacher = builder.find_record(records, "s_1", "cloud_alone", "t")
    assert teacher["_folder"] == str(source)  # only the source run has it, and its file is read from there


def test_the_ledger_note_names_the_scenario_the_audit_reads(tmp_path):  # item 7
    note = builder.ledger_note("student-x", "abc1234")
    assert note.split(" ") == ["build_coach_checked", "student-x", "abc1234"]
    teach = [{"kind": "coach_checked", "small_model_key": "student-x", "scenario_id": "abc1234", "cost_usd": 0.3}]
    ledger = [{"run": "r", "note": note, "usd": 0.1}, {"run": "r", "note": note, "usd": 0.2}]
    report = audit.compare_note_builds(teach, ledger, "r")
    assert report["n_builds_compared"] == 1 and report["n_builds_that_differ"] == 0


def test_a_restart_reads_the_latest_pending_state(tmp_path):  # item 4
    assert builder.pending_state(tmp_path) is None
    state = {key: [] for key in builder.RESUME_KEYS}
    state.update(teacher_cost_usd=0.02, student_cost_usd=0.05, teacher_calls=2, student_requests=9,
                 cut_off_requests=0, first=None, attempts=[{"attempt": 1, "passed": False}])
    (tmp_path / "coach_checked_PENDING_log_20261125_010000.json").write_text(
        json.dumps({**state, "attempts": []}), encoding="utf-8")
    (tmp_path / "coach_checked_PENDING_log_20261125_020000.json").write_text(json.dumps(state), encoding="utf-8")
    found = builder.pending_state(tmp_path)
    assert found["file"].endswith("020000.json")
    assert len(found["attempts"]) == 1 and found["teacher_cost_usd"] == 0.02  # attempts and spend carry over


def test_a_pending_log_without_the_state_to_resume_stops_the_builder(tmp_path):
    (tmp_path / "coach_checked_PENDING_log_20261125_010000.json").write_text(
        json.dumps({"prompt": "p", "attempts": [], "teacher_cost_usd": 0.01}), encoding="utf-8")
    with pytest.raises(SystemExit):
        builder.pending_state(tmp_path)


skills_builder = load("function_builder_under_test", "experiments/pilot/build_skills.py")


def test_an_interrupted_function_build_resumes_with_its_attempts_and_spend(tmp_path):  # item 4, function builder
    assert skills_builder.compile_pending_state(tmp_path) is None
    state = {"messages": [{"role": "user", "content": "p"}], "attempts": [{"attempt": 1, "passed": False}],
             "usages": [{"requests": 1, "cost_usd": 0.2}], "last_error": None}
    (tmp_path / "compile_PENDING_20261127_010000.json").write_text(json.dumps({**state, "attempts": []}), encoding="utf-8")
    (tmp_path / "compile_PENDING_20261127_020000.json").write_text(json.dumps(state), encoding="utf-8")
    found = skills_builder.compile_pending_state(tmp_path)
    assert found["file"].endswith("020000.json") and len(found["attempts"]) == 1 and found["usages"][0]["cost_usd"] == 0.2
    (tmp_path / "compile_PENDING_20261127_030000.json").write_text(json.dumps({"attempts": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        skills_builder.compile_pending_state(tmp_path)


def test_a_finished_build_retires_its_checkpoints(tmp_path):
    (tmp_path / "compile_PENDING_20261127_010000.json").write_text("{}", encoding="utf-8")
    skills_builder.retire_pending(tmp_path, skills_builder.COMPILE_PENDING_GLOB)
    assert skills_builder.compile_pending_state(tmp_path) is None
    assert (tmp_path / "compile_RESUMED_20261127_010000.json").exists()


def test_two_budgets_share_one_invocation_guard_and_stop_before_the_cap(tmp_path):
    from loopy.agent.react import Budget, CostCapReached
    teacher, student = Budget(max_usd=6.0), Budget(max_usd=6.0)
    teacher.shares_cap_with, student.shares_cap_with = student, teacher
    teacher.add(4.0)
    student.add(1.5)
    teacher.check()
    student.add(1.0)
    for budget in (teacher, student):
        with pytest.raises(CostCapReached):
            budget.check()
    ledger = tmp_path / "ledger.jsonl"
    reserved = Budget(ledger=ledger, provider="openai.com", ledger_cap=90.0, reserve_usd=4.0)
    reserved.add(85.5)
    reserved.check()
    reserved.add(0.6)
    with pytest.raises(CostCapReached):
        reserved.check()


def test_a_checkpoint_is_resumed_only_by_the_same_teacher_student_and_task(tmp_path):
    state = {"messages": [], "attempts": [], "usages": [], "last_error": None, "teacher_model_key": "t",
             "small_model_key": "shared", "learn_task_id": "a_1"}
    (tmp_path / "compile_PENDING_20261127_010000.json").write_text(json.dumps(state), encoding="utf-8")
    same = {"teacher_model_key": "t", "small_model_key": "shared", "learn_task_id": "a_1"}
    assert skills_builder.compile_pending_state(tmp_path, same)["learn_task_id"] == "a_1"
    with pytest.raises(SystemExit):
        skills_builder.compile_pending_state(tmp_path, {**same, "teacher_model_key": "another"})


def test_a_request_that_fails_after_a_paid_part_reports_what_was_paid():
    from loopy.agent.llm import ModelSpec, Reply
    from loopy.agent.react import Budget
    from loopy.skills.teach import PaidRequestFailed, complete_uncut

    class Chat:
        calls = 0

        def __init__(self, spec):
            self.spec = spec

        def complete(self, messages):
            Chat.calls += 1
            if Chat.calls == 1:  # cut off by the output limit: paid for, sent again with more room
                return Reply(text="partial", input_tokens=1000, output_tokens=100, seconds=1.0, finish_reason="length")
            raise ConnectionError("provider down")

    spec = ModelSpec(key="t", role="cloud", name="t", usd_per_mtok_in=1.0, usd_per_mtok_out=1.0, max_tokens=100)
    with pytest.raises(PaidRequestFailed) as caught:
        complete_uncut(spec, [{"role": "user", "content": "x"}], Budget(), make_chat=Chat)
    assert caught.value.usage["requests"] == 1 and abs(caught.value.usage["cost_usd"] - 0.0011) < 1e-12
