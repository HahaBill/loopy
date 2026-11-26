"""Stage 2, part A: the screen and its keep rule. Synthetic rows only; no model, no AppWorld."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


part_a = load("stage2_part_a", "experiments/stage2/part_a.py")
MODELS = list(part_a.GUARDS)
TASKS = [f"s{index:02d}_1" for index in range(12)]


def run(model, task, success, repeat=1, stop="completed", cost=0.02, difficulty=1):
    return {"condition": "small_alone", "model_key": model, "task_id": task, "success": success, "repeat": repeat,
            "stop_reason": stop, "n_steps": 5, "cost_usd": cost, "difficulty": difficulty}


def full(model, passes, cost=0.02):
    return [run(model, task, index < passes, cost=cost) for index, task in enumerate(TASKS)]


def result(passes, cost=0.02, cut=False):
    return {"passes": passes, "n": 12, "cost_per_run": cost, "cut_short": cut}


def test_screen_tasks_follow_the_fixed_rule():
    difficulty = {f"a{i}": 1 for i in range(9)} | {f"b{i}": 2 for i in range(6)} | {f"c{i}": 3 for i in range(8)}
    tasks = part_a.screen_tasks(set(difficulty), difficulty)
    assert tasks == [f"a{i}_1" for i in range(5)] + [f"b{i}_1" for i in range(3)] + [f"c{i}_1" for i in range(4)]


def test_the_config_has_every_candidate_as_a_student_under_the_screen_stop():
    config = json.loads((ROOT / "experiments/stage2/config_part_a.json").read_text(encoding="utf-8"))
    base = json.loads((ROOT / "experiments/stage2/config.json").read_text(encoding="utf-8"))
    assert config["ledger_caps_usd"] == {"nebius.com": 51.63}
    assert sum(part_a.GUARDS.values()) <= 4.0 + 1e-9
    for model in MODELS:
        assert config["models"][model]["role"] == "small"
    for key in ("max_steps", "output_char_limit", "appworld_timeout_seconds", "split", "scenario_file"):
        assert config[key] == base[key]
    for key, entry in base["models"].items():
        assert config["models"][key] == entry


def test_band_ranking_and_budget():
    decision = part_a.decide({"a": result(4), "b": result(6), "c": result(7), "d": result(10)}, screen_spend=2.0)
    assert decision["status"]["a"] == "below the band" and decision["status"]["d"] == "above the band"
    assert decision["ranked"] == ["c", "b"]  # 7 of 12 is nearer 55% than 6 of 12
    assert decision["kept"] == ["c", "b"]  # 2 x (116 x 0.02 + 0.60) = 5.84 fits in the 10 left

    costly = part_a.decide({"b": result(6, cost=0.05), "c": result(7, cost=0.05)}, screen_spend=3.0)
    assert costly["kept"] == ["c"]  # 6.40 each: only one fits in the 9 left
    assert costly["status"]["b"].startswith("in the band, not kept")

    assert part_a.decide({"a": result(6, cut=True), "b": result(2)}, screen_spend=1.0)["kept"] == []


def test_a_cut_candidate_is_finished_and_an_error_is_redone():
    rows = full(MODELS[0], 6) + full(MODELS[1], 3) + full(MODELS[2], 9)
    rows += [run(MODELS[3], TASKS[0], False), run(MODELS[3], TASKS[1], False, stop="cost_cap")]
    assert part_a.incomplete_reasons(TASKS, rows) == []
    assert part_a.retry_lines(TASKS, rows, MODELS[3]) == []
    report = part_a.screen_report(TASKS, rows)
    assert report["decision"]["status"][MODELS[3]].startswith("out")
    assert report["decision"]["kept"] == [MODELS[0], MODELS[2]]  # 6 of 12 ranks before 9 of 12; both fit

    rows = full(MODELS[0], 6)[:-1] + [run(MODELS[0], TASKS[-1], False, stop="model_error")]
    assert part_a.retry_lines(TASKS, rows, MODELS[0]) == [f"2 {TASKS[-1]}"]
    assert any("infrastructure error" in reason for reason in part_a.incomplete_reasons(TASKS, rows))
    rows.append(run(MODELS[0], TASKS[-1], True, repeat=2))
    assert part_a.retry_lines(TASKS, rows, MODELS[0]) == []
    redone = part_a.screen_report(TASKS, rows)["candidates"][MODELS[0]]
    assert (redone["passes"], redone["runs_counted"], redone["redone_runs"]) == (7, 12, 1)  # the redo passed and counts
