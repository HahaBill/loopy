"""The pilot's reading rules, checked on hand-made records."""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "pilot_analyze", Path(__file__).resolve().parents[1] / "experiments" / "pilot" / "analyze.py")
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


def run(task_id, condition, model_key, success, cost=0.01, forecast=None, cloud_calls=0, failure_type=None):
    scenario, version = task_id.rsplit("_", 1)
    return {"task_id": task_id, "scenario_id": scenario, "version": int(version), "condition": condition,
            "model_key": model_key, "success": success, "cost_usd": cost, "forecast_p_fail": forecast,
            "cloud_calls": cloud_calls, "failure_type": None if success else (failure_type or "bug"),
            "wall_seconds": 10.0, "n_steps": 5, "input_tokens": 1000}


def teach_row(scenario, kind, cost, status="built", calls=1):
    return {"scenario_id": scenario, "kind": kind, "teacher_model_key": "big", "small_model_key": "small",
            "cost_usd": cost, "cloud_calls": calls, "status": status, "validated": status == "built"}


def test_auroc_counts_pairs_and_ties():
    assert analyze.auroc([0.9, 0.8], [0.1, 0.2]) == 1.0
    assert analyze.auroc([0.1], [0.9]) == 0.0
    assert analyze.auroc([0.5], [0.5]) == 0.5
    assert analyze.auroc([], [0.5]) is None
    assert analyze.auroc([0.9, 0.1], [0.5]) == 0.5


def test_signals_on_a_small_made_up_pilot():
    records = [
        # scenario a: small fails everything; coach fixes v2 cheaply; rent solves both at a higher price
        run("a_1", "small_alone", "small", False, forecast=0.8), run("a_2", "small_alone", "small", False, forecast=0.7),
        run("a_3", "small_alone", "small", False, forecast=0.9),
        run("a_2", "cloud_alone", "big", True, cost=0.50, cloud_calls=10),
        run("a_3", "cloud_alone", "big", True, cost=0.50, cloud_calls=10),
        run("a_2", "coach", "small", True, cost=0.02), run("a_3", "coach", "small", False, cost=0.02),
        run("a_2", "compile", "small", False, cost=0.01), run("a_3", "compile", "small", False, cost=0.01),
        # scenario b: small passes v1 and v2, fails v3; only rent can help there
        run("b_1", "small_alone", "small", True, forecast=0.2), run("b_2", "small_alone", "small", True, forecast=0.1),
        run("b_3", "small_alone", "small", False, forecast=0.3),
        run("b_3", "cloud_alone", "big", True, cost=0.40, cloud_calls=8),
    ]
    teach = [teach_row("a", "coach", 0.05), teach_row("a", "compile", 0.10, status="failed_validation", calls=3)]
    reading = analyze.read_signals(records, teach, "small", "big")
    signals = reading["signals"]

    assert signals["1_small_model_fails_often"] == {"small_alone_failed": 4, "of": 6, "holds": True}
    second = signals["2_coach_or_compile_fixes_new_versions"]
    assert second["test_tasks_small_failed_alone"] == ["a_2", "a_3", "b_3"]
    assert second["fixed_by_coach"] == ["a_2"] and second["fixed_by_compile"] == [] and second["holds"] is False

    costs = reading["option_costs"]
    coach = costs["a"]["options"]["coach"]
    assert coach["n_solved"] == 1 and coach["cost_usd_per_solved_task"] == 0.09  # 0.05 build + 0.04 runs
    assert costs["a"]["options"]["rent"]["cost_usd_per_solved_task"] == 0.5
    assert costs["a"]["options"]["compile"]["cost_usd_per_solved_task"] is None
    assert costs["a"]["cheapest_option"] == "coach" and costs["b"]["cheapest_option"] == "rent"
    assert signals["3_no_option_always_wins"]["holds"] is True

    fourth = signals["4_forecast_tracks_outcomes"]
    assert fourth["auroc"] == 1.0 and fourth["holds"] is True
    assert reading["n_holding"] == 3


def test_signals_that_cannot_be_read_are_none_not_false():
    records = [run("a_1", "small_alone", "small", True, forecast=0.1),
               run("a_2", "small_alone", "small", True, forecast=0.1)]
    signals = analyze.read_signals(records, [], "small", "big")["signals"]
    assert signals["1_small_model_fails_often"]["holds"] is False
    assert signals["2_coach_or_compile_fixes_new_versions"]["holds"] is None
    assert signals["3_no_option_always_wins"]["holds"] is None
    assert signals["4_forecast_tracks_outcomes"]["holds"] is None


def test_skill_effects_separate_fixed_from_hurt():
    records = [run("a_2", "small_alone", "small", False), run("a_3", "small_alone", "small", True),
               run("a_2", "coach", "small", True), run("a_3", "coach", "small", False)]
    effects = analyze.skill_effects(records, "small")["coach"]
    assert effects["fixed (failed alone, passed with it)"] == ["a_2"]
    assert effects["hurt (passed alone, failed with it)"] == ["a_3"]
