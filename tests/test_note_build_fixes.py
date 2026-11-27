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
