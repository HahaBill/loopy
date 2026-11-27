"""Stage 2, part A, gate 1: the screen for students of middle strength (condition small_alone).

    part_a.py tasks                 the 12 screen tasks
    part_a.py retry --model M       lines "<repeat> <tasks>" for runs to redo: the latest run ended in an infrastructure error
    part_a.py check                 why the screen is not finished; prints nothing when it is
    part_a.py screen --out FILE     writes the table and the decision; refuses while `check` prints anything

The rules are in experiments/stage2/PROTOCOL_PART_A.md and were written before any run of a part A model. Rows are read,
never written. No task text is read or written here.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl

STAGE1 = REPO_ROOT / "results" / "pilot" / "stage1"
RUN_DIR = REPO_ROOT / "results" / "pilot" / "stage2a"
CONDITION = "small_alone"
GUARDS = {"qwen3-235b-instruct": 1.2, "nemotron-3-super-120b": 1.2, "inkling-2-small": 1.2,
          "nemotron-3.5-lightning": 0.4}  # dollars per candidate
SCREEN_COUNTS = {1: 5, 2: 3, 3: 4}  # tasks per AppWorld difficulty level, the proportion of the 23 scenarios
BAND = (5, 9)  # passes of 12 that count as middle strength
TARGET = 0.55
MAX_KEPT = 2
PART_A_STOP_USD = 12.0
GATE2_RUNS, GATE2_TEACHER_USD = 116, 0.60  # estimated gate 2 cost = runs x mean cost per screen run + teacher
MAX_REDOS = 2


def function_scenarios(teach: list[dict]) -> set[str]:
    last = {row["scenario_id"]: row for row in teach if row["kind"] == "compile" and row["small_model_key"] == "shared"}
    return {scenario for scenario, row in last.items() if row["status"] == "built"}


def screen_tasks(scenarios: set[str], difficulty: dict[str, int]) -> list[str]:
    """Version 1 of the first scenario ids, in sorted order, at each difficulty level. Looks at no result."""
    tasks = []
    for level, count in sorted(SCREEN_COUNTS.items()):
        found = sorted(scenario for scenario in scenarios if difficulty[scenario] == level)
        if len(found) < count:
            raise ValueError(f"level {level}: {len(found)} scenarios with a function, {count} needed")
        tasks += [f"{scenario}_1" for scenario in found[:count]]
    return tasks


def latest_rows(rows: list[dict]) -> dict[tuple[str, str], dict]:
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["model_key"], row["task_id"])
        if key not in latest or row["repeat"] >= latest[key]["repeat"]:
            latest[key] = row
    return latest


def screen_rows(rows: list[dict], tasks: list[str]) -> list[dict]:
    wanted = set(tasks)
    return [row for row in rows if row["condition"] == CONDITION and row["model_key"] in GUARDS
            and row["task_id"] in wanted]


def cut_short(rows: list[dict], model: str) -> bool:
    """A spending stop (its own guard or the provider stop) ended this candidate's screen."""
    return any(row["model_key"] == model and row["stop_reason"] == "cost_cap" for row in rows)


def incomplete_reasons(tasks: list[str], rows: list[dict]) -> list[str]:
    reasons = []
    mine = screen_rows(rows, tasks)
    if len(mine) != len(rows):
        reasons.append(f"{len(rows) - len(mine)} rows that are not screen runs")
    latest = latest_rows(mine)
    by_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in mine:
        by_task[(row["model_key"], row["task_id"])].append(row)
    for model in GUARDS:
        if cut_short(mine, model):
            continue  # out by the budget rule; nothing more to wait for
        missing = [task for task in tasks if (model, task) not in latest]
        errors = [task for task in tasks if (model, task) in latest and latest[(model, task)]["stop_reason"] == "model_error"]
        unearned = [task for task in tasks
                    if any(row["stop_reason"] != "model_error"
                           for row in sorted(by_task[(model, task)], key=lambda r: r["repeat"])[:-1])]
        if missing:
            reasons.append(f"{model}: {len(missing)} of {len(tasks)} runs missing")
        if errors:
            reasons.append(f"{model}: {len(errors)} runs ended in an infrastructure error")
        if unearned:
            reasons.append(f"{model}: {len(unearned)} tasks were rerun after a run that counted")
    return reasons


def retry_lines(tasks: list[str], rows: list[dict], model: str) -> list[str]:
    mine = screen_rows(rows, tasks)
    if cut_short(mine, model):
        return []
    latest = latest_rows(mine)
    by_repeat: dict[int, list[str]] = defaultdict(list)
    for task in tasks:
        row = latest.get((model, task))
        if row and row["stop_reason"] == "model_error" and row["repeat"] <= MAX_REDOS:
            by_repeat[row["repeat"] + 1].append(task)
    return [f"{repeat} {','.join(sorted(found))}" for repeat, found in sorted(by_repeat.items())]


def decide(results: dict[str, dict], screen_spend: float) -> dict:
    """The keep rule. `results[model]` has passes, n, cost_per_run and cut_short."""
    low, high = BAND
    status = {}
    for model, result in results.items():
        if result["cut_short"]:
            status[model] = "out: cut short by a spending stop"
        elif result["passes"] < low:
            status[model] = "below the band"
        elif result["passes"] > high:
            status[model] = "above the band"
        else:
            status[model] = "in the band"
    ranked = sorted((model for model, text in status.items() if text == "in the band"),
                    key=lambda model: (abs(results[model]["passes"] / results[model]["n"] - TARGET),
                                       results[model]["cost_per_run"], model))
    left = PART_A_STOP_USD - screen_spend
    kept, estimates = [], {}
    for model in ranked:
        estimates[model] = round(GATE2_RUNS * results[model]["cost_per_run"] + GATE2_TEACHER_USD, 2)
        if len(kept) < MAX_KEPT and estimates[model] <= left:
            kept.append(model)
            left -= estimates[model]
        else:
            status[model] = "in the band, not kept: gate 2 does not fit" if estimates[model] > left else \
                "in the band, not kept: two are kept already"
    return {"status": status, "ranked": ranked, "kept": kept, "gate2_estimate_usd": estimates,
            "left_of_part_a_stop_usd": round(left, 2)}


def screen_report(tasks: list[str], rows: list[dict]) -> dict:
    mine = screen_rows(rows, tasks)
    latest = latest_rows(mine)
    results, table = {}, {}
    for model in GUARDS:
        final = [latest[(model, task)] for task in tasks if (model, task) in latest]
        counted = [row for row in final if row["stop_reason"] not in ("model_error", "cost_cap")]
        spent = sum(row["cost_usd"] for row in mine if row["model_key"] == model)
        results[model] = {"passes": sum(row["success"] for row in counted), "n": len(tasks),
                          "cost_per_run": spent / len(counted) if counted else float("inf"),
                          "cut_short": cut_short(mine, model)}
        table[model] = {"passes": results[model]["passes"], "runs_counted": len(counted), "tasks": len(tasks),
                        "passes_by_difficulty": {str(level): sum(row["success"] for row in counted
                                                                 if row["difficulty"] == level)
                                                 for level in sorted(SCREEN_COUNTS)},
                        "spent_usd": round(spent, 6),
                        "cost_per_counted_run_usd": round(spent / len(counted), 6) if counted else None,
                        "median_steps": sorted(row["n_steps"] for row in counted)[len(counted) // 2] if counted else None,
                        "redone_runs": sum(1 for row in mine if row["model_key"] == model and row["repeat"] > 1),
                        "cut_short": results[model]["cut_short"]}
    spend = round(sum(row["cost_usd"] for row in mine), 6)
    return {"band_passes_of_12": list(BAND), "target_rate": TARGET, "screen_spend_usd_on_rows": spend,
            "candidates": table, "decision": decide(results, spend)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("tasks", "check", "retry", "screen"))
    parser.add_argument("--model")
    parser.add_argument("--out")
    args = parser.parse_args()
    chosen = json.loads((REPO_ROOT / "experiments" / "stage1" / "scenarios.json").read_text(encoding="utf-8"))["chosen"]
    difficulty = {item["scenario_id"]: item["difficulty"] for item in chosen}
    tasks = screen_tasks(function_scenarios(read_jsonl(STAGE1 / "teach.jsonl")), difficulty)
    if args.what == "tasks":
        print(",".join(tasks))
        return 0
    runs_path = RUN_DIR / "runs.jsonl"
    rows = read_jsonl(runs_path) if runs_path.exists() else []
    if args.what == "check":
        print("; ".join(incomplete_reasons(tasks, rows)))
        return 0
    if args.what == "retry":
        print("\n".join(retry_lines(tasks, rows, args.model)))
        return 0
    reasons = incomplete_reasons(tasks, rows)
    if reasons:
        print("STATUS INCOMPLETE; no decision computed: " + "; ".join(reasons))
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump({"status": "COMPLETE", **screen_report(tasks, rows)}, handle, indent=2)
        handle.write("\n")
    print(f"STATUS COMPLETE; written, not printed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
