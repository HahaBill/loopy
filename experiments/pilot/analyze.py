"""Read a pilot run: per-condition results, the four signals from the plan, and cost per solved task.

    .venv/Scripts/python.exe experiments/pilot/analyze.py --run-name pilot1 --small-model <key> --cloud-model <key>

Reads results/pilot/<run-name>/runs.jsonl and teach.jsonl, prints a summary and writes summary.json next to
them. It only counts and divides; every number can be recomputed by hand from the two files.

The four signals are read as proposed in experiments/pilot/README.md ("Proposed readings"), which was written
before any pilot arm ran. With 9 tasks they are coarse, and they are proposals until the team agrees on them.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl

FORECAST_AUROC_THRESHOLD = 0.65
SMALL_FAILS_OFTEN_AT_LEAST = 3
TEST_VERSIONS = (2, 3)
RESOURCE_FIELDS = ("cost_usd", "cloud_calls", "requests", "input_tokens", "output_tokens", "model_seconds",
                   "wall_seconds", "n_steps")


def auroc(scores_of_failures: list[float], scores_of_passes: list[float]) -> float | None:
    """Chance that a failed run got a higher forecast of failure than a passed run (ties count half)."""
    if not scores_of_failures or not scores_of_passes:
        return None
    wins = 0.0
    for failed in scores_of_failures:
        for passed in scores_of_passes:
            wins += 1.0 if failed > passed else 0.5 if failed == passed else 0.0
    return wins / (len(scores_of_failures) * len(scores_of_passes))


def latest_repeats(records: list[dict]) -> list[dict]:
    """One row per task, condition and model: the outcome of the highest repeat, the resources of all repeats."""
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in records:
        grouped[(row["task_id"], row["condition"], row["model_key"])].append(row)
    merged = []
    for rows in grouped.values():
        last = max(enumerate(rows), key=lambda item: (item[1].get("repeat", 1), item[0]))[1]
        spent = {key: sum(row[key] for row in rows) for key in RESOURCE_FIELDS if all(key in row for row in rows)}
        merged.append({**last, **spent, "n_repeats": len(rows)})
    return merged


def condition_table(records: list[dict]) -> dict[str, dict]:
    table: dict[str, dict] = {}
    by_condition: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for record in latest_repeats(records):
        by_condition[(record["condition"], record["model_key"])].append(record)
    for (condition, model_key), rows in sorted(by_condition.items()):
        n = len(rows)
        passed = sum(1 for row in rows if row["success"])
        table[f"{condition} [{model_key}]"] = {
            "n_runs": n,
            "n_rerun_rows": sum(row["n_repeats"] - 1 for row in rows),
            "n_passed": passed,
            "n_bug_failures": sum(1 for row in rows if row["failure_type"] == "bug"),
            "n_quality_failures": sum(1 for row in rows if row["failure_type"] == "quality"),
            "cost_usd_total": round(sum(row["cost_usd"] for row in rows), 6),
            "cost_usd_per_run": round(sum(row["cost_usd"] for row in rows) / n, 6),
            "wall_seconds_per_run": round(sum(row["wall_seconds"] for row in rows) / n, 1),
            "steps_per_run": round(sum(row["n_steps"] for row in rows) / n, 1),
            "input_tokens_per_run": round(sum(row["input_tokens"] for row in rows) / n),
            "cloud_calls_total": sum(row["cloud_calls"] for row in rows),
        }
    return table


def forecast_reading(rows: list[dict]) -> dict:
    with_forecast = [row for row in rows if row.get("forecast_p_fail") is not None]
    failed = [row["forecast_p_fail"] for row in with_forecast if not row["success"]]
    passed = [row["forecast_p_fail"] for row in with_forecast if row["success"]]
    value = auroc(failed, passed)
    return {
        "n_runs": len(rows),
        "n_with_forecast": len(with_forecast),
        "mean_forecast_on_failed_runs": round(sum(failed) / len(failed), 3) if failed else None,
        "mean_forecast_on_passed_runs": round(sum(passed) / len(passed), 3) if passed else None,
        "auroc": None if value is None else round(value, 3),
    }


def option_costs(records: list[dict], teach: list[dict], small: str, cloud: str) -> dict[str, dict]:
    """Per scenario, on the test versions the small model failed alone: what each option cost and solved."""
    def find(task_id: str, condition: str, model_key: str) -> dict | None:
        rows = [row for row in records if row["task_id"] == task_id and row["condition"] == condition
                and row["model_key"] == model_key]
        return rows[0] if rows else None

    scenarios = sorted({row["scenario_id"] for row in records})
    result: dict[str, dict] = {}
    for scenario in scenarios:
        alone = [row for row in records if row["scenario_id"] == scenario and row["condition"] == "small_alone"
                 and row["model_key"] == small and row["version"] in TEST_VERSIONS]
        needs_help = [row["task_id"] for row in alone if not row["success"]]
        entry: dict = {"test_tasks_small_failed_alone": needs_help, "options": {}}
        build: dict[str, dict] = {}  # every attempt's cost counts; the last attempt gives the status
        for row in teach:
            if row["scenario_id"] == scenario and row["teacher_model_key"] == cloud and row["small_model_key"] == small:
                previous = build.get(row["kind"])
                build[row["kind"]] = {**row,
                                      "cost_usd": row["cost_usd"] + (previous["cost_usd"] if previous else 0.0),
                                      "cloud_calls": row["cloud_calls"] + (previous["cloud_calls"] if previous else 0)}
        for option, condition, model_key in (("rent", "cloud_alone", cloud), ("coach", "coach", small),
                                             ("compile", "compile", small)):
            runs = [find(task_id, condition, model_key) for task_id in needs_help]
            present = [row for row in runs if row is not None]
            build_row = build.get(option)
            build_cost = float(build_row["cost_usd"]) if build_row else 0.0
            build_calls = int(build_row["cloud_calls"]) if build_row else 0
            solved = sum(1 for row in present if row["success"])
            run_cost = sum(row["cost_usd"] for row in present)
            total = build_cost + run_cost
            entry["options"][option] = {
                "n_tasks": len(needs_help),
                "n_runs_found": len(present),
                "n_solved": solved,
                "build_status": build_row["status"] if build_row else ("not needed" if option == "rent" else None),
                "build_cost_usd": round(build_cost, 6),
                "run_cost_usd": round(run_cost, 6),
                "cloud_calls": build_calls + sum(row["cloud_calls"] for row in present),
                "cost_usd_per_solved_task": round(total / solved, 6) if solved else None,
            }
        solved_options = {name: data["cost_usd_per_solved_task"] for name, data in entry["options"].items()
                          if data["cost_usd_per_solved_task"] is not None}
        entry["cheapest_option"] = min(solved_options, key=solved_options.get) if solved_options else None
        result[scenario] = entry
    return result


def skill_effects(records: list[dict], small: str) -> dict[str, dict]:
    """On the test versions: what a skill changed compared with the small model alone, task by task."""
    effects: dict[str, dict] = {}
    alone = {row["task_id"]: row for row in records if row["condition"] == "small_alone"
             and row["model_key"] == small and row["version"] in TEST_VERSIONS}
    for condition in ("coach", "compile"):
        with_skill = {row["task_id"]: row for row in records if row["condition"] == condition
                      and row["model_key"] == small}
        common = sorted(set(alone) & set(with_skill))
        effects[condition] = {
            "n_tasks_with_both_runs": len(common),
            "fixed (failed alone, passed with it)": [task for task in common
                                                     if not alone[task]["success"] and with_skill[task]["success"]],
            "hurt (passed alone, failed with it)": [task for task in common
                                                    if alone[task]["success"] and not with_skill[task]["success"]],
            "still failing": [task for task in common
                              if not alone[task]["success"] and not with_skill[task]["success"]],
            "still passing": [task for task in common if alone[task]["success"] and with_skill[task]["success"]],
        }
    return effects


def read_signals(records: list[dict], teach: list[dict], small: str, cloud: str) -> dict:
    alone = [row for row in records if row["condition"] == "small_alone" and row["model_key"] == small]
    n_failed = sum(1 for row in alone if not row["success"])
    signal_1 = {"small_alone_failed": n_failed, "of": len(alone),
                "holds": n_failed >= SMALL_FAILS_OFTEN_AT_LEAST if alone else None}

    failed_tests = [row["task_id"] for row in alone if not row["success"] and row["version"] in TEST_VERSIONS]
    fixed = {}
    for condition in ("coach", "compile"):
        passes = {row["task_id"] for row in records if row["condition"] == condition
                  and row["model_key"] == small and row["success"]}
        fixed[condition] = sorted(set(failed_tests) & passes)
    best = max((len(tasks) for tasks in fixed.values()), default=0)
    signal_2 = {"test_tasks_small_failed_alone": failed_tests, "fixed_by_coach": fixed["coach"],
                "fixed_by_compile": fixed["compile"],
                "holds": (best * 2 >= len(failed_tests)) if failed_tests else None}

    costs = option_costs(records, teach, small, cloud)
    cheapest = {scenario: entry["cheapest_option"] for scenario, entry in costs.items()
                if entry["test_tasks_small_failed_alone"]}
    decided = [option for option in cheapest.values() if option is not None]
    signal_3 = {"cheapest_option_by_scenario": cheapest,
                "holds": (len(set(decided)) > 1) if len(decided) >= 2 else None}

    forecast = forecast_reading(alone)
    signal_4 = {**forecast, "threshold": FORECAST_AUROC_THRESHOLD,
                "holds": None if forecast["auroc"] is None else forecast["auroc"] >= FORECAST_AUROC_THRESHOLD}

    signals = {"1_small_model_fails_often": signal_1, "2_coach_or_compile_fixes_new_versions": signal_2,
               "3_no_option_always_wins": signal_3, "4_forecast_tracks_outcomes": signal_4}
    holding = [name for name, signal in signals.items() if signal["holds"] is True]
    unreadable = [name for name, signal in signals.items() if signal["holds"] is None]
    return {"signals": signals, "n_holding": len(holding), "holding": holding, "not_readable": unreadable,
            "option_costs": costs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--small-model", required=True)
    parser.add_argument("--cloud-model", required=True)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    run_dir = REPO_ROOT / "results" / "pilot" / args.run_name
    records = read_jsonl(run_dir / "runs.jsonl")
    teach = read_jsonl(run_dir / "teach.jsonl")
    labels = sorted({str(row.get("label")) for row in records + teach})
    summary = {
        "run_name": args.run_name,
        "labels": labels,
        "small_model": args.small_model,
        "cloud_model": args.cloud_model,
        "n_run_records": len(records),
        "n_teach_records": len(teach),
        "by_condition": condition_table(records),
        "teach": [{key: row.get(key) for key in ("scenario_id", "kind", "round", "status", "validated", "attempts",
                                                 "cloud_calls", "cost_usd", "divergence_step", "failure_kind")}
                  for row in teach],
        "skill_effects_on_test_versions": skill_effects(latest_repeats(records), args.small_model),
        **read_signals(latest_repeats(records), teach, args.small_model, args.cloud_model),
        "total_cost_usd": round(sum(row["cost_usd"] for row in records) + sum(row["cost_usd"] for row in teach), 6),
    }
    print(json.dumps(summary, indent=2))
    if not args.no_write:
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"written: {run_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
