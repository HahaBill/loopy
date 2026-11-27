"""Stage 2, part B: the compile arm's function handed over as text in a note (condition code_note).

    part_b.py tasks                 the test tasks: versions 2 and 3 of every scenario with a built function
    part_b.py check                 why part B is not finished; prints nothing when it is
    part_b.py retry --model M       lines "<repeat> <tasks>" for runs to redo: the latest run of the task ended in an
                                    infrastructure error or at a spend stop
    part_b.py analyze --out FILE    writes the result without printing it; refuses while `check` prints anything

The rules are in experiments/stage2/PROTOCOL.md and were written before any code_note run. Stage 1 rows are read, never
written. No task text is read or written here.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl

STAGE1 = REPO_ROOT / "results" / "pilot" / "stage1"
RUN_DIR = REPO_ROOT / "results" / "pilot" / "stage2b"
CONFIG = Path(__file__).resolve().parent / "config.json"
SKILLS = STAGE1 / "raw_large" / "skills" / "shared"
CONDITION = "code_note"
STUDENTS = ("gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash")  # stage 1's lower tier
NOT_A_RESULT = ("model_error", "cost_cap")
RESAMPLES, SEED = 10_000, 123
FUNCTION_DEFINITION = "def workflow("


def latest_rows(rows: list[dict]) -> dict[tuple[str, str, str], dict]:
    latest: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["condition"], row["model_key"], row["task_id"])
        if key not in latest or row["repeat"] >= latest[key]["repeat"]:
            latest[key] = row
    return latest


def built(teach: list[dict], kind: str, owner: str) -> set[str]:
    last = {row["scenario_id"]: row for row in teach if row["kind"] == kind and row["small_model_key"] == owner}
    return {scenario for scenario, row in last.items() if row["status"] == "built"}


def part_b_tasks(teach: list[dict]) -> list[str]:
    return [f"{scenario}_{version}" for scenario in sorted(built(teach, "compile", "shared")) for version in (2, 3)]


def incomplete_reasons(tasks: list[str], rows: list[dict], students: tuple[str, ...] = STUDENTS) -> list[str]:
    reasons = []
    wanted = set(tasks)
    strays = [row for row in rows if row["condition"] != CONDITION or row["model_key"] not in students
              or row["task_id"] not in wanted]
    if strays:
        reasons.append(f"{len(strays)} rows that are not part B runs")
    latest = latest_rows([row for row in rows if row not in strays])
    by_task: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        by_task[(row["model_key"], row["task_id"])].append(row)
    for student in students:
        missing = [task for task in tasks if (CONDITION, student, task) not in latest]
        bad = [task for task in tasks if (CONDITION, student, task) in latest
               and latest[(CONDITION, student, task)]["stop_reason"] in NOT_A_RESULT]
        # a rerun counts only if every run before it ended in an infrastructure error or a spend stop
        unearned = [task for task in tasks
                    if any(row["stop_reason"] not in NOT_A_RESULT
                           for row in sorted(by_task[(student, task)], key=lambda r: r["repeat"])[:-1])]
        if missing:
            reasons.append(f"{student}: {len(missing)} of {len(tasks)} runs missing")
        if bad:
            reasons.append(f"{student}: {len(bad)} runs ended in an infrastructure error or a spend stop")
        if unearned:
            reasons.append(f"{student}: {len(unearned)} tasks were rerun after a run that counted ({','.join(unearned[:5])})")
    return reasons


def retry_lines(tasks: list[str], rows: list[dict], model: str) -> list[str]:
    latest = latest_rows(rows)
    by_repeat: dict[int, list[str]] = defaultdict(list)
    for task in tasks:
        row = latest.get((CONDITION, model, task))
        if row and row["stop_reason"] in NOT_A_RESULT:
            by_repeat[row["repeat"] + 1].append(task)
    return [f"{repeat} {','.join(sorted(found))}" for repeat, found in sorted(by_repeat.items())]


def percentile(ordered: list[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def rates(units: list[dict]) -> dict:
    """Point estimates from a list of failed-alone units (one per student and test task)."""
    both = [unit for unit in units if unit["note_built"]]
    n_all, n_both = len(units), len(both)

    def share(items: list[dict], key: str) -> float | None:
        return sum(unit[key] for unit in items) / len(items) if items else None

    note, function, text = share(both, "note"), share(both, "function"), share(both, "text")
    recovered = None
    if None not in (note, function, text) and function - note > 0:
        recovered = (text - note) / (function - note)
    function_all, text_all = share(units, "function"), share(units, "text")
    return {"n_both_built": n_both, "note": note, "function": function, "text": text, "share_recovered": recovered,
            "n_failed_alone": n_all, "function_all": function_all, "text_all": text_all,
            "function_minus_text_all": None if None in (function_all, text_all) else function_all - text_all}


def label_for(interval: dict | None) -> str:
    if not interval:
        return "INCONCLUSIVE"
    if interval["low"] > 0.5:
        return "MOSTLY WHAT IS SAID"
    if interval["high"] < 0.5:
        return "MOSTLY HOW IT ARRIVES"
    return "MIXED"


def bootstrap(units: list[dict], scenarios: list[str]) -> dict:
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for unit in units:
        by_scenario[unit["scenario"]].append(unit)
    generator = random.Random(SEED)
    draws: dict[str, list[float]] = {"share_recovered": [], "function_minus_text_all": []}
    undefined = Counter()
    for _ in range(RESAMPLES):
        sample = [unit for scenario in generator.choices(scenarios, k=len(scenarios)) for unit in by_scenario[scenario]]
        point = rates(sample)
        for key, values in draws.items():
            if point[key] is None:
                undefined[key] += 1
            else:
                values.append(point[key])
    out = {}
    for key, values in draws.items():
        ordered = sorted(values)
        out[key] = ({"low": percentile(ordered, 0.025), "high": percentile(ordered, 0.975),
                     "n_undefined_resamples": undefined[key]} if ordered else None)
    return out


def analyze(stage1_runs: list[dict], teach: list[dict], part_b_runs: list[dict], tasks: list[str],
            students: tuple[str, ...] = STUDENTS, usage: dict | None = None) -> dict:
    one, two = latest_rows(stage1_runs), latest_rows(part_b_runs)
    units, harm, per_student = [], {}, {}
    for student in students:
        notes = built(teach, "coach_checked", student)
        mine, passed_alone = [], []
        for task in tasks:
            scenario = task.rsplit("_", 1)[0]
            alone = bool(one[("small_alone", student, task)]["success"])
            function = bool(one[("compile", student, task)]["success"])
            text = bool(two[(CONDITION, student, task)]["success"])
            note_row = one.get(("coach_checked", student, task)) if scenario in notes else None
            unit = {"student": student, "scenario": scenario, "task": task, "function": function, "text": text,
                    "note_built": note_row is not None, "note": bool(note_row and note_row["success"])}
            (passed_alone if alone else mine).append(unit)
        units += mine
        per_student[student] = rates(mine)
        harm[student] = {"passed_alone": len(passed_alone),
                         "broken_with_function": sum(not unit["function"] for unit in passed_alone),
                         "broken_with_text": sum(not unit["text"] for unit in passed_alone)}
    scenarios = sorted({task.rsplit("_", 1)[0] for task in tasks})
    point, intervals = rates(units), bootstrap(units, scenarios)
    return {"students": list(students), "n_tasks_per_student": len(tasks), "pooled": point, "intervals_95": intervals,
            "label": label_for(intervals["share_recovered"]) if point["share_recovered"] is not None else "INCONCLUSIVE",
            "per_student": per_student, "harm_on_tasks_passed_alone": harm,
            "bootstrap": {"unit": "scenario", "resamples": RESAMPLES, "seed": SEED, "interval": "percentile, 2.5 to 97.5"},
            "usage": usage or {},
            "cost_usd_all_part_b_rows": round(sum(row["cost_usd"] or 0 for row in part_b_runs), 6)}


def usage_report(part_b_runs: list[dict], run_dir: Path, config: dict) -> dict:
    """What students did with the code, from the raw files (kept local): pasted the function or not, steps, length."""
    out = {}
    latest = latest_rows(part_b_runs)
    for student in sorted({key[1] for key in latest}):
        limit = config["models"][student].get("max_tokens", 1500)
        counts = Counter()
        for (_, model, task), row in latest.items():
            if model != student:
                continue
            raw_path = run_dir / "raw_large" / f"{CONDITION}__{student}__{task}__r{row['repeat']}.json"
            source = (SKILLS / task.rsplit("_", 1)[0] / "compiled_workflow.py").read_text(encoding="utf-8")
            fits = len(source) / 3.5 <= limit - 200  # rough: could the student write the function out in one reply
            pasted = None
            if raw_path.exists():
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                pasted = any(FUNCTION_DEFINITION in str(step.get("code", "")) for step in raw.get("steps", []))
            counts["runs"] += 1
            counts["passed"] += bool(row["success"])
            counts["function_fits_output_limit"] += fits
            counts["passed_where_it_fits"] += bool(fits and row["success"])
            if pasted is None:
                counts["raw_file_missing"] += 1
            else:
                counts["pasted_the_function"] += pasted
                counts["passed_after_pasting"] += bool(pasted and row["success"])
            counts["steps_total"] += row["n_steps"]
        out[student] = dict(counts)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("tasks", "check", "retry", "analyze"))
    parser.add_argument("--model")
    parser.add_argument("--out")
    args = parser.parse_args()
    teach = read_jsonl(STAGE1 / "teach.jsonl")
    tasks = part_b_tasks(teach)
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
        print("STATUS INCOMPLETE; no result computed: " + "; ".join(reasons))
        return 2
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = {"status": "COMPLETE",
              **analyze(read_jsonl(STAGE1 / "runs.jsonl"), teach, rows, tasks, usage=usage_report(rows, RUN_DIR, config))}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"STATUS COMPLETE; written, not printed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
