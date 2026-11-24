"""Compare what each stage 1 run's row says it cost with what the spend ledger recorded for that run.

    .venv/Scripts/python.exe experiments/stage1/ledger_vs_rows.py --out results/pilot/stage1/<file>.json

Why: until Nov 24, 2026 a run's row summed the cost of its finished steps. If AppWorld raised after a model reply, that
reply was charged to the budget (and so to the ledger) but its step was never stored, so the row missed one request.
The ledger is the spend of record. This script measures how far the rows fall short of it. It reads only; it edits
nothing. The output holds ids, counts and dollars, no task text.

How ledger rows are matched to runs (the ledger was written in two ways during stage 1):

- one ledger row per run, with the task in its note ("<condition> <model> <task>"): the teacher, alone, note-test and
  function-test arms. Ledger rows and run rows of the same condition, model and task are paired in time order.
- one ledger row per request, with no task in its note ("<condition> <model>"): the generic-note control. Each
  student's control runs ran one after another, so a ledger row belongs to the run whose start and finish times
  contain it. Times are whole seconds. A request on the second where one run ends and the next starts could belong to
  either, so those two runs are compared together, as one sum.

Ledger rows written by hand (upper estimates for jobs stopped in flight) and the rows of the builders are not run
costs and are left out of the run comparison; they are counted in the output.

Note builds are compared too, because a note's validation is a student run with the same weakness. Each note build
has one ledger row ("build_coach_checked <student> <scenario>") and its rows in teach.jsonl. Function builds are not
compared: their validation calls no model, and part of their ledger was written by hand after the pauses.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl

RUN_CONDITIONS = ("cloud_alone", "small_alone", "coach", "coach_checked", "compile", "generic_note")
ROUNDING_USD = 1e-6  # both sides are rounded to 6 decimals
BY_TASK = "task in the ledger note, time order"
BY_TIME = "request time inside the run's start and finish"
BY_TIME_TOGETHER = "request times inside the start and finish of runs that share a boundary second"


def when(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp)


def compare(runs: list[dict], ledger: list[dict], run_name: str) -> dict:
    """Pairs ledger rows with runs and lists every run, or group of runs, whose rows and ledger disagree."""
    per_run: dict[tuple[str, str, str], list[dict]] = defaultdict(list)      # the note names the task
    per_request: dict[tuple[str, str], list[dict]] = defaultdict(list)       # the note names no task
    other = []
    for entry in ledger:
        if entry.get("run") != run_name:
            continue
        words = str(entry.get("note", "")).split(" ")
        if words[0] in RUN_CONDITIONS and len(words) == 3:
            per_run[(words[0], words[1], words[2])].append(entry)
        elif words[0] in RUN_CONDITIONS and len(words) == 2:
            per_request[(words[0], words[1])].append(entry)
        else:
            other.append(entry)

    rows_by_task: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    rows_by_arm: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in runs:
        rows_by_task[(row["condition"], row["model_key"], row["task_id"])].append(row)
        rows_by_arm[(row["condition"], row["model_key"])].append(row)

    compared, unmatched_rows, unmatched_ledger = [], [], []

    def add(rows: list[dict], entries: list[dict], how: str) -> None:
        ledger_usd = round(sum(float(entry["usd"]) for entry in entries), 6)
        row_usd = round(sum(row["cost_usd"] for row in rows), 6)
        compared.append({"condition": rows[0]["condition"], "model_key": rows[0]["model_key"],
                         "runs": [{"task_id": row["task_id"], "repeat": row["repeat"],
                                   "stop_reason": row["stop_reason"], "requests": row["requests"],
                                   "row_usd": row["cost_usd"]} for row in rows],
                         "matched_by": how, "n_ledger_rows": len(entries),
                         "row_requests": sum(row["requests"] for row in rows),
                         "row_usd": row_usd, "ledger_usd": ledger_usd,
                         "ledger_minus_row_usd": round(ledger_usd - row_usd, 6),
                         "tolerance_usd": round(ROUNDING_USD * (1 + (len(entries) + len(rows)) / 2), 6)})

    arms_per_request = set(per_request)
    for key, rows in sorted(rows_by_task.items()):
        if (key[0], key[1]) in arms_per_request:
            continue
        entries = sorted(per_run.pop(key, []), key=lambda entry: when(entry["time"]))
        rows = sorted(rows, key=lambda row: (when(row["finished"]), row["repeat"]))
        if len(entries) != len(rows):  # cannot pair one to one: compare nothing, list both
            unmatched_rows += [{"condition": key[0], "model_key": key[1], "task_id": key[2], "repeat": row["repeat"],
                                "row_usd": row["cost_usd"]} for row in rows]
            unmatched_ledger += entries
            continue
        for row, entry in zip(rows, entries):
            add([row], [entry], BY_TASK)
    unmatched_ledger += [entry for entries in per_run.values() for entry in entries]

    for arm, entries in sorted(per_request.items()):
        rows = sorted(rows_by_arm.get(arm, []), key=lambda row: when(row["started"]))
        group = list(range(len(rows)))  # runs that could both own one ledger row are compared together

        def root(index: int) -> int:
            while group[index] != index:
                index = group[index]
            return index

        owned: list[tuple[int, dict]] = []
        for entry in entries:
            at = when(entry["time"])
            inside = [index for index, row in enumerate(rows) if when(row["started"]) <= at <= when(row["finished"])]
            if not inside:
                unmatched_ledger.append(entry)
                continue
            for index in inside[1:]:
                group[root(index)] = root(inside[0])
            owned.append((inside[0], entry))
        members: dict[int, list[dict]] = defaultdict(list)
        for index, row in enumerate(rows):
            members[root(index)].append(row)
        entries_of: dict[int, list[dict]] = defaultdict(list)
        for index, entry in owned:
            entries_of[root(index)].append(entry)
        for index, together in sorted(members.items()):
            add(together, entries_of.get(index, []), BY_TIME if len(together) == 1 else BY_TIME_TOGETHER)

    differ = [item for item in compared if abs(item["ledger_minus_row_usd"]) > item["tolerance_usd"]]
    by_arm: dict[str, dict] = {}
    for item in compared:
        cell = by_arm.setdefault(item["condition"], {"n_runs": 0, "row_usd": 0.0, "ledger_usd": 0.0,
                                                     "n_runs_that_differ": 0})
        cell["n_runs"] += len(item["runs"])
        cell["row_usd"] += item["row_usd"]
        cell["ledger_usd"] += item["ledger_usd"]
        cell["n_runs_that_differ"] += len(item["runs"]) if item in differ else 0
    for cell in by_arm.values():
        cell["row_usd"], cell["ledger_usd"] = round(cell["row_usd"], 6), round(cell["ledger_usd"], 6)
        cell["ledger_minus_row_usd"] = round(cell["ledger_usd"] - cell["row_usd"], 6)
    return {
        "run_name": run_name,
        "n_run_rows": len(runs),
        "n_runs_compared": sum(len(item["runs"]) for item in compared),
        "n_comparisons": len(compared),
        "n_runs_compared_together_with_a_neighbour": sum(len(item["runs"]) for item in compared
                                                         if len(item["runs"]) > 1),
        "n_runs_that_differ": sum(len(item["runs"]) for item in differ),
        "ledger_minus_row_usd_over_runs_that_differ": round(sum(item["ledger_minus_row_usd"] for item in differ), 6),
        "ledger_minus_row_usd_over_all_compared": round(sum(item["ledger_minus_row_usd"] for item in compared), 6),
        "row_usd_compared": round(sum(item["row_usd"] for item in compared), 6),
        "ledger_usd_compared": round(sum(item["ledger_usd"] for item in compared), 6),
        "by_condition": dict(sorted(by_arm.items())),
        "runs_that_differ": sorted(differ, key=lambda item: -abs(item["ledger_minus_row_usd"])),
        "run_rows_not_compared": unmatched_rows,
        "ledger_rows_of_runs_not_matched": {"n": len(unmatched_ledger),
                                            "usd": round(sum(float(entry["usd"]) for entry in unmatched_ledger), 6)},
        "ledger_rows_that_are_not_run_costs": {"n": len(other), "usd": round(sum(float(e["usd"]) for e in other), 6),
                                               "what": "builders' rows and rows written by hand"},
    }


def compare_note_builds(teach: list[dict], ledger: list[dict], run_name: str) -> dict:
    """Each student's note build: what its ledger rows sum to against the cost in its teach rows."""
    in_ledger: dict[tuple[str, str], float] = defaultdict(float)
    for entry in ledger:
        words = str(entry.get("note", "")).split(" ")
        if entry.get("run") == run_name and words[0] == "build_coach_checked" and len(words) == 3:
            in_ledger[(words[1], words[2])] += float(entry["usd"])
    in_rows: dict[tuple[str, str], float] = defaultdict(float)
    for row in teach:
        if row["kind"] == "coach_checked" and row["cost_usd"] > 0:
            in_rows[(row["small_model_key"], row["scenario_id"])] += row["cost_usd"]
    both = sorted(set(in_ledger) & set(in_rows))
    differ = [{"student": student, "scenario_id": scenario, "row_usd": round(in_rows[(student, scenario)], 6),
               "ledger_usd": round(in_ledger[(student, scenario)], 6),
               "ledger_minus_row_usd": round(in_ledger[(student, scenario)] - in_rows[(student, scenario)], 6)}
              for student, scenario in both
              if abs(in_ledger[(student, scenario)] - in_rows[(student, scenario)]) > 2 * ROUNDING_USD]
    return {"n_builds_compared": len(both), "n_builds_that_differ": len(differ),
            "row_usd": round(sum(in_rows[key] for key in both), 6),
            "ledger_usd": round(sum(in_ledger[key] for key in both), 6),
            "builds_that_differ": differ,
            "n_builds_in_only_one_file": len(set(in_ledger) ^ set(in_rows))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-dir", default=str(REPO_ROOT / "results" / "pilot" / "stage1"))
    parser.add_argument("--ledger", default=str(REPO_ROOT / "results" / "spend_ledger.jsonl"))
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    ledger = read_jsonl(args.ledger)
    report = compare(read_jsonl(run_dir / "runs.jsonl"), ledger, run_dir.name)
    report["note_builds"] = compare_note_builds(read_jsonl(run_dir / "teach.jsonl"), ledger, run_dir.name)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"{report['n_runs_compared']} of {report['n_run_rows']} runs compared; {report['n_runs_that_differ']} differ; "
          f"ledger minus rows ${report['ledger_minus_row_usd_over_runs_that_differ']:.6f}; written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
