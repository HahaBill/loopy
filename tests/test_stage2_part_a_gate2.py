"""Stage 2, part A, gate 2: task lists, completeness, the contrasts and the label. Synthetic rows; no model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


g2 = load("stage2_part_a_gate2", "experiments/stage2/part_a_gate2.py")
SCEN = ["a", "b"]


def run(condition, model, task, success, repeat=1, stop="completed"):
    return {"condition": condition, "model_key": model, "task_id": task, "success": success, "repeat": repeat,
            "stop_reason": stop, "n_steps": 3, "cost_usd": 0.01, "git_commit": "c", "started": "t", "finished": "t"}


def unit(scenario, note, function, control, student="s"):
    return {"student": student, "scenario": scenario, "task": f"{scenario}_2", "note_fixed": note,
            "function_fixed": function, "control_fixed": control, "control_ran": True, "note_eligible": True}


TEACHER_ROWS = [run("cloud_alone", g2.TEACHER, "a_1", True), run("cloud_alone", g2.TEACHER, "b_1", True)]


def alone_rows(student="s"):
    # a: failed version 1, failed 2, passed 3; b: passed version 1 (no note is built), failed 2 and 3
    outcome = {"a_1": False, "a_2": False, "a_3": True, "b_1": True, "b_2": False, "b_3": False}
    return [run("small_alone", student, task, passed) for task, passed in outcome.items()]


def test_control_tasks_are_the_units():
    assert g2.control_tasks(alone_rows(), TEACHER_ROWS, "s", SCEN) == ["a_2"]


def test_retry_lists_missing_runs_and_redoes_at_most_twice():
    rows = alone_rows()[:-1] + [run("small_alone", "s", "b_3", False, stop="model_error")]
    assert g2.retry_lines("small_alone", "s", rows, [], TEACHER_ROWS, SCEN) == ["2 b_3"]
    rows = rows[1:]  # a_1 never ran
    assert g2.retry_lines("small_alone", "s", rows, [], TEACHER_ROWS, SCEN) == ["1 a_1", "2 b_3"]
    rows = alone_rows()[:-1] + [run("small_alone", "s", "b_3", False, repeat=3, stop="model_error")]
    assert g2.retry_lines("small_alone", "s", rows, [], TEACHER_ROWS, SCEN) == []


def test_completeness_needs_every_arm_and_flags_strays_and_unearned_reruns(monkeypatch):
    monkeypatch.setattr(g2, "screen_task_ids", lambda teach: set())
    teach = [{"kind": "coach_checked", "small_model_key": "s", "teacher_model_key": g2.TEACHER, "scenario_id": "a",
              "learn_task_id": "a_1", "status": "built", "cost_usd": 0.1, "attempts": 1},
             {"kind": "coach_checked", "small_model_key": "s", "teacher_model_key": g2.TEACHER, "scenario_id": "b",
              "learn_task_id": "b_1", "status": "skipped_small_passed", "cost_usd": 0.0, "attempts": 0}]
    rows = alone_rows() + [run("coach_checked", "s", t, True) for t in ("a_2", "a_3")]
    rows += [run("compile", "s", t, True) for t in ("a_2", "a_3", "b_2", "b_3")]
    assert any("generic_note runs missing" in r for r in g2.incomplete_reasons(rows, teach, TEACHER_ROWS, [], ("s",), SCEN))
    rows.append(run("generic_note", "s", "a_2", False))
    assert g2.incomplete_reasons(rows, teach, TEACHER_ROWS, [], ("s",), SCEN) == []
    assert any("not part of" in r for r in g2.incomplete_reasons(
        rows + [run("generic_note", "s", "b_2", True)], teach, TEACHER_ROWS, [], ("s",), SCEN))
    assert any("run again after a run that counted" in r for r in g2.incomplete_reasons(
        rows + [run("compile", "s", "a_2", True, repeat=2)], teach, TEACHER_ROWS, [], ("s",), SCEN))
    assert any("note decisions missing" in r for r in g2.incomplete_reasons(rows, teach[:1], TEACHER_ROWS, [], ("s",), SCEN))
    assert g2.incomplete_reasons(rows, teach, TEACHER_ROWS, [], (), SCEN) == ["the screen kept no student"]


def test_contrasts_and_label():
    part_a = [unit("a", 1, 1, 0), unit("b", 1, 1, 1)]
    lower = [unit("a", 0, 1, 0), unit("b", 0, 1, 0), unit("b", 1, 0, 0), unit("a", 0, 1, 0)]
    point = g2.contrasts(part_a, lower)
    assert point["D_A"] == 1 - 0.25 and point["D_A_net"] == 0.75 - 0.5
    assert point["gap_F_minus_N_diff"] == 0 - (0.75 - 0.25) and point["F_diff"] == 1 - 0.75
    assert g2.label_for(point, {"D_A": {"low": 0.1, "high": 0.9}, "D_A_net": {"low": 0.01, "high": 0.8}}) == ("CATCHES UP", True)
    assert g2.label_for(point, {"D_A": {"low": 0.1, "high": 0.9}, "D_A_net": {"low": -0.1, "high": 0.8}}) == ("CATCHES UP", False)
    assert g2.label_for({"D_A": 0.1}, {"D_A": {"low": -0.2, "high": 0.4}}) == ("DOES NOT", False)
    assert g2.label_for({"D_A": 0.2}, {"D_A": {"low": -0.2, "high": 0.4}}) == ("UNDECIDED", False)
    assert g2.label_for(None, {}) == ("UNDECIDED", False)


def test_bootstrap_resamples_both_groups_together_and_counts_empty_draws():
    part_a = [unit("a", 1, 1, 0)]  # only in scenario a
    lower = [unit("b", 0, 1, 0)]  # only in scenario b
    boot = g2.bootstrap(part_a, lower, SCEN, resamples=400, seed=1)
    assert 100 < boot["n_undefined_resamples"] < 300  # a draw of [a, a] or [b, b] leaves one group empty (about half)
    assert boot["intervals_95"]["D_A"] == {"low": 1.0, "high": 1.0}
