"""Stage 2, part A, gate 2 (experiments/stage2/PROTOCOL_PART_A.md): the kept students through the stage 1 arms.

    part_a_gate2.py students                       the students the screen kept, read from its decision file
    part_a_gate2.py tasks --arm alone|test         alone: versions 1, 2 and 3 of the 23 scenarios; test: versions 2, 3
    part_a_gate2.py ready --model M                why the student's alone arm is not finished; prints nothing when it is
    part_a_gate2.py control --model M              the generic-note tasks (the student's units); refuses until ready
    part_a_gate2.py retry --condition C --model M  lines "<repeat> <tasks>": runs missing, or whose latest run ended in an
                                                   infrastructure error or a spend stop (at most two redos)
    part_a_gate2.py check                          why gate 2 is not finished; prints nothing when it is
    part_a_gate2.py analyze --out FILE             writes the result without printing it; refuses while `check` prints

Rows are read, never written. No task text is read or written here. Units, and break-even with failures priced, are
counted by the stage 1 analysis code (`experiments/stage1/analyze_stage1.py`), so both stages use one rule.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl
from loopy.skills.teach import skip_still_holds

HERE = Path(__file__).resolve().parent
STAGE1 = REPO_ROOT / "results" / "pilot" / "stage1"
RUN_DIR = REPO_ROOT / "results" / "pilot" / "stage2a"
SCREEN_FILE = RUN_DIR / "screen_part_a_2026-11-25.json"
SCENARIO_FILE = HERE / "scenarios_part_a.json"
TEACHER = "glm-5.3-flash"
LOWER = ("gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash")
UPPER = ("deepseek-v4.1-flash", "qwen3.8-27b")
REFERENCE = {"n": 108, "note": 27, "function": 87, "control": 12}  # stated in the protocol before any gate 2 run
NOT_A_RESULT = ("model_error", "cost_cap")
TEST_VERSIONS = (2, 3)
ARMS = ("small_alone", "coach_checked", "compile", "generic_note")
RESAMPLES, SEED, SMALL_D = 10_000, 123, 0.15
MAX_REPEAT = 3  # the first run and at most two redos


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


s1 = _load("stage1_analysis_for_part_a", REPO_ROOT / "experiments" / "stage1" / "analyze_stage1.py")
screen = _load("stage2_part_a_screen_for_gate2", HERE / "part_a.py")


# ---------------------------------------------------------------- what gate 2 must have on file

def scenario_ids() -> list[str]:
    return [item["scenario_id"] for item in json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))["chosen"]]


def kept_students() -> tuple[str, ...]:
    return tuple(json.loads(SCREEN_FILE.read_text(encoding="utf-8"))["decision"]["kept"])


def alone_tasks(scenarios: list[str]) -> list[str]:
    return [f"{scenario}_{version}" for scenario in scenarios for version in (1, *TEST_VERSIONS)]


def test_tasks(scenarios: list[str]) -> list[str]:
    return [f"{scenario}_{version}" for scenario in scenarios for version in TEST_VERSIONS]


def latest_of(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    latest: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["condition"], row["model_key"], row["task_id"])
        if key not in latest or row["repeat"] >= latest[key]["repeat"]:
            latest[key] = row
    return latest


def final_notes(teach: list[dict], student: str) -> dict[str, dict]:
    return {row["scenario_id"]: row for row in teach if row["kind"] == "coach_checked"
            and row["small_model_key"] == student and row["teacher_model_key"] == TEACHER}


def built_notes(teach: list[dict], student: str) -> set[str]:
    return {scenario for scenario, row in final_notes(teach, student).items() if row["status"] == "built"}


def alone_reasons(rows: list[dict], student: str, scenarios: list[str]) -> list[str]:
    latest = latest_of(rows)
    wanted = alone_tasks(scenarios)
    missing = [task for task in wanted if ("small_alone", student, task) not in latest]
    bad = [task for task in wanted if ("small_alone", student, task) in latest
           and latest[("small_alone", student, task)]["stop_reason"] in NOT_A_RESULT]
    reasons = []
    if missing:
        reasons.append(f"{student}: {len(missing)} of {len(wanted)} alone runs missing")
    if bad:
        reasons.append(f"{student}: {len(bad)} alone runs ended in an infrastructure error or a spend stop")
    return reasons


def control_tasks(rows: list[dict], stage1_rows: list[dict], student: str, scenarios: list[str]) -> list[str]:
    """Test tasks the student failed alone, in scenarios where it failed version 1 alone and the teacher passed it."""
    latest, teacher = latest_of(rows), latest_of(stage1_rows)
    tasks = []
    for scenario in scenarios:
        own = latest[("small_alone", student, f"{scenario}_1")]
        if own["success"] or not teacher[("cloud_alone", TEACHER, f"{scenario}_1")]["success"]:
            continue
        tasks += [f"{scenario}_{version}" for version in TEST_VERSIONS
                  if not latest[("small_alone", student, f"{scenario}_{version}")]["success"]]
    return tasks


def wanted_tasks(condition: str, student: str, rows: list[dict], teach: list[dict], stage1_rows: list[dict],
                 scenarios: list[str]) -> list[str]:
    if condition == "small_alone":
        return alone_tasks(scenarios)
    if condition == "coach_checked":
        return test_tasks(sorted(built_notes(teach, student)))
    if condition == "compile":
        return test_tasks(scenarios)
    return control_tasks(rows, stage1_rows, student, scenarios)


def retry_lines(condition: str, student: str, rows: list[dict], teach: list[dict], stage1_rows: list[dict],
                scenarios: list[str]) -> list[str]:
    latest = latest_of(rows)
    by_repeat: dict[int, list[str]] = defaultdict(list)
    for task in wanted_tasks(condition, student, rows, teach, stage1_rows, scenarios):
        row = latest.get((condition, student, task))
        if row is None:
            by_repeat[1].append(task)
        elif row["stop_reason"] in NOT_A_RESULT and row["repeat"] < MAX_REPEAT:
            by_repeat[row["repeat"] + 1].append(task)
    return [f"{repeat} {','.join(sorted(found))}" for repeat, found in sorted(by_repeat.items())]


def screen_task_ids(stage1_teach: list[dict]) -> set[str]:
    chosen = json.loads((REPO_ROOT / "experiments" / "stage1" / "scenarios.json").read_text(encoding="utf-8"))["chosen"]
    difficulty = {item["scenario_id"]: item["difficulty"] for item in chosen}
    return set(screen.screen_tasks(screen.function_scenarios(stage1_teach), difficulty))


def incomplete_reasons(rows: list[dict], teach: list[dict], stage1_rows: list[dict], stage1_teach: list[dict],
                       students: tuple[str, ...], scenarios: list[str]) -> list[str]:
    if not students:
        return ["the screen kept no student"]
    reasons = []
    latest = latest_of(rows)
    allowed: set[tuple[str, str, str]] = {("small_alone", model, task) for model in screen.GUARDS
                                          for task in screen_task_ids(stage1_teach)}
    for student in students:
        alone = alone_reasons(rows, student, scenarios)
        reasons += alone
        notes = final_notes(teach, student)
        if set(notes) != set(scenarios):
            reasons.append(f"{student}: {len(set(scenarios) - set(notes))} of {len(scenarios)} note decisions missing"
                           + (f", {len(set(notes) - set(scenarios))} outside the 23" if set(notes) - set(scenarios) else ""))
        for scenario, row in sorted(notes.items()):
            if row["status"] == "cost_cap":
                reasons.append(f"{student}: the note build for {scenario} was stopped by a spending stop")
            if row["learn_task_id"] != f"{scenario}_1":
                reasons.append(f"{student}: the note for {scenario} was not learned from version 1")
            if not alone and row["status"].startswith("skipped") and not skip_still_holds(
                    row["status"], bool(latest[("small_alone", student, f"{scenario}_1")]["success"]),
                    bool(latest_of(stage1_rows)[("cloud_alone", TEACHER, f"{scenario}_1")]["success"])):
                reasons.append(f"{student}: the skip recorded for {scenario} no longer matches the latest runs")
        if alone:
            continue  # the other arms' task lists depend on the alone runs
        for condition in ARMS:
            wanted = set(wanted_tasks(condition, student, rows, teach, stage1_rows, scenarios))
            allowed |= {(condition, student, task) for task in wanted}
            have = {task for cond, model, task in latest if cond == condition and model == student}
            bad = {task for task in wanted & have if latest[(condition, student, task)]["stop_reason"] in NOT_A_RESULT}
            if wanted - have:
                reasons.append(f"{student}: {len(wanted - have)} of {len(wanted)} {condition} runs missing")
            if bad:
                reasons.append(f"{student}: {len(bad)} {condition} runs ended in an infrastructure error or a spend stop")
    strays = sorted({key for key in latest if key not in allowed})
    if strays:
        reasons.append(f"{len(strays)} runs on file that are not part of the screen or gate 2 "
                       f"({', '.join(':'.join(key) for key in strays[:5])})")
    by_key: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_key[(row["condition"], row["model_key"], row["task_id"])].append(row)
    unearned = sorted(key for key, found in by_key.items()
                      if any(row["stop_reason"] not in NOT_A_RESULT
                             for row in sorted(found, key=lambda r: r["repeat"])[:-1]))
    if unearned:
        reasons.append(f"{len(unearned)} tasks were run again after a run that counted")
    other_builders = {row["small_model_key"] for row in teach} - set(students)
    if other_builders:
        reasons.append(f"note builds on file for students gate 2 does not run: {sorted(other_builders)}")
    return reasons


# ---------------------------------------------------------------- the measures fixed in the protocol

def rates(units: list[dict]) -> dict:
    n = len(units)
    share = (lambda key: sum(bool(unit[key]) for unit in units) / n) if n else (lambda key: None)
    return {"n": n, "note": share("note_fixed"), "function": share("function_fixed"),
            "control": share("control_fixed")}


def contrasts(part_a: list[dict], lower: list[dict]) -> dict | None:
    """The primary and secondary differences, part A students minus the lower tier. None when a group is empty."""
    if not part_a or not lower:
        return None
    a, low = rates(part_a), rates(lower)
    d = a["note"] - low["note"]
    return {"D_A": d, "D_A_net": d - (a["control"] - low["control"]),
            "gap_F_minus_N_diff": (a["function"] - a["note"]) - (low["function"] - low["note"]),
            "F_diff": a["function"] - low["function"]}


def percentile(ordered: list[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap(part_a: list[dict], lower: list[dict], scenarios: list[str], resamples: int = RESAMPLES,
              seed: int = SEED) -> dict:
    """Both groups resampled together over the scenarios; a draw where either group is empty is undefined."""
    by_a: dict[str, list[dict]] = defaultdict(list)
    by_low: dict[str, list[dict]] = defaultdict(list)
    for unit in part_a:
        by_a[unit["scenario"]].append(unit)
    for unit in lower:
        by_low[unit["scenario"]].append(unit)
    generator = random.Random(seed)
    draws: dict[str, list[float]] = defaultdict(list)
    undefined = 0
    for _ in range(resamples):
        drawn = generator.choices(scenarios, k=len(scenarios))
        point = contrasts([unit for s in drawn for unit in by_a[s]], [unit for s in drawn for unit in by_low[s]])
        if point is None:
            undefined += 1
            continue
        for key, value in point.items():
            draws[key].append(value)
    out = {}
    for key, values in draws.items():
        values.sort()
        out[key] = {"low": percentile(values, 0.025), "high": percentile(values, 0.975)}
    return {"intervals_95": out, "n_undefined_resamples": undefined, "resamples": resamples, "seed": seed,
            "unit": "scenario", "interval": "percentile, 2.5 to 97.5"}


def label_for(point: dict | None, intervals: dict) -> tuple[str, bool]:
    """(label, whether it may be quoted as the thesis). The rule is stage 1's, as written in the protocol."""
    if point is None or "D_A" not in intervals:
        return "UNDECIDED", False
    d, net = intervals["D_A"], intervals.get("D_A_net")
    if d["low"] > 0:
        return "CATCHES UP", bool(net and net["low"] > 0)
    if point["D_A"] < SMALL_D and d["low"] <= 0 <= d["high"]:
        return "DOES NOT", False
    return "UNDECIDED", False


# ---------------------------------------------------------------- descriptive parts

def student_table(units: list[dict], strength: dict, latest: dict, teach: list[dict], students: tuple[str, ...],
                  group: str, scenarios: list[str]) -> dict:
    out = {}
    for student in students:
        mine = [unit for unit in units if unit["student"] == student]
        notes = built_notes(teach, student)
        passed_alone = [task for task in test_tasks(scenarios) if latest[("small_alone", student, task)]["success"]]
        with_note = [task for task in passed_alone if task.rsplit("_", 1)[0] in notes]
        out[student] = {
            "group": group, "v1_passed_alone_of_23": strength[student]["v1_passed"],
            "v1_pass_rate_alone": strength[student]["v1_pass_rate"], **{
                key: value for key, value in rates(mine).items()},
            "note_fixed": sum(unit["note_fixed"] for unit in mine),
            "function_fixed": sum(unit["function_fixed"] for unit in mine),
            "control_fixed": sum(unit["control_fixed"] for unit in mine),
            "harm": {"test_tasks_passed_alone": len(passed_alone),
                     "with_a_built_note": len(with_note),
                     "broken_by_note": sum(1 for task in with_note
                                           if not latest[("coach_checked", student, task)]["success"]),
                     "broken_by_function": sum(1 for task in passed_alone
                                               if not latest[("compile", student, task)]["success"])}}
    return out


def arm_costs(latest: dict, students: tuple[str, ...]) -> dict:
    out = {}
    for student in students:
        out[student] = {}
        for condition in ARMS:
            found = [row for (cond, model, _), row in latest.items() if cond == condition and model == student]
            if found:
                out[student][condition] = {
                    "runs": len(found), "passed": sum(bool(row["success"]) for row in found),
                    "mean_cost_usd": round(statistics.mean(row["cost_usd"] for row in found), 6),
                    "median_steps": statistics.median(row["n_steps"] for row in found),
                    "stop_reasons": dict(Counter(row["stop_reason"] for row in found))}
    return out


def builds_table(teach: list[dict], students: tuple[str, ...]) -> dict:
    out = {}
    for student in students:
        final = final_notes(teach, student)
        attempted = [row for row in final.values() if not row["status"].startswith("skipped")]
        out[student] = {"decisions": len(final), "attempted": len(attempted),
                        "status": dict(Counter(row["status"] for row in final.values())),
                        "cost_usd_all_builds": round(sum(row["cost_usd"] for row in teach
                                                         if row["kind"] == "coach_checked"
                                                         and row["small_model_key"] == student), 6),
                        "mean_attempts_when_attempted": (round(statistics.mean(row["attempts"] for row in attempted), 2)
                                                         if attempted else None)}
    return out


def analyze(stage1_rows: list[dict], stage1_teach: list[dict], rows: list[dict], teach: list[dict],
            students: tuple[str, ...], scenarios: list[str]) -> dict:
    lower_all, lower_strength = s1.build_units(stage1_rows, stage1_teach, scenarios, LOWER, TEACHER)
    upper_all, upper_strength = s1.build_units(stage1_rows, stage1_teach, scenarios, UPPER, TEACHER)
    runs_a = stage1_rows + rows
    teach_a = [row for row in stage1_teach if row["kind"] == "compile"] + teach
    part_a_all, part_a_strength = s1.build_units(runs_a, teach_a, scenarios, students, TEACHER)
    lower = [unit for unit in lower_all if unit["note_eligible"]]
    part_a = [unit for unit in part_a_all if unit["note_eligible"]]
    missing_control = [unit["task"] for unit in lower + part_a if not unit["control_ran"]]
    point = contrasts(part_a, lower)
    boot = bootstrap(part_a, lower, scenarios)
    label, quotable = label_for(point, boot["intervals_95"])
    if missing_control:
        label, quotable = "UNDECIDED", False
    low_counts = {"n": len(lower), "note": sum(u["note_fixed"] for u in lower),
                  "function": sum(u["function_fixed"] for u in lower), "control": sum(u["control_fixed"] for u in lower)}
    latest_s1, latest_a = latest_of(stage1_rows), latest_of(runs_a)
    gate2_rows = [row for row in rows if row["model_key"] in students]
    return {
        "students": list(students), "n_scenarios": len(scenarios), "teacher": TEACHER,
        "label": label, "quotable_as_thesis": quotable,
        "point": point, "bootstrap": boot,
        "part_a_pooled": {**rates(part_a), "note_fixed": sum(u["note_fixed"] for u in part_a),
                          "function_fixed": sum(u["function_fixed"] for u in part_a),
                          "control_fixed": sum(u["control_fixed"] for u in part_a)},
        "lower_tier_pooled": {**rates(lower), **{f"{k}_count": v for k, v in low_counts.items()}},
        "lower_tier_matches_protocol_reference": low_counts == REFERENCE,
        "units_without_a_control_run": missing_control,
        "per_student": {**student_table(lower, lower_strength, latest_s1, stage1_teach, LOWER, "lower tier (stage 1)",
                                        scenarios),
                        **student_table([u for u in upper_all if u["note_eligible"]], upper_strength, latest_s1,
                                        stage1_teach, UPPER, "upper tier (stage 1)", scenarios),
                        **student_table(part_a, part_a_strength, latest_a, teach, students, "part A", scenarios)},
        "note_builds": builds_table(teach, students),
        "cost_and_steps_by_arm": arm_costs(latest_of(rows), students),
        "break_even_including_failures": s1.break_even_including_failures(runs_a, teach_a, part_a_all, students,
                                                                          TEACHER),
        "run_facts": {"gate2_rows": len(gate2_rows), "gate2_rows_by_condition": dict(Counter(
                          row["condition"] for row in gate2_rows)),
                      "redone_runs": sum(1 for row in gate2_rows if row["repeat"] > 1),
                      "commits": sorted({row["git_commit"] for row in gate2_rows}),
                      "cost_usd_on_rows": round(sum(row["cost_usd"] for row in gate2_rows), 6),
                      "note_build_cost_usd": round(sum(row["cost_usd"] for row in teach), 6),
                      "first_started": min((row["started"] for row in gate2_rows), default=None),
                      "last_finished": max((row["finished"] for row in gate2_rows), default=None)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("students", "tasks", "ready", "control", "retry", "check", "analyze"))
    parser.add_argument("--arm", choices=("alone", "test"))
    parser.add_argument("--model")
    parser.add_argument("--condition", choices=ARMS)
    parser.add_argument("--out")
    args = parser.parse_args()
    scenarios, students = scenario_ids(), kept_students()
    if args.what == "students":
        print(" ".join(students))
        return 0
    if args.what == "tasks":
        print(",".join(alone_tasks(scenarios) if args.arm == "alone" else test_tasks(scenarios)))
        return 0
    rows = read_jsonl(RUN_DIR / "runs.jsonl") if (RUN_DIR / "runs.jsonl").exists() else []
    teach = read_jsonl(RUN_DIR / "teach.jsonl") if (RUN_DIR / "teach.jsonl").exists() else []
    stage1_rows, stage1_teach = read_jsonl(STAGE1 / "runs.jsonl"), read_jsonl(STAGE1 / "teach.jsonl")
    if args.what in ("ready", "control", "retry") and args.model not in students:
        print(f"{args.model} is not a student gate 2 runs", file=sys.stderr)
        return 2
    if args.what == "ready":
        print("; ".join(alone_reasons(rows, args.model, scenarios)))
        return 0
    if args.what == "control":
        reasons = alone_reasons(rows, args.model, scenarios)
        if reasons:
            print("; ".join(reasons), file=sys.stderr)
            return 2
        print(",".join(control_tasks(rows, stage1_rows, args.model, scenarios)))
        return 0
    if args.what == "retry":
        if args.condition == "generic_note" and alone_reasons(rows, args.model, scenarios):
            return 2
        print("\n".join(retry_lines(args.condition, args.model, rows, teach, stage1_rows, scenarios)))
        return 0
    reasons = incomplete_reasons(rows, teach, stage1_rows, stage1_teach, students, scenarios)
    if args.what == "check":
        print("; ".join(reasons))
        return 0
    if reasons:
        print("STATUS INCOMPLETE; no result computed: " + "; ".join(reasons))
        return 2
    report = {"status": "COMPLETE", **analyze(stage1_rows, stage1_teach, rows, teach, students, scenarios)}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"STATUS COMPLETE; written, not printed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
