"""The fixes made before the stage 1 students ran. No model needed."""

import importlib.util
import json
import multiprocessing as mp
from pathlib import Path

import pytest

from loopy.agent.llm import ModelSpec, Reply
from loopy.agent.react import Budget, CostCapReached
from loopy.eval.runlog import append_jsonl, read_jsonl
from loopy.skills.teach import (
    CHECK_TRIES,
    cap_stop_status,
    complete_uncut,
    run_check,
    skip_still_holds,
    stale_skips,
    stop_status,
)

SPEC = ModelSpec(key="t", role="cloud", name="t", usd_per_mtok_in=1.0, usd_per_mtok_out=1.0, max_tokens=16000)


def scripted(limits_seen, replies):
    class Chat:
        def __init__(self, spec):
            self.spec = spec

        def complete(self, messages):
            limits_seen.append(self.spec.max_tokens)
            return replies.pop(0)

    return Chat


def test_cut_off_reply_is_retried_with_a_larger_limit_and_priced():
    seen = []
    replies = [Reply("", 100, 16000, 1.0, finish_reason="length"), Reply("answer", 100, 20000, 1.0, finish_reason="stop")]
    reply, usage = complete_uncut(SPEC, [{"role": "user", "content": "x"}], Budget(), make_chat=scripted(seen, replies))
    assert reply.text == "answer" and seen == [16000, 32000]
    assert usage["requests"] == 2 and usage["cut_off_requests"] == 1 and usage["output_tokens"] == 36000


def test_stops_after_three_requests_at_the_ceiling_and_a_short_empty_reply_is_not_retried():
    seen = []
    replies = [Reply("", 1, 1, 0.1, finish_reason="length") for _ in range(5)]
    reply, usage = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen, replies))
    assert seen == [16000, 32000, 64000, 64000, 64000] and not reply.text
    assert usage["cut_off_requests"] == 5 and usage["still_cut_off"] is True and stop_status(usage) == "cut_off"
    seen2 = []
    _, usage2 = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen2, [Reply("", 1, 1, 0.1, finish_reason="stop")]))
    assert seen2 == [16000] and usage2["cut_off_requests"] == 0 and usage2["still_cut_off"] is False


def test_reply_stopped_partway_through_its_text_is_a_cut_off():
    seen = []
    replies = [Reply("def workflow(", 1, 16000, 0.1, finish_reason="length"), Reply("whole", 1, 9, 0.1, finish_reason="stop")]
    reply, usage = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen, replies))
    assert reply.text == "whole" and seen == [16000, 32000]
    assert usage["cut_off_requests"] == 1 and usage["still_cut_off"] is False


def test_second_ceiling_request_can_succeed():
    seen = []
    replies = [Reply("", 1, 1, 0.1, finish_reason="length") for _ in range(3)] + [Reply("ok", 1, 1, 0.1, finish_reason="stop")]
    reply, usage = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen, replies))
    assert reply.text == "ok" and seen == [16000, 32000, 64000, 64000] and usage["still_cut_off"] is False


def test_a_cost_cap_stop_returns_the_paid_usage():
    budget = Budget(max_usd=0.01)
    replies = [Reply("", 0, 16000, 0.1, finish_reason="length")]  # $0.016 at $1 per Mtok, over the cap
    _, usage = complete_uncut(SPEC, [], budget, make_chat=scripted([], replies))
    assert budget.spent_usd == pytest.approx(0.016) and usage["cost_usd"] == pytest.approx(0.016)
    assert usage["stopped_by_cap"] is True and stop_status(usage) == "cost_cap"
    with pytest.raises(CostCapReached):  # nothing was sent, so nothing to record
        complete_uncut(SPEC, [], budget, make_chat=scripted([], []))


def test_a_build_the_cap_stops_before_its_first_request_leaves_no_record():
    assert cap_stop_status(0) is None  # no row is written, so a restart with more budget builds it
    assert cap_stop_status(1) == "cost_cap" and cap_stop_status(4) == "cost_cap"  # paid requests are kept on record


def scripted_check(stops):
    started = []

    def start():
        started.append(stops[len(started)])
        return started[-1], {"stop_reason": started[-1], "n": len(started)}

    return start, started


def test_a_validation_the_provider_or_the_bridge_broke_is_started_again_not_counted():
    start, started = scripted_check(["model_error", "model_error", "completed"])
    ran, kept = run_check(start)
    assert ran is True and started == ["model_error", "model_error", "completed"]
    assert [item["n"] for item in kept] == [1, 2, 3]            # every start is kept, so what each cost is not lost
    start, started = scripted_check(["max_steps"])
    assert run_check(start)[0] is True and started == ["max_steps"]   # the student's own failure is a verdict
    start, started = scripted_check(["model_error"] * 5)
    ran, kept = run_check(start)
    assert ran is False and len(started) == CHECK_TRIES == 3     # bounded; the caller leaves the build pending
    start, started = scripted_check(["cost_cap", "completed"])
    assert run_check(start)[0] is False and started == ["cost_cap"]   # a spend stop is not tried again


def test_a_recorded_skip_counts_only_while_the_latest_runs_support_it():
    assert skip_still_holds("skipped_cloud_failed", None, False) and skip_still_holds("skipped_cloud_failed", None, None)
    assert not skip_still_holds("skipped_cloud_failed", False, True)     # the teacher's rerun passed
    assert skip_still_holds("skipped_small_passed", True, True) and not skip_still_holds("skipped_small_passed", False, True)
    assert skip_still_holds("built", False, True) and skip_still_holds("failed_validation", True, False)

    def row(scenario, kind, student, status):
        return {"scenario_id": scenario, "kind": kind, "teacher_model_key": "t", "small_model_key": student,
                "status": status}

    latest_run = {("cloud_alone", "t", "a"): True, ("cloud_alone", "t", "b"): False, ("small_alone", "s", "c"): False,
                  ("small_alone", "s", "d"): True, ("cloud_alone", "t", "e"): True}
    rows = [row("a", "compile", "shared", "skipped_cloud_failed"),      # the teacher's latest run passed: stale
            row("b", "compile", "shared", "skipped_cloud_failed"),      # still a failure: stands
            row("c", "coach_checked", "s", "skipped_small_passed"),     # the student's latest run failed: stale
            row("d", "coach_checked", "s", "skipped_small_passed"),     # still a pass: stands
            row("e", "compile", "shared", "skipped_cloud_failed"),
            row("e", "compile", "shared", "built")]                     # a later row decided it: not a skip any more
    assert stale_skips(rows, lambda condition, model, scenario: latest_run.get((condition, model, scenario))) == {
        ("a", "compile", "t", "shared"), ("c", "coach_checked", "t", "s")}


def test_a_limit_above_the_ceiling_is_clamped():
    seen = []
    big = ModelSpec(key="t", role="cloud", name="t", usd_per_mtok_in=1.0, usd_per_mtok_out=1.0, max_tokens=80000)
    replies = [Reply("", 1, 1, 0.1, finish_reason="length") for _ in range(3)]
    _, usage = complete_uncut(big, [], Budget(), make_chat=scripted(seen, replies))
    assert seen == [64000, 64000, 64000] and usage["still_cut_off"] is True


def test_stage1_check_reports_a_cost_cap_stop_and_missing_runs(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "experiments" / "stage1" / "sweep.py"
    spec = importlib.util.spec_from_file_location("stage1_sweep", path)
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    monkeypatch.setattr(sweep, "RUN_DIR", tmp_path)
    monkeypatch.setattr(sweep, "STUDENTS", ("s",))
    append_jsonl(tmp_path / "runs.jsonl", {"condition": "small_alone", "model_key": "s", "task_id": "a_1", "repeat": 1,
                                           "stop_reason": "completed"})
    append_jsonl(tmp_path / "teach.jsonl", {"kind": "coach_checked", "small_model_key": "s", "scenario_id": "a",
                                            "status": "cost_cap"})
    reasons = sweep.incomplete_reasons()
    assert "1 builds stopped by the cost cap" in reasons
    assert "s: 1 of 90 alone runs" in reasons and "s: 1 of 30 note decisions" in reasons


def _writer(args):
    path, who = args
    for index in range(200):
        append_jsonl(path, {"who": who, "index": index, "padding": "x" * 900})


def test_parallel_appends_keep_every_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    with mp.get_context("spawn").Pool(4) as pool:
        pool.map(_writer, [(str(path), who) for who in range(4)])
    rows = read_jsonl(path)
    assert len(rows) == 800 and len({(row["who"], row["index"]) for row in rows}) == 800
