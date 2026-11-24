"""The stage 1 reading rules and the fixes from review, on hand-made records. No model needed."""

import importlib.util
import json
from pathlib import Path

import pytest

from loopy.agent.react import Budget, CostCapReached
from loopy.eval.runlog import append_jsonl, ledger_total, read_jsonl

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


stage1 = load("stage1_analysis_under_test", "experiments/stage1/analyze_stage1.py")
pilot = load("pilot_analyze_under_test", "experiments/pilot/analyze.py")
sweep = load("stage1_sweep_under_test", "experiments/stage1/sweep.py")
run_arm = load("run_arm_under_test", "experiments/pilot/run_arm.py")
ledger_check = load("ledger_vs_rows_under_test", "experiments/stage1/ledger_vs_rows.py")

SCENARIOS = ["a", "b", "c", "d"]
STUDENTS = ("lo", "hi")


def run(condition, model, task, success, repeat=1):
    scenario, version = task.rsplit("_", 1)
    return {"condition": condition, "model_key": model, "task_id": task, "scenario_id": scenario, "version": int(version),
            "success": success, "repeat": repeat, "stop_reason": "completed", "failure_type": None if success else "bug",
            "cost_usd": 0.01, "cloud_calls": 0, "requests": 1, "input_tokens": 10, "output_tokens": 5,
            "model_seconds": 1.0, "wall_seconds": 2.0, "n_steps": 3}


def build(kind, owner, scenario, status):
    return {"kind": kind, "small_model_key": owner, "scenario_id": scenario, "status": status, "cost_usd": 0.02}


def fixture():
    """lo fails everything. hi passes a_1, b_1 and all of b, and fails a_2, a_3, c and d."""
    runs, teach = [], []
    for scenario in SCENARIOS:
        teach.append(build("compile", "shared", scenario, "built"))
        for version in (1, 2, 3):
            task = f"{scenario}_{version}"
            runs.append(run("cloud_alone", "t", task, True))
            runs.append(run("small_alone", "lo", task, False))
            hi_passes = scenario == "b" or (scenario == "a" and version == 1)
            runs.append(run("small_alone", "hi", task, hi_passes))
        for student in STUDENTS:
            for version in (2, 3):
                runs.append(run("compile", student, f"{scenario}_{version}", True))
    for scenario in SCENARIOS:
        teach.append(build("coach_checked", "lo", scenario, "built" if scenario == "a" else "failed_validation"))
    runs += [run("coach_checked", "lo", "a_2", True), run("coach_checked", "lo", "a_3", False)]
    teach += [build("coach_checked", "hi", "a", "skipped_small_passed"), build("coach_checked", "hi", "b", "skipped_small_passed"),
              build("coach_checked", "hi", "c", "built"), build("coach_checked", "hi", "d", "built")]
    runs += [run("coach_checked", "hi", "c_2", True), run("coach_checked", "hi", "c_3", True),
             run("coach_checked", "hi", "d_2", True), run("coach_checked", "hi", "d_3", False)]
    return runs, teach


def test_rates_on_hand_counted_records():
    runs, teach = fixture()
    report = stage1.analyze(runs, teach, SCENARIOS, STUDENTS, "t", n_resamples=200)
    written = report["secondary_as_first_written"]
    # lo: 8 failed tasks, the note fixes a_2. hi: 6 failed tasks (a_2, a_3, c, d), the note fixes c_2, c_3, d_2.
    assert written["n_units"] == 14 and written["note_lower"] == pytest.approx(1 / 8)
    assert written["note_upper"] == pytest.approx(3 / 6) and written["D"] == pytest.approx(3 / 6 - 1 / 8)
    assert written["function_lower"] == 1.0 and written["function_upper"] == 1.0
    assert written["H2"] == pytest.approx((1 - 1 / 8) - (1 - 3 / 6))
    eligible = report["primary_note_eligible"]  # a_2 and a_3 of hi drop out: hi passed a_1
    assert eligible["n_units"] == 12 and eligible["note_upper"] == pytest.approx(3 / 4)
    assert report["per_student"]["hi"]["tier"] == "upper" and report["per_student"]["lo"]["tier"] == "lower"
    assert report["per_student"]["hi"]["harm"]["function"] == {"passed_alone_and_ran_with_skill": 2, "failed_with_skill": 0}


def test_generic_note_control_is_read_on_the_primary_tasks():
    runs, teach = fixture()
    primary = stage1.analyze(runs, teach, SCENARIOS, STUDENTS, "t", n_resamples=200)["primary_note_eligible"]
    assert primary["generic_note_control"]["n_units_without_a_control_run"] == 12
    assert primary["generic_note_control"]["D_net_of_control"] is None
    for student, task_list in (("lo", [f"{s}_{v}" for s in SCENARIOS for v in (2, 3)]),
                               ("hi", ["c_2", "c_3", "d_2", "d_3"])):
        passes = "a_2" if student == "lo" else "c_2"  # 1 of lo's 8 tasks, 1 of hi's 4
        runs += [run("generic_note", student, task, task == passes) for task in task_list]
    control = stage1.analyze(runs, teach, SCENARIOS, STUDENTS, "t", n_resamples=200)["primary_note_eligible"]
    block = control["generic_note_control"]
    assert block["n_units_without_a_control_run"] == 0 and block["control_lower"] == pytest.approx(1 / 8)
    assert block["control_upper"] == pytest.approx(1 / 4) and block["D_control"] == pytest.approx(1 / 8)
    assert block["D_net_of_control"] == pytest.approx((3 / 4 - 1 / 8) - 1 / 8)


@pytest.mark.parametrize("label, net_low, missing, expected", [
    ("SUPPORTED", 0.05, 0, "SUPPORTED and beyond a generic note"),
    ("SUPPORTED", -0.05, 0, "SUPPORTED but not separated from a generic note"),
    ("SUPPORTED", None, 3, "SUPPORTED, control not finished: do not quote"),
    ("INCONCLUSIVE", 0.05, 0, "INCONCLUSIVE"),
])
def test_what_may_be_quoted(label, net_low, missing, expected):
    assert stage1.claim_label(label, net_low, missing) == expected


def test_control_runs_on_tasks_where_a_note_was_eligible(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "RUN_DIR", tmp_path)
    monkeypatch.setattr(sweep, "TEACHER", "t")
    for row in (run("cloud_alone", "t", "a_1", True), run("cloud_alone", "t", "b_1", True), run("cloud_alone", "t", "c_1", False),
                run("small_alone", "s", "a_1", False), run("small_alone", "s", "a_2", False), run("small_alone", "s", "a_3", True),
                run("small_alone", "s", "b_1", True), run("small_alone", "s", "b_2", False),
                run("small_alone", "s", "c_1", False), run("small_alone", "s", "c_2", False)):
        append_jsonl(tmp_path / "runs.jsonl", row)
    assert sweep.control_tasks("s") == ["a_2"]


def test_equal_student_weight_differs_from_pooling():
    units = [{"student": "x", "scenario": "a", "task": f"a_{i}", "tier": "lower", "note_eligible": True,
              "note_fixed": i == 0, "function_fixed": True} for i in range(4)]
    units += [{"student": "y", "scenario": "a", "task": "a_9", "tier": "lower", "note_eligible": True, "note_fixed": True,
               "function_fixed": True}]
    table = stage1.cells(units, ["a"], ("x", "y"))[0]
    assert stage1.tier_rate(table, [0, 1], 1, False) == pytest.approx(2 / 5)
    assert stage1.tier_rate(table, [0, 1], 1, True) == pytest.approx((1 / 4 + 1) / 2)


@pytest.mark.parametrize("d, low, high, function, both, expected", [
    (0.40, 0.10, 0.70, 0.80, True, "SUPPORTED"),
    (0.10, 0.01, 0.20, 0.70, True, "SUPPORTED"),
    (0.40, 0.10, 0.70, 0.60, True, "INCONCLUSIVE"),
    (0.10, -0.10, 0.30, 0.90, True, "NOT SUPPORTED"),
    (0.30, -0.05, 0.60, 0.90, True, "INCONCLUSIVE"),
    (-0.30, -0.60, -0.10, 0.90, True, "INCONCLUSIVE"),
    (0.40, 0.10, 0.70, 0.90, False, "INCONCLUSIVE"),
    (None, None, None, None, True, "INCONCLUSIVE"),
])
def test_labels_follow_the_protocol(d, low, high, function, both, expected):
    assert stage1.h1_label(d, low, high, function, both) == expected


def test_bootstrap_is_repeatable_and_resamples_scenarios():
    first, second = stage1.draws(30, 50), stage1.draws(30, 50)
    assert first == second and all(sum(row) == 30 for row in first)
    assert stage1.percentile([0.0, 1.0], 0.25) == 0.25
    assert stage1.interval([None, 1.0, 1.0])["n_undefined_resamples"] == 1


def test_recount_catches_a_record_that_disagrees_with_its_raw_file(tmp_path):
    row = run("compile", "s", "a_2", True)
    raw = tmp_path / "raw_large"
    raw.mkdir()
    (raw / "compile__s__a_2__r1.json").write_text(json.dumps(
        {"evaluation": {"success": False}, "guidance": "g", "preload_code": "c"}), encoding="utf-8")
    assert stage1.recount_from_raw(tmp_path, [row])["problems"] == ["success differs from raw: compile__s__a_2__r1.json"]
    assert "missing raw file" in stage1.recount_from_raw(tmp_path, [run("compile", "s", "b_2", True)])["problems"][0]


def manifest(tmp_path, scenarios):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps({"chosen": [{"scenario_id": scenario} for scenario in scenarios]}), encoding="utf-8")
    return path


def complete_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "RUN_DIR", tmp_path)
    monkeypatch.setattr(sweep, "SCENARIO_FILE", manifest(tmp_path, ["a"]))
    monkeypatch.setattr(sweep, "STUDENTS", ("s",))
    monkeypatch.setattr(sweep, "TEACHER", "t")
    monkeypatch.setattr(sweep, "N_SCENARIOS", 1)
    monkeypatch.setattr(sweep, "N_TASKS", 3)
    monkeypatch.setattr(sweep, "AUDITED_LOST_TRIES", {"a"})
    for version in (1, 2, 3):
        append_jsonl(tmp_path / "runs.jsonl", run("cloud_alone", "t", f"a_{version}", True))
        append_jsonl(tmp_path / "runs.jsonl", run("small_alone", "s", f"a_{version}", True))
    for version in (2, 3):
        append_jsonl(tmp_path / "runs.jsonl", run("compile", "s", f"a_{version}", True))
    append_jsonl(tmp_path / "teach.jsonl", build("coach_checked", "s", "a", "skipped_small_passed"))


def test_check_requires_teacher_runs_function_decisions_and_audited_rebuilds(tmp_path, monkeypatch):
    complete_files(tmp_path, monkeypatch)
    assert "0 of 1 function decisions" in sweep.incomplete_reasons()
    append_jsonl(tmp_path / "teach.jsonl", build("compile", "shared", "a", "failed_validation"))
    assert any("function rebuilds not finished: a" in reason for reason in sweep.incomplete_reasons())
    append_jsonl(tmp_path / "teach.jsonl", {**build("compile", "shared", "a", "built"), "cutoff_fix_version": 3})
    assert sweep.incomplete_reasons() == []
    rows = [row for row in read_jsonl(tmp_path / "runs.jsonl") if row["condition"] != "cloud_alone" or row["task_id"] != "a_3"]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert "t: 2 of 3 teacher runs" in sweep.incomplete_reasons()


def test_latest_repeat_keeps_the_resources_of_every_try():
    merged = pilot.latest_repeats([run("cloud_alone", "t", "a_1", False), run("cloud_alone", "t", "a_1", True, repeat=2)])
    assert len(merged) == 1 and merged[0]["success"] is True
    assert merged[0]["wall_seconds"] == 4.0 and merged[0]["input_tokens"] == 20 and merged[0]["n_steps"] == 6


def test_budget_writes_each_request_and_sees_the_spend_of_other_jobs(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    one = Budget(max_usd=10, ledger=ledger, provider="p", run_name="r", note="one", ledger_cap=1.0)
    two = Budget(max_usd=10, ledger=ledger, provider="p", run_name="r", note="two", ledger_cap=1.0)
    one.add(0.6)
    two.check()
    two.add(0.5)
    assert ledger_total(ledger, "p") == pytest.approx(1.1) and len(read_jsonl(ledger)) == 2
    with pytest.raises(CostCapReached):
        one.check()


# The fixes from the review of Nov 24, 2026.


def priced(row, usd):
    return {**row, "cost_usd": usd}


def test_break_even_that_counts_failed_runs_and_failed_builds():
    """s fails every task alone except e_1. Rent costs 0.10 a task, 0.30 for b_3. The teacher fails f_2 and f_3."""
    scenarios, runs, teach = ["a", "b", "c", "d", "e", "f"], [], []
    for scenario in scenarios:
        for version in (1, 2, 3):
            task = f"{scenario}_{version}"
            runs.append(priced(run("cloud_alone", "t", task, not (scenario == "f" and version > 1)),
                               0.30 if task == "b_3" else 0.10))
            runs.append(run("small_alone", "s", task, task == "e_1"))
        teach.append(priced(build("compile", "shared", scenario, "failed_validation" if scenario == "c" else "built"), 0.09))
    function_passes = {"a_2", "a_3", "b_2", "e_2", "e_3"}  # b fixes one of two, d fixes none, c was never built
    runs += [priced(run("compile", "s", f"{scenario}_{version}", f"{scenario}_{version}" in function_passes), 0.01)
             for scenario in "abdef" for version in (2, 3)]
    teach += [priced(build("coach_checked", "s", "a", "built"), 0.02),
              priced(build("coach_checked", "s", "b", "failed_validation"), 0.02),
              priced(build("coach_checked", "s", "c", "failed_validation"), 0.02),
              priced(build("coach_checked", "s", "d", "built"), 0.02),
              build("coach_checked", "s", "e", "skipped_small_passed"),
              priced(build("coach_checked", "s", "f", "failed_validation"), 0.02)]
    runs += [priced(run("coach_checked", "s", "a_2", True), 0.03), priced(run("coach_checked", "s", "a_3", False), 0.03),
             priced(run("coach_checked", "s", "d_2", False), 0.20), priced(run("coach_checked", "s", "d_3", False), 0.20)]
    report = stage1.analyze(runs, teach, scenarios, ("s",), "t", n_resamples=50)

    kept = report["break_even"]["summary"]  # the first measure reads fixed tasks only and is not changed
    assert kept["function"] == {"n_student_scenarios": 3, "n_never_pays_back": 0, "median_uses_to_break_even": 1.0}
    assert kept["note"]["n_student_scenarios"] == 1 and kept["note"]["median_uses_to_break_even"] == pytest.approx(0.29)

    block = report["break_even_including_failures"]
    rows = {(row["form"], row["scenario"]): row for row in block["rows"]}
    assert ("function", "f") not in rows and ("note", "e") not in rows  # no rent to compare with; no build attempted
    assert rows[("function", "a")]["uses_to_break_even"] == 1.0          # 0.09 / (0.10 - 0.01)
    # b_2 is fixed and costs 0.01. b_3 is not: 0.01 for the failed run plus its own rent of 0.30, not the mean rent.
    assert rows[("function", "b")]["rent_usd_per_task"] == pytest.approx(0.20)
    assert rows[("function", "b")]["cost_usd_per_use"] == pytest.approx(0.16)   # (0.01 + 0.31) / 2
    assert rows[("function", "b")]["uses_to_break_even"] == 2.25         # 0.09 / (0.20 - 0.16)
    assert rows[("function", "c")]["build_status"] == "failed_validation"
    assert rows[("function", "c")]["uses_to_break_even"] is None and rows[("function", "c")]["run_usd_per_task"] is None
    assert rows[("function", "d")]["n_fixed"] == 0 and rows[("function", "d")]["uses_to_break_even"] is None
    assert rows[("function", "e")]["note_eligible"] is False and rows[("function", "e")]["uses_to_break_even"] == 1.0
    assert rows[("note", "a")]["uses_to_break_even"] == 1.0              # 0.02 / (0.10 - (0.03 + half of 0.10))
    assert rows[("note", "d")]["uses_to_break_even"] is None             # the note runs cost more than renting
    assert block["summary"]["function"] == {"n_student_scenarios": 5, "n_failed_builds": 1, "n_built_with_no_fix": 1,
                                            "n_never_pays_back": 2, "median_uses_to_break_even": 1.0}
    assert block["summary_note_eligible_scenarios_only"]["function"]["median_uses_to_break_even"] == 1.625
    assert block["summary"]["note"] == {"n_student_scenarios": 4, "n_failed_builds": 2, "n_built_with_no_fix": 1,
                                        "n_never_pays_back": 3, "median_uses_to_break_even": 1.0}


def test_check_compares_ids_with_the_scenario_file(tmp_path, monkeypatch):
    complete_files(tmp_path, monkeypatch)
    append_jsonl(tmp_path / "teach.jsonl", {**build("compile", "shared", "a", "built"), "cutoff_fix_version": 3})
    assert sweep.incomplete_reasons() == []
    rows = [run("small_alone", "s", "z_1", True) if row["condition"] == "small_alone" and row["task_id"] == "a_1" else row
            for row in read_jsonl(tmp_path / "runs.jsonl")]  # same count of alone runs, one of them on another task
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    reasons = sweep.incomplete_reasons()
    assert "s: alone runs missing for a_1" in reasons
    assert "s: alone runs on file for ids outside the scenario file: z_1" in reasons
    assert not any("of 3 alone runs" in reason for reason in reasons)  # the count alone would not have caught it


def control_files(folder, module, monkeypatch):
    """One scenario. The student fails a_1 and a_2 and passes a_3, so a_2 is its one control task."""
    monkeypatch.setattr(module, "RUN_DIR", folder)
    monkeypatch.setattr(module, "SCENARIO_FILE", manifest(folder, ["a"]))
    monkeypatch.setattr(module, "STUDENTS", ("s",))
    monkeypatch.setattr(module, "TEACHER", "t")
    monkeypatch.setattr(module, "N_SCENARIOS", 1)
    monkeypatch.setattr(module, "N_TASKS", 3)
    monkeypatch.setattr(module, "AUDITED_LOST_TRIES", set())
    rows = [run("cloud_alone", "t", f"a_{version}", True) for version in (1, 2, 3)]
    rows += [run("small_alone", "s", "a_1", False), run("small_alone", "s", "a_2", False), run("small_alone", "s", "a_3", True)]
    rows += [run("compile", "s", "a_2", True), run("compile", "s", "a_3", True)]
    for row in rows:
        append_jsonl(folder / "runs.jsonl", row)
    append_jsonl(folder / "teach.jsonl", {**build("compile", "shared", "a", "built"), "cutoff_fix_version": 3})
    append_jsonl(folder / "teach.jsonl", build("coach_checked", "s", "a", "failed_validation"))
    return rows


def test_control_check_needs_a_run_that_counts_for_every_control_task(tmp_path, monkeypatch):
    control_files(tmp_path, sweep, monkeypatch)
    assert sweep.incomplete_reasons() == [] and sweep.control_tasks("s") == ["a_2"]
    assert sweep.control_incomplete_reasons() == ["s: 1 of 1 control runs missing (a_2)"]
    append_jsonl(tmp_path / "runs.jsonl", {**run("generic_note", "s", "a_2", False), "stop_reason": "cost_cap"})
    assert sweep.control_incomplete_reasons() == ["s: 1 control runs ended in an infrastructure error or the cost cap (a_2)"]
    append_jsonl(tmp_path / "runs.jsonl", run("generic_note", "s", "a_2", False, repeat=2))
    assert sweep.control_incomplete_reasons() == []


def test_analyzer_refuses_a_result_while_the_control_is_missing(tmp_path, monkeypatch, capsys):
    rows = control_files(tmp_path, stage1.sweep, monkeypatch)
    out = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["analyze_stage1.py", "--run-dir", str(tmp_path),
                                     "--scenarios", str(tmp_path / "scenarios.json"), "--out", str(out)])
    assert stage1.main() == 2 and not out.exists()
    assert "STATUS INCOMPLETE" in capsys.readouterr().out
    broken = {**run("generic_note", "s", "a_2", False), "stop_reason": "model_error"}
    append_jsonl(tmp_path / "runs.jsonl", broken)
    assert stage1.main() == 2 and not out.exists()  # a control run that ended in an infrastructure error does not count
    control = run("generic_note", "s", "a_2", False, repeat=2)
    append_jsonl(tmp_path / "runs.jsonl", control)
    (tmp_path / "raw_large").mkdir()
    for row in rows + [broken, control]:  # every repeat has its raw file, and the recount opens every one
        name = f"{row['condition']}__{row['model_key']}__{row['task_id']}__r{row['repeat']}.json"
        (tmp_path / "raw_large" / name).write_text(json.dumps(
            {"evaluation": {"success": row["success"]}, "guidance": "g", "preload_code": "c"}), encoding="utf-8")
    assert stage1.main() == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "COMPLETE"
    assert report["primary_note_eligible"]["generic_note_control"]["n_units_without_a_control_run"] == 0
    again = tmp_path / "again.json"  # the same rows read again reproduce every value of the first report
    monkeypatch.setattr("sys.argv", ["analyze_stage1.py", "--run-dir", str(tmp_path), "--scenarios",
                                     str(tmp_path / "scenarios.json"), "--out", str(again), "--corrects", str(out)])
    assert stage1.main() == 0
    block = json.loads(again.read_text(encoding="utf-8"))["corrections_to_report"]
    assert block["n_values_changed"] == 0 and block["changed"] == [] and block["top_level_keys_added"] == []
    assert block["n_values_compared"] == stage1.n_values(report)


@pytest.mark.parametrize("condition, skills_dir, refused", [
    ("generic_note", "skills", True), ("small_alone", "skills", True), ("cloud_alone", "skills", True),
    ("compile", None, True), ("coach_checked", None, True),
    ("generic_note", None, False), ("small_alone", None, False), ("compile", "skills", False),
])
def test_skill_folder_and_condition_must_go_together(condition, skills_dir, refused):
    if refused:
        with pytest.raises(SystemExit):
            run_arm.check_skill_arguments(condition, skills_dir)
    else:
        run_arm.check_skill_arguments(condition, skills_dir)


def test_only_skill_conditions_read_the_skill_folder(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "coach_checked_note.txt").write_text("the note", encoding="utf-8")
    generic = run_arm.generic_guidance()
    assert generic and run_arm.guidance_for("generic_note", tmp_path, "a") == (generic, None)  # a folder cannot replace it
    assert run_arm.guidance_for("generic_note", None, "a") == (generic, None)
    assert run_arm.guidance_for("small_alone", tmp_path, "a") == (None, None)
    assert run_arm.guidance_for("coach_checked", tmp_path, "a") == ("the note", None)
    with pytest.raises(FileNotFoundError):
        run_arm.guidance_for("coach_checked", tmp_path, "b")


# The fixes from the second review round of Nov 24, 2026.


def test_equal_weight_resample_is_undefined_when_a_tier_member_has_no_task():
    one_without_tasks = [[4, 1, 4, 0], [0, 0, 0, 0]]
    assert stage1.tier_rate(one_without_tasks, [0, 1], 1, True) is None          # not the mean of whoever is left
    assert stage1.tier_rate(one_without_tasks, [0, 1], 1, False) == pytest.approx(1 / 4)   # pooling still has tasks
    assert stage1.tier_rate([[4, 1, 4, 0], [2, 2, 0, 0]], [0, 1], 1, True) == pytest.approx((1 / 4 + 1) / 2)
    assert stage1.tier_rate([], [], 1, True) is None

    def unit(student, scenario, tier, note_fixed):
        return {"student": student, "scenario": scenario, "task": f"{scenario}_2", "tier": tier, "note_eligible": True,
                "note_fixed": note_fixed, "function_fixed": True}

    # x and z have a failed task in both scenarios, y only in b: a resample without b has no rate for y.
    units = [unit("x", "a", "lower", False), unit("x", "b", "lower", True), unit("y", "b", "lower", False),
             unit("z", "a", "upper", True), unit("z", "b", "upper", True)]
    strength = {"x": {"tier": "lower"}, "y": {"tier": "lower"}, "z": {"tier": "upper"}}
    resamples = stage1.draws(2, 200)
    without_b = sum(1 for weights in resamples if weights[1] == 0)
    assert 0 < without_b < 200
    equal = stage1.estimate(units, ["a", "b"], ("x", "y", "z"), strength, resamples, equal_students=True)
    pooled = stage1.estimate(units, ["a", "b"], ("x", "y", "z"), strength, resamples)
    assert equal["D_interval_95"]["n_undefined_resamples"] == without_b      # dropped and counted, as the protocol says
    assert equal["H2_interval_95"]["n_undefined_resamples"] == without_b
    assert pooled["D_interval_95"]["n_undefined_resamples"] == 0
    assert equal["note_lower"] == pytest.approx((1 / 2 + 0) / 2) and equal["D"] == pytest.approx(1 - 1 / 4)


def test_differences_lists_what_an_earlier_report_had_and_this_one_does_not_reproduce():
    earlier = {"a": {"x": 1, "y": [1, 2]}, "b": 0.5, "gone": 1}
    now = {"a": {"x": 1, "y": [1, 3], "new": 9}, "b": 0.5, "added": {}}
    assert stage1.differences(earlier, now) == [{"key": "a.y[1]", "earlier": 2, "now": 3},
                                                {"key": "gone", "earlier": 1, "now": "(absent)"}]
    assert stage1.differences({"n": 1}, {"n": 1.0}) == [{"key": "n", "earlier": 1, "now": 1.0}]
    assert stage1.n_values(earlier) == 5


def test_a_skipped_build_must_agree_with_the_latest_version_1_runs(tmp_path, monkeypatch):
    complete_files(tmp_path, monkeypatch)
    rows = [row for row in read_jsonl(tmp_path / "runs.jsonl") if row["condition"] != "compile"]  # no function here
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    append_jsonl(tmp_path / "teach.jsonl", build("compile", "shared", "a", "skipped_cloud_failed"))
    stale = "shared function: marked skipped_cloud_failed but the teacher's latest version 1 run passed: a"
    assert stale in sweep.incomplete_reasons()  # the teacher passed a_1, so the function was never decided
    append_jsonl(tmp_path / "runs.jsonl", run("cloud_alone", "t", "a_1", False, repeat=2))
    assert sweep.incomplete_reasons() == []     # now the latest teacher run of a_1 is a failure and the skip stands
    append_jsonl(tmp_path / "runs.jsonl", run("small_alone", "s", "a_1", False, repeat=2))
    assert sweep.incomplete_reasons() == [
        "s note: marked skipped_small_passed but the student's latest version 1 run failed: a"]


def test_a_failed_function_build_without_a_cut_off_count_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep, "RUN_DIR", tmp_path)
    monkeypatch.setattr(sweep, "AUDITED_LOST_TRIES", set())
    for row in (build("compile", "shared", "a", "failed_validation"),                 # written before the count
                {**build("compile", "shared", "b", "cut_off"), "cut_off_requests": None},
                {**build("compile", "shared", "c", "failed_validation"), "cut_off_requests": 0},
                build("compile", "shared", "d", "built"),
                build("compile", "shared", "e", "skipped_cloud_failed"),
                build("coach_checked", "s", "f", "failed_validation")):          # a note, not a function
        append_jsonl(tmp_path / "teach.jsonl", row)
    assert sweep.voided_builds() == ["a", "b"]
    append_jsonl(tmp_path / "teach.jsonl", {**build("compile", "shared", "a", "failed_validation"), "cut_off_requests": 2})
    assert sweep.voided_builds() == ["b"]       # rebuilt with the count on record: a real failure, it stays failed
    monkeypatch.setattr(sweep, "AUDITED_LOST_TRIES", {"c"})
    assert sweep.voided_builds() == ["b", "c"]  # the hand audit still applies until a row from after the fix
    append_jsonl(tmp_path / "teach.jsonl", {**build("compile", "shared", "c", "failed_validation"),
                                            "cut_off_requests": 0, "cutoff_fix_version": 3})
    assert sweep.voided_builds() == ["b"]


def test_a_control_run_that_did_not_count_is_rerun_at_the_next_repeat(tmp_path, monkeypatch):
    control_files(tmp_path, sweep, monkeypatch)
    assert sweep.control_retries("s") == {}     # a task with no run is the first pass's work, not a retry
    append_jsonl(tmp_path / "runs.jsonl", {**run("generic_note", "s", "a_2", False), "stop_reason": "cost_cap"})
    assert sweep.control_retries("s") == {2: ["a_2"]}
    assert sweep.infra_tasks("generic_note", "s") == []   # the stage 1 runner's list is unchanged: model_error only
    append_jsonl(tmp_path / "runs.jsonl", {**run("generic_note", "s", "a_2", False, repeat=2), "stop_reason": "model_error"})
    assert sweep.control_retries("s") == {3: ["a_2"]} and sweep.infra_tasks("generic_note", "s") == []
    append_jsonl(tmp_path / "runs.jsonl", run("generic_note", "s", "a_2", False, repeat=3))
    assert sweep.control_retries("s") == {} and sweep.control_incomplete_reasons() == []


def test_runs_that_should_not_exist_are_flagged(tmp_path, monkeypatch):
    control_files(tmp_path, sweep, monkeypatch)
    assert sweep.incomplete_reasons() == []
    should_not = "runs on file that should not exist (no built skill for the scenario, or not one of its test tasks)"
    for row in (run("compile", "s", "z_2", True), run("compile", "s", "a_1", True), run("coach_checked", "s", "z_3", True)):
        append_jsonl(tmp_path / "runs.jsonl", row)
    reasons = sweep.incomplete_reasons()
    assert f"s: compile {should_not}: a_1,z_2" in reasons          # another scenario, and a version that is not a test
    assert f"s: coach_checked {should_not}: z_3" in reasons
    # The note of scenario a failed validation, so a note test run on a real test task has no built note behind it.
    append_jsonl(tmp_path / "runs.jsonl", run("coach_checked", "s", "a_2", True))
    assert f"s: coach_checked {should_not}: a_2,z_3" in sweep.incomplete_reasons()
    # The same for the shared function once its latest build is not "built".
    append_jsonl(tmp_path / "teach.jsonl", {**build("compile", "shared", "a", "failed_validation"), "cut_off_requests": 0})
    assert f"s: compile {should_not}: a_1,a_2,a_3,z_2" in sweep.incomplete_reasons()
    for row in (run("small_alone", "x", "a_1", True), run("coach", "s", "a_2", True)):
        append_jsonl(tmp_path / "runs.jsonl", row)
    assert ("runs on file of a model or arm that is not part of stage 1: coach:s,small_alone:x"
            in sweep.incomplete_reasons())


def test_control_runs_that_should_not_exist_are_flagged(tmp_path, monkeypatch):
    control_files(tmp_path, sweep, monkeypatch)
    append_jsonl(tmp_path / "runs.jsonl", run("generic_note", "s", "a_2", False))
    assert sweep.control_incomplete_reasons() == []
    should_not = "generic_note runs on file that should not exist (not a control task of that student)"
    append_jsonl(tmp_path / "runs.jsonl", run("generic_note", "s", "a_3", True))   # s passed a_3 alone: no control task
    assert sweep.control_incomplete_reasons() == [f"{should_not}: s:a_3"]
    for row in (run("generic_note", "s", "z_3", False), run("generic_note", "x", "a_2", False)):
        append_jsonl(tmp_path / "runs.jsonl", row)                                 # outside the file; not a student
    assert sweep.control_incomplete_reasons() == [f"{should_not}: s:a_3,s:z_3,x:a_2"]
    assert sweep.incomplete_reasons() == []   # the stage check does not read the control's runs


def test_the_stage_check_leaves_a_cut_short_control_run_to_the_control_check(tmp_path, monkeypatch):
    """The case from review: a control run that ended at a spend limit must not close the gate the control starts behind."""
    control_files(tmp_path, sweep, monkeypatch)
    append_jsonl(tmp_path / "runs.jsonl", {**run("generic_note", "s", "a_2", False), "stop_reason": "model_error"})
    append_jsonl(tmp_path / "runs.jsonl", {**run("generic_note", "s", "a_2", False, repeat=2), "stop_reason": "cost_cap"})
    assert sweep.incomplete_reasons() == []                       # stage 1's own runs and builds are all there
    assert sweep.control_retries("s") == {3: ["a_2"]}             # so the control starts and reruns it as repeat 3
    assert sweep.control_incomplete_reasons() == [
        "s: 1 control runs ended in an infrastructure error or the cost cap (a_2)"]


def raw_file(folder, row, **content):
    (folder / "raw_large").mkdir(exist_ok=True)
    name = f"{row['condition']}__{row['model_key']}__{row['task_id']}__r{row['repeat']}.json"
    (folder / "raw_large" / name).write_text(json.dumps(
        {"evaluation": {"success": row["success"]}, "guidance": "g", "preload_code": "c", **content}), encoding="utf-8")


def test_recount_opens_every_repeat_and_compares_the_resources(tmp_path):
    def part(tokens_in, tokens_out, seconds, usd):
        return {"input_tokens": tokens_in, "output_tokens": tokens_out, "seconds": seconds, "cost_usd": usd}

    first = {**run("small_alone", "s", "a_2", False), "requests": 3, "input_tokens": 60, "output_tokens": 6,
             "model_seconds": 3.0, "cost_usd": 0.03, "stop_reason": "model_error"}
    again = {**run("small_alone", "s", "a_2", True, repeat=2), "requests": 2, "input_tokens": 30, "output_tokens": 3,
             "model_seconds": 2.0, "cost_usd": 0.02}
    steps = [part(10, 1, 1.0, 0.01), part(20, 2, 1.0, 0.01)]
    raw_file(tmp_path, again, steps=steps, forecast=None)
    recount = stage1.recount_from_raw(tmp_path, [first, again])
    assert recount["problems"] == ["missing raw file: small_alone__s__a_2__r1.json"]   # the first try counts too
    # The first try has two stored steps, a forecast and one paid reply that never became a step: four requests.
    raw_file(tmp_path, first, steps=steps, forecast=part(20, 2, 0.5, 0.005), unfinished_replies=[part(10, 1, 0.5, 0.005)])
    problems = stage1.recount_from_raw(tmp_path, [first, again])["problems"]
    assert problems == ["requests differs from raw: small_alone__s__a_2__r1.json (row 3, raw 4)"]
    first["requests"] = 4
    recount = stage1.recount_from_raw(tmp_path, [first, again])
    assert recount["problems"] == [] and recount["n_checked"] == 1 and recount["n_raw_files_checked_every_repeat"] == 2
    again["cost_usd"] = 0.021
    assert stage1.recount_from_raw(tmp_path, [first, again])["problems"] == [
        "cost_usd differs from raw: small_alone__s__a_2__r2.json (row 0.021, raw 0.02)"]
    assert stage1.resources_in_raw({"evaluation": {}}) == {}       # an old file without steps: only the outcome is read


def ledger_row(note, time, usd):
    return {"run": "stage1", "provider": "p", "note": note, "time": f"2026-11-23T10:00:{time:02d}-05:00", "usd": usd}


def timed(row, started, finished, usd, requests):
    stamp = "2026-11-23T10:00:{:02d}-05:00"
    return {**row, "started": stamp.format(started), "finished": stamp.format(finished), "cost_usd": usd,
            "requests": requests}


def test_ledger_and_rows_are_compared_run_by_run():
    runs = [timed(run("cloud_alone", "t", "a_1", True), 0, 5, 0.010, 4),
            timed(run("cloud_alone", "t", "a_2", False), 5, 9, 0.007, 3),            # one paid reply missing from its row
            timed(run("cloud_alone", "t", "a_2", True, repeat=2), 20, 25, 0.009, 4),
            timed(run("generic_note", "s", "a_2", False), 0, 10, 0.020, 2),
            timed(run("generic_note", "s", "a_3", False), 10, 20, 0.030, 3),         # starts on the second a_2 ends
            timed(run("generic_note", "s", "b_2", False), 30, 40, 0.020, 2)]         # its row misses one request
    ledger = [ledger_row("cloud_alone t a_1", 5, 0.010), ledger_row("cloud_alone t a_2", 9, 0.008),
              ledger_row("cloud_alone t a_2", 25, 0.009),
              ledger_row("generic_note s", 4, 0.010), ledger_row("generic_note s", 10, 0.010),   # 10: a_2's or a_3's?
              ledger_row("generic_note s", 12, 0.010), ledger_row("generic_note s", 15, 0.010),
              ledger_row("generic_note s", 19, 0.010),
              ledger_row("generic_note s", 33, 0.010), ledger_row("generic_note s", 36, 0.010),
              ledger_row("generic_note s", 39, 0.005),
              ledger_row("build_coach_checked s a", 50, 0.5), ledger_row("written by hand: an estimate", 51, 0.2),
              {**ledger_row("cloud_alone t a_1", 1, 9.0), "run": "another_run"}]
    report = ledger_check.compare(runs, ledger, "stage1")
    assert report["n_runs_compared"] == 6 and report["n_comparisons"] == 5
    assert report["n_runs_compared_together_with_a_neighbour"] == 2       # a_2 and a_3 share second 10: one sum
    differ = {(item["condition"], item["runs"][0]["task_id"], item["runs"][0]["repeat"]): item["ledger_minus_row_usd"]
              for item in report["runs_that_differ"]}
    assert differ == {("cloud_alone", "a_2", 1): pytest.approx(0.001), ("generic_note", "b_2", 1): pytest.approx(0.005)}
    assert report["n_runs_that_differ"] == 2
    assert report["ledger_minus_row_usd_over_runs_that_differ"] == pytest.approx(0.006)
    assert report["ledger_rows_of_runs_not_matched"] == {"n": 0, "usd": 0}
    assert report["ledger_rows_that_are_not_run_costs"]["n"] == 2          # the builder's row and the hand-written one
    builds = ledger_check.compare_note_builds(
        [priced(build("coach_checked", "s", "a", "failed_validation"), 0.3), priced(build("coach_checked", "s", "a", "built"), 0.2),
         priced(build("coach_checked", "s", "b", "built"), 0.1), build("compile", "shared", "a", "built")],
        ledger + [ledger_row("build_coach_checked s b", 52, 0.13)], "stage1")
    assert builds["n_builds_compared"] == 2 and builds["n_builds_that_differ"] == 1
    assert builds["builds_that_differ"][0]["scenario_id"] == "b"
    assert builds["builds_that_differ"][0]["ledger_minus_row_usd"] == pytest.approx(0.03)


def test_a_run_whose_grading_breaks_is_recorded_as_an_infrastructure_error():
    class Bridge:
        def __init__(self, broken):
            self.broken = broken

        def evaluate(self):
            if self.broken:
                raise RuntimeError("worker gone")
            return {"success": True, "passes": ["a"], "failures": []}

    trace = run_arm.RunTrace(stop_reason="completed", task_completed=True)
    assert run_arm.grade(Bridge(False), trace)["success"] is True and trace.stop_reason == "completed"
    verdict = run_arm.grade(Bridge(True), trace)
    assert verdict == {"success": False, "passes": [], "failures": []}
    assert trace.stop_reason == "model_error" and "grading failed: RuntimeError: worker gone" in trace.error
