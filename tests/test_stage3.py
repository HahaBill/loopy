"""Stage 3 (OpenAI teacher, same students): costs, the buy label, completeness. Synthetic rows; no model, no AppWorld."""

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


g3 = load("stage3_helper_under_test", "experiments/stage3/stage3.py")
T = g3.TEACHER
SCEN = ["a", "b"]


def run(condition, model, task, success, repeat=1, stop="completed", cost=0.01):
    return {"condition": condition, "model_key": model, "task_id": task, "success": success, "repeat": repeat,
            "stop_reason": stop, "n_steps": 3, "cost_usd": cost, "git_commit": "c", "started": "t", "finished": "t"}


def row(form, scenario, status, build, per_use, rent, student="s", eligible=True):
    return {"student": student, "form": form, "scenario": scenario, "note_eligible": eligible,
            "build_status": status, "build_usd": build, "cost_usd_per_use": per_use, "rent_usd_per_task": rent,
            "uses_to_break_even": None}


def test_costs_rent_every_use_of_a_failed_build():
    assert g3.cost_of(row("note", "a", "built", 0.2, 0.05, 0.3), 10) == 0.2 + 10 * 0.05
    assert g3.cost_of(row("note", "a", "failed_validation", 0.2, None, 0.3), 10) == 0.2 + 10 * 0.3


def test_pairs_and_the_share_where_the_note_is_cheaper():
    rows = [row("note", "a", "built", 0.1, 0.10, 0.3), row("function", "a", "built", 0.5, 0.02, 0.3),
            row("note", "b", "built", 0.1, 0.02, 0.3), row("function", "b", "built", 0.5, 0.02, 0.3),
            row("note", "c", "built", 0.1, 0.02, 0.3, eligible=False), row("function", "c", "built", 0.5, 0.02, 0.3)]
    pairs = g3.pairs_of(rows, ("s",))
    assert [pair["scenario"] for pair in pairs] == ["a", "b"]  # c is not note-eligible
    # a: note 0.1 + 0.1k, function 0.5 + 0.02k -> the note is cheaper below 5 uses; b: the note is always cheaper
    assert g3.note_cheaper_share(pairs, 1) == 1.0 and g3.note_cheaper_share(pairs, 10) == 0.5
    assert g3.note_cheaper_share([], 10) is None


def test_buy_label():
    assert g3.buy_label(0.8, {"low": 0.6, "high": 0.9}) == "NOTE IS THE BETTER BUY"
    assert g3.buy_label(0.1, {"low": 0.0, "high": 0.3}) == "FUNCTION IS THE BETTER BUY"
    assert g3.buy_label(0.4, {"low": 0.1, "high": 0.7}) == "UNDECIDED"
    assert g3.buy_label(None, {"low": None, "high": None}) == "UNDECIDED"


def test_the_share_interval_counts_empty_draws():
    pairs = [{"student": "s", "scenario": "a", "note": row("note", "a", "built", 0.1, 0.02, 0.3),
              "function": row("function", "a", "built", 0.5, 0.02, 0.3)}]
    interval = g3.share_interval(pairs, SCEN, resamples=400, seed=1)
    assert 50 < interval["n_undefined_resamples"] < 150  # a draw of [b, b] holds no pair (about a quarter)
    assert interval["low"] == interval["high"] == 1.0


def test_billed_costs_take_the_cache_off_the_teacher_only():
    runs = [{**run("cloud_alone", T, "a_1", True, cost=0.3), "cached_input_tokens": 100_000},
            {**run("coach_checked", "s", "a_2", True, cost=0.05), "cached_input_tokens": 100_000}]
    teach = [{"kind": "compile", "cost_usd": 0.4, "cached_input_tokens": 50_000},
             {"kind": "coach_checked", "cost_usd": 0.3, "teacher_cached_input_tokens": 50_000}]
    runs_b, teach_b = g3.billed(runs, teach, price_in=2.0, price_cached=0.1)
    assert abs(runs_b[0]["cost_usd"] - (0.3 - 100_000 * 1.9 / 1e6)) < 1e-12
    assert runs_b[1]["cost_usd"] == 0.05  # a student run is billed by another provider and is not changed
    assert abs(teach_b[0]["cost_usd"] - (0.4 - 0.095)) < 1e-12 and abs(teach_b[1]["cost_usd"] - (0.3 - 0.095)) < 1e-12
    assert g3.billed(runs, teach, 2.0, None) == (runs, teach)


def test_builds_are_read_for_the_teacher_in_use(monkeypatch):
    teach = [{"kind": "compile", "small_model_key": "shared", "teacher_model_key": T, "scenario_id": "a",
              "status": "built"},
             {"kind": "compile", "small_model_key": "shared", "teacher_model_key": g3.FLASH, "scenario_id": "b",
              "status": "built"}]
    assert g3.built(teach, "compile", "shared") == {"a"}
    monkeypatch.setattr(g3, "TEACHER", g3.FLASH)
    assert g3.built(teach, "compile", "shared") == {"b"}


def test_completeness_reads_reused_solo_runs_and_flags_what_is_missing(monkeypatch):
    monkeypatch.setattr(g3, "STUDENTS", ("s",))
    solo = [run("small_alone", "s", task, ok) for task, ok in
            {"a_1": False, "a_2": False, "a_3": True, "b_1": True, "b_2": False, "b_3": False}.items()]
    own = [run("cloud_alone", T, task, True) for task in g3.all_tasks(SCEN)]
    teach = [{"kind": "compile", "small_model_key": "shared", "teacher_model_key": T, "scenario_id": s,
              "learn_task_id": f"{s}_1", "status": "built", "cost_usd": 0.1} for s in SCEN]
    teach += [{"kind": "coach_checked", "small_model_key": "s", "teacher_model_key": T, "scenario_id": "a",
               "learn_task_id": "a_1", "status": "built", "cost_usd": 0.1},
              {"kind": "coach_checked", "small_model_key": "s", "teacher_model_key": T, "scenario_id": "b",
               "learn_task_id": "b_1", "status": "skipped_small_passed", "cost_usd": 0.0}]
    assert g3.control_tasks(own + solo, "s", SCEN) == ["a_2"]
    own += [run("coach_checked", "s", t, True) for t in ("a_2", "a_3")]
    own += [run("compile", "s", t, True) for t in ("a_2", "a_3", "b_2", "b_3")]
    assert any("generic_note runs missing" in r for r in g3.incomplete_reasons(own, solo, teach, SCEN))
    assert g3.retry_lines("generic_note", "s", own + solo, teach, SCEN) == ["1 a_2"]
    own.append(run("generic_note", "s", "a_2", False))
    assert g3.incomplete_reasons(own, solo, teach, SCEN) == []
    assert any("not part of stage 3" in r for r in g3.incomplete_reasons(
        own + [run("small_alone", "s", "a_1", True)], solo, teach, SCEN))  # solo runs are reused, never rerun here
    assert any("solo" not in r and "small_alone runs missing" in r for r in g3.incomplete_reasons(
        own, solo[1:], teach, SCEN))
    assert any("cloud_alone runs missing" in r for r in g3.incomplete_reasons(own[1:], solo, teach, SCEN))


def test_the_library_sends_no_temperature_to_the_reasoning_teacher_and_zero_to_students():
    from loopy.agent.llm import ModelSpec
    import json as _json
    config = _json.loads((ROOT / "experiments/stage3/config.json").read_text(encoding="utf-8"))
    teacher = ModelSpec.from_dict(T, config["models"][T])
    assert teacher.temperature is None and "temperature" not in g3.sent_settings(teacher)
    for student in g3.STUDENTS:
        sent = g3.sent_settings(ModelSpec.from_dict(student, config["models"][student]))
        assert sent["temperature"] == 0.0 and sent["seed"] == 123
    zero = ModelSpec.from_dict(T, {**config["models"][T], "temperature": 0.0})
    assert "temperature" not in g3.sent_settings(zero)  # what the preflight refuses: configured, but never sent


def test_the_projection_stops_when_the_stage_would_pass_the_stop(tmp_path, monkeypatch):
    import json as _json
    monkeypatch.setattr(g3, "RUN_DIR", tmp_path)
    monkeypatch.setattr(g3, "LEDGER", tmp_path / "ledger.jsonl")
    config = {"ledger_caps_usd": {"openai.com": 90.0}, "ledger_reserve_usd": {"openai.com": 4.0}}
    assert g3.calibration_tasks(SCEN) == ["a_1", "a_2", "a_3"]  # fixed in advance, whatever ran first
    (tmp_path / "raw_large").mkdir()

    def trajectories(cut):
        steps = [{"finish_reason": "length"}] * cut + [{"finish_reason": "stop"}] * (10 - cut)
        for v in (1, 2, 3):
            (tmp_path / "raw_large" / f"cloud_alone__{T}__a_{v}__r1.json").write_text(_json.dumps({"steps": steps}))

    own = [run("cloud_alone", T, f"a_{v}", True, cost=0.3) for v in (1, 2)] + [run("cloud_alone", T, "b_1", True)]
    assert "not all on file" in g3.projection(own, config, SCEN)[0][0]  # b_1 is not a calibration task
    own.append(run("cloud_alone", T, "a_3", False, stop="model_error", cost=0.0))
    assert "not all on file" in g3.projection(own, config, SCEN)[0][0]  # an infrastructure error is not a result
    own[-1] = run("cloud_alone", T, "a_3", True, cost=0.3)
    assert "no trajectory file" in g3.projection(own, config, SCEN)[0][0]
    trajectories(cut=0)
    problems, facts = g3.projection(own, config, SCEN)
    assert problems == [] and facts["projected_more_openai_spend_usd"] == round(0.3 * g3.RUN_EQUIVALENTS - 0.9, 2)
    dear = [run("cloud_alone", T, f"a_{v}", True, cost=0.6) for v in (1, 2, 3)]
    assert "would need about" in g3.projection(dear, config, SCEN)[0][0]
    trajectories(cut=3)
    assert any("cut by the output limit" in p for p in g3.projection(own, config, SCEN)[0])
    assert g3.calibration_retry_lines(own[:2], SCEN) == ["1 a_3"]


def test_a_result_file_is_written_whole_or_not_at_all(tmp_path):
    import pytest as _pytest
    with _pytest.raises(TypeError):
        g3.write_once(tmp_path / "result.json", {"not serializable": object()})
    assert not (tmp_path / "result.json").exists()
    g3.write_once(tmp_path / "result.json", {"ok": 1})
    with _pytest.raises(FileExistsError):
        g3.write_once(tmp_path / "result.json", {"ok": 2})


def test_an_existing_result_counts_only_when_it_is_whole(tmp_path):
    (tmp_path / "partial.json").write_text('{"status": "COMPL', encoding="utf-8")
    assert not g3.result_is_whole(tmp_path / "partial.json")
    g3.write_once(tmp_path / "empty.json", {"status": "COMPLETE", "list_price": {}, "billed_with_cached_input": {}})
    assert not g3.result_is_whole(tmp_path / "empty.json")
    whole = {"status": "COMPLETE", "billed_with_cached_input": {"cost_question": {"all_four": {}}},
             "list_price": {"cost_question": {"all_four": {"label": "UNDECIDED", "interval_95": {}}},
                            "accuracy": {"label": "CATCHES UP"}}}
    g3.write_once(tmp_path / "whole.json", whole)
    assert g3.result_is_whole(tmp_path / "whole.json")
    assert not list(tmp_path.glob(".*.tmp"))  # the temporary file is gone
