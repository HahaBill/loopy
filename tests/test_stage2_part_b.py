"""Stage 2, part B: the function handed over as text. Synthetic rows only; no model, no AppWorld."""

from __future__ import annotations

import importlib.util
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


part_b = load("stage2_part_b", "experiments/stage2/part_b.py")
run_arm = load("pilot_run_arm_for_part_b", "experiments/pilot/run_arm.py")


def run(condition, model, task, success, repeat=1, stop="completed", steps=5, cost=0.01):
    return {"condition": condition, "model_key": model, "task_id": task, "success": success, "repeat": repeat,
            "stop_reason": stop, "n_steps": steps, "cost_usd": cost}


def build(kind, owner, scenario, status="built"):
    return {"kind": kind, "small_model_key": owner, "scenario_id": scenario, "status": status}


def test_code_note_shows_the_function_as_text_and_loads_nothing(tmp_path):
    folder = tmp_path / "abc1234"
    folder.mkdir()
    (folder / "compiled_workflow.py").write_text("def workflow(apis, x):\n    return x\n", encoding="utf-8")
    (folder / "compiled_guidance.txt").write_text("already defined", encoding="utf-8")
    guidance, preload = run_arm.load_skill(tmp_path, "code_note", "abc1234")
    assert preload is None
    assert "def workflow(apis, x):" in guidance and "NOT defined in your environment" in guidance
    assert guidance.startswith("**A note from an expert")  # the same wrapper as a coach note
    assert "already defined" not in guidance
    loaded_guidance, loaded_code = run_arm.load_skill(tmp_path, "compile", "abc1234")
    assert loaded_code.startswith("def workflow") and loaded_guidance == "already defined"


def test_code_note_needs_the_skill_folder():
    with pytest.raises(SystemExit):
        run_arm.check_skill_arguments("code_note", None)
    run_arm.check_skill_arguments("code_note", "some/folder")


def test_tasks_are_versions_2_and_3_of_built_functions_only():
    teach = [build("compile", "shared", "bbb"), build("compile", "shared", "aaa"),
             build("compile", "shared", "ccc", "failed_validation"), build("coach_checked", "s", "ddd")]
    assert part_b.part_b_tasks(teach) == ["aaa_2", "aaa_3", "bbb_2", "bbb_3"]


def test_check_names_missing_bad_stray_and_unearned_reruns():
    tasks, students = ["aaa_2", "aaa_3"], ("s1",)
    assert part_b.incomplete_reasons(tasks, [], students) == ["s1: 2 of 2 runs missing"]
    rows = [run("code_note", "s1", "aaa_2", True), run("code_note", "s1", "aaa_3", False, stop="cost_cap")]
    assert part_b.incomplete_reasons(tasks, rows, students) == ["s1: 1 runs ended in an infrastructure error or a spend stop"]
    assert part_b.retry_lines(tasks, rows, "s1") == ["2 aaa_3"]
    rows.append(run("code_note", "s1", "aaa_3", True, repeat=2))
    assert part_b.incomplete_reasons(tasks, rows, students) == []
    assert part_b.retry_lines(tasks, rows, "s1") == []
    # a second run after a run that counted is not accepted
    again = rows + [run("code_note", "s1", "aaa_2", False, repeat=2)]
    assert any("rerun after a run that counted" in reason for reason in part_b.incomplete_reasons(tasks, again, students))
    stray = rows + [run("code_note", "s1", "zzz_2", True)]
    assert any("not part B runs" in reason for reason in part_b.incomplete_reasons(tasks, stray, students))


def test_share_recovered_and_labels():
    # 4 scenarios, one student, every test task failed alone, a note built everywhere.
    # note fixes 1 of 8, function 7 of 8, text 4 of 8: recovered = (4 - 1) / (7 - 1) = 0.5
    scenarios = ["a", "b", "c", "d"]
    tasks = [f"{scenario}_{version}" for scenario in scenarios for version in (2, 3)]
    teach = [build("compile", "shared", scenario) for scenario in scenarios] + [
        build("coach_checked", "s1", scenario) for scenario in scenarios]
    note_ok, function_bad, text_ok = {"a_2"}, {"d_3"}, {"a_2", "a_3", "b_2", "b_3"}
    stage1, part = [], []
    for task in tasks:
        stage1 += [run("small_alone", "s1", task, False), run("coach_checked", "s1", task, task in note_ok),
                   run("compile", "s1", task, task not in function_bad)]
        part.append(run("code_note", "s1", task, task in text_ok))
    report = part_b.analyze(stage1, teach, part, tasks, students=("s1",))
    pooled = report["pooled"]
    assert pooled["n_both_built"] == 8 and pooled["n_failed_alone"] == 8
    assert pooled["note"] == 1 / 8 and pooled["function"] == 7 / 8 and pooled["text"] == 4 / 8
    assert pooled["share_recovered"] == pytest.approx(0.5)
    assert pooled["function_minus_text_all"] == pytest.approx(3 / 8)
    assert report["label"] in ("MIXED", "MOSTLY WHAT IS SAID", "MOSTLY HOW IT ARRIVES")
    assert report["intervals_95"]["share_recovered"]["low"] <= 0.5 <= report["intervals_95"]["share_recovered"]["high"]
    assert part_b.label_for({"low": 0.6, "high": 0.9}) == "MOSTLY WHAT IS SAID"
    assert part_b.label_for({"low": 0.0, "high": 0.4}) == "MOSTLY HOW IT ARRIVES"
    assert part_b.label_for({"low": 0.2, "high": 0.7}) == "MIXED"
    assert part_b.label_for(None) == "INCONCLUSIVE"


def test_harm_counts_tasks_passed_alone_and_no_note_means_not_in_the_note_set():
    tasks = ["a_2", "a_3"]
    teach = [build("compile", "shared", "a"), build("coach_checked", "s1", "a", "failed_validation")]
    stage1 = [run("small_alone", "s1", "a_2", True), run("compile", "s1", "a_2", False),
              run("small_alone", "s1", "a_3", False), run("compile", "s1", "a_3", True)]
    part = [run("code_note", "s1", "a_2", True), run("code_note", "s1", "a_3", False)]
    report = part_b.analyze(stage1, teach, part, tasks, students=("s1",))
    assert report["harm_on_tasks_passed_alone"]["s1"] == {"passed_alone": 1, "broken_with_function": 1,
                                                          "broken_with_text": 0}
    assert report["pooled"]["n_both_built"] == 0 and report["pooled"]["share_recovered"] is None
    assert report["label"] == "INCONCLUSIVE"
    assert report["pooled"]["function_all"] == 1.0 and report["pooled"]["text_all"] == 0.0
