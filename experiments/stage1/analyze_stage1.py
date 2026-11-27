"""The stage 1 analysis fixed in PROTOCOL.md. It only counts, divides and resamples.

    .venv/Scripts/python.exe experiments/stage1/analyze_stage1.py --run-dir results/pilot/stage1 --out <file.json>

It refuses to compute any result until every required run and build is on file, the generic-note control included, and
the outcomes in runs.jsonl match the raw trajectory files. It prints only the status and the output path, so nobody
reads a label by accident.
The output holds ids, counts, rates, dollars and seconds, no task text.
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

HERE = Path(__file__).resolve().parent
TEST_VERSIONS = (2, 3)
LOWER_BELOW, UPPER_FROM = 0.25, 0.50
FUNCTION_BAR, SMALL_D = 0.70, 0.15
N_RESAMPLES, SEED = 10_000, 123
SKILL_ARMS = {"note": ("coach_checked", 1), "function": ("compile", 2)}  # column in a student's [n, note, function]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sweep = _load("stage1_sweep_for_analysis", HERE / "sweep.py")
pilot = _load("pilot_analyze_for_stage1", HERE.parent / "pilot" / "analyze.py")


def tier_of(rate: float) -> str:
    return "lower" if rate < LOWER_BELOW else "upper" if rate >= UPPER_FROM else "middle"


def final_builds(teach: list[dict], kind: str, owner: str) -> dict[str, dict]:
    return {row["scenario_id"]: row for row in teach if row["kind"] == kind and row["small_model_key"] == owner}


def build_cost(teach: list[dict], kind: str, owner: str, scenario: str) -> float:
    return sum(row["cost_usd"] for row in teach
               if row["kind"] == kind and row["small_model_key"] == owner and row["scenario_id"] == scenario)


def build_units(runs: list[dict], teach: list[dict], scenarios: list[str], students: tuple[str, ...],
                teacher: str) -> tuple[list[dict], dict[str, dict]]:
    """One unit per test task a student failed alone. A task with no built skill counts as not fixed."""
    latest = {(row["condition"], row["model_key"], row["task_id"]): row for row in pilot.latest_repeats(runs)}
    functions = final_builds(teach, "compile", "shared")
    units, strength = [], {}
    for student in students:
        passed_v1 = sum(bool(latest[("small_alone", student, f"{scenario}_1")]["success"]) for scenario in scenarios)
        rate = passed_v1 / len(scenarios)
        strength[student] = {"v1_passed": passed_v1, "v1_tasks": len(scenarios), "v1_pass_rate": rate,
                             "tier": tier_of(rate)}
        notes = final_builds(teach, "coach_checked", student)

        def fixed(condition: str, build: dict | None, task: str) -> bool:
            if not build or build["status"] != "built":
                return False
            return bool(latest[(condition, student, task)]["success"])

        for scenario in scenarios:
            student_v1 = latest[("small_alone", student, f"{scenario}_1")]["success"]
            teacher_v1 = latest[("cloud_alone", teacher, f"{scenario}_1")]["success"]
            for version in TEST_VERSIONS:
                task = f"{scenario}_{version}"
                if latest[("small_alone", student, task)]["success"]:
                    continue
                units.append({"student": student, "scenario": scenario, "task": task,
                              "tier": strength[student]["tier"],
                              "note_eligible": (not student_v1) and bool(teacher_v1),
                              "note_fixed": fixed("coach_checked", notes.get(scenario), task),
                              "function_fixed": fixed("compile", functions.get(scenario), task),
                              "control_ran": ("generic_note", student, task) in latest,
                              "control_fixed": bool(latest.get(("generic_note", student, task), {}).get("success"))})
    return units, strength


def cells(units: list[dict], scenarios: list[str], students: tuple[str, ...]) -> list[list[list[int]]]:
    """scenario -> student -> [units, fixed by note, fixed by function, fixed by the generic note]."""
    table = [[[0, 0, 0, 0] for _ in students] for _ in scenarios]
    scenario_index = {name: index for index, name in enumerate(scenarios)}
    student_index = {name: index for index, name in enumerate(students)}
    for unit in units:
        cell = table[scenario_index[unit["scenario"]]][student_index[unit["student"]]]
        cell[0] += 1
        cell[1] += int(unit["note_fixed"])
        cell[2] += int(unit["function_fixed"])
        cell[3] += int(unit.get("control_fixed", False))
    return table


def tier_rate(totals: list[list[int]], members: list[int], column: int, equal_students: bool) -> float | None:
    if equal_students:
        # A mean of per-student rates is undefined as soon as one student of the tier has no task. PROTOCOL.md:
        # "Resamples where a rate is undefined are dropped and counted." Averaging over the students who are left
        # would change which students the tier stands for from one resample to the next.
        if not members or any(not totals[index][0] for index in members):
            return None
        return sum(totals[index][column] / totals[index][0] for index in members) / len(members)
    n = sum(totals[index][0] for index in members)
    return sum(totals[index][column] for index in members) / n if n else None


def statistics_of(totals: list[list[int]], lower: list[int], upper: list[int], equal_students: bool) -> dict:
    note_low, note_up = (tier_rate(totals, group, 1, equal_students) for group in (lower, upper))
    func_low, func_up = (tier_rate(totals, group, 2, equal_students) for group in (lower, upper))
    d = None if note_low is None or note_up is None else note_up - note_low
    h2 = None if None in (note_low, note_up, func_low, func_up) else (func_low - note_low) - (func_up - note_up)
    control_low, control_up = (tier_rate(totals, group, 3, equal_students) for group in (lower, upper))
    d_control = None if control_low is None or control_up is None else control_up - control_low
    return {"note_lower": note_low, "note_upper": note_up, "function_lower": func_low, "function_upper": func_up,
            "D": d, "H2": h2, "control_lower": control_low, "control_upper": control_up, "D_control": d_control,
            "D_net_of_control": None if d is None or d_control is None else d - d_control}


def percentile(ordered: list[float], fraction: float) -> float:
    position = (len(ordered) - 1) * fraction
    below = int(position)
    above = min(below + 1, len(ordered) - 1)
    return ordered[below] + (ordered[above] - ordered[below]) * (position - below)


def draws(n_scenarios: int, n_resamples: int = N_RESAMPLES, seed: int = SEED) -> list[list[int]]:
    """How many times each scenario appears in each resample. The same draws serve every estimate."""
    rng = random.Random(seed)
    result = []
    for _ in range(n_resamples):
        counts = [0] * n_scenarios
        for _ in range(n_scenarios):
            counts[rng.randrange(n_scenarios)] += 1
        result.append(counts)
    return result


def interval(values: list[float | None]) -> dict:
    defined = sorted(value for value in values if value is not None)
    if not defined:
        return {"low": None, "high": None, "n_undefined_resamples": len(values)}
    return {"low": percentile(defined, 0.025), "high": percentile(defined, 0.975),
            "n_undefined_resamples": len(values) - len(defined)}


def h1_label(d: float | None, low: float | None, high: float | None, function_lower: float | None,
             both_tiers: bool) -> str:
    if not both_tiers or d is None or low is None or high is None:
        return "INCONCLUSIVE"
    if low > 0 and function_lower is not None and function_lower >= FUNCTION_BAR:
        return "SUPPORTED"
    if d < SMALL_D and low <= 0 <= high:
        return "NOT SUPPORTED"
    return "INCONCLUSIVE"


def claim_label(label: str, net_low: float | None, n_missing: int) -> str:
    """What may be quoted as the thesis: H1 has to hold beyond what any general note does."""
    if label != "SUPPORTED":
        return label
    if n_missing:
        return "SUPPORTED, control not finished: do not quote"
    if net_low is not None and net_low > 0:
        return "SUPPORTED and beyond a generic note"
    return "SUPPORTED but not separated from a generic note"


def estimate(units: list[dict], scenarios: list[str], students: tuple[str, ...], strength: dict,
             resamples: list[list[int]], equal_students: bool = False, with_control: bool = False) -> dict:
    lower = [index for index, name in enumerate(students) if strength[name]["tier"] == "lower"]
    upper = [index for index, name in enumerate(students) if strength[name]["tier"] == "upper"]
    table = cells(units, scenarios, students)

    def totals_for(weights: list[int]) -> list[list[int]]:
        return [[sum(weights[s] * table[s][student][column] for s in range(len(scenarios))) for column in range(4)]
                for student in range(len(students))]

    observed = statistics_of(totals_for([1] * len(scenarios)), lower, upper, equal_students)
    boot = [statistics_of(totals_for(weights), lower, upper, equal_students) for weights in resamples]
    d_interval, h2_interval = interval([row["D"] for row in boot]), interval([row["H2"] for row in boot])
    both = bool(lower) and bool(upper)
    control_keys = ("control_lower", "control_upper", "D_control", "D_net_of_control")
    result = {**{key: value for key, value in observed.items() if key not in control_keys},
              "n_units": len(units), "lower_students": [students[index] for index in lower],
              "upper_students": [students[index] for index in upper], "D_interval_95": d_interval,
              "H2_interval_95": h2_interval,
              "label": h1_label(observed["D"], d_interval["low"], d_interval["high"], observed["function_lower"], both)}
    if with_control:
        missing = sum(1 for unit in units if not unit.get("control_ran"))
        net_interval = interval([row["D_net_of_control"] for row in boot])
        result["generic_note_control"] = {
            "n_units_without_a_control_run": missing,
            **({key: observed[key] for key in control_keys} if not missing else {key: None for key in control_keys}),
            "D_control_interval_95": interval([row["D_control"] for row in boot]) if not missing else None,
            "D_net_interval_95": net_interval if not missing else None}
        result["claim"] = claim_label(result["label"], None if missing else net_interval["low"], missing)
    return result


def per_student(runs: list[dict], teach: list[dict], units: list[dict], strength: dict, students: tuple[str, ...]) -> dict:
    latest = {(row["condition"], row["model_key"], row["task_id"]): row for row in pilot.latest_repeats(runs)}
    result = {}
    for student in students:
        mine = [unit for unit in units if unit["student"] == student]
        eligible = [unit for unit in mine if unit["note_eligible"]]
        harm = {}
        for form, (condition, _) in SKILL_ARMS.items():
            with_skill = [row for key, row in latest.items() if key[0] == condition and key[1] == student
                          and row["version"] in TEST_VERSIONS]
            passed_alone = [row for row in with_skill if latest[("small_alone", student, row["task_id"])]["success"]]
            harm[form] = {"passed_alone_and_ran_with_skill": len(passed_alone),
                          "failed_with_skill": sum(1 for row in passed_alone if not row["success"])}
        result[student] = {**strength[student], "failed_test_tasks": len(mine),
                           "fixed_by_note": sum(unit["note_fixed"] for unit in mine),
                           "fixed_by_function": sum(unit["function_fixed"] for unit in mine),
                           "note_eligible_failed_test_tasks": len(eligible),
                           "eligible_fixed_by_note": sum(unit["note_fixed"] for unit in eligible),
                           "eligible_fixed_by_function": sum(unit["function_fixed"] for unit in eligible),
                           "harm": harm}
    return result


def builds_report(teach: list[dict], students: tuple[str, ...]) -> dict:
    def one(kind: str, owner: str) -> dict:
        rows = [row for row in teach if row["kind"] == kind and row["small_model_key"] == owner]
        final = final_builds(teach, kind, owner)
        statuses = Counter(row["status"] for row in final.values())
        attempted = sum(count for status, count in statuses.items() if not status.startswith("skipped"))
        return {"final_status": dict(sorted(statuses.items())), "attempted": attempted, "built": statuses["built"],
                "cut_off": statuses["cut_off"], "cost_usd_all_rows_including_failed": round(
                    sum(row["cost_usd"] for row in rows), 6)}

    return {"function_shared": one("compile", "shared"),
            "note_by_student": {student: one("coach_checked", student) for student in students}}


def break_even(runs: list[dict], teach: list[dict], units: list[dict], students: tuple[str, ...], teacher: str) -> dict:
    """Uses of a skill at which build cost plus run cost equals renting, on the failed test tasks it fixed.

    Conditional on a fix: failed skill runs, failed builds and builds that fixed nothing are left out, so this is the
    payback of a skill that works. `break_even_including_failures` counts them.
    """
    latest = {(row["condition"], row["model_key"], row["task_id"]): row for row in pilot.latest_repeats(runs)}
    rows = []
    for student in students:
        for form, (condition, _) in SKILL_ARMS.items():
            flag = f"{form}_fixed"
            by_scenario: dict[str, list[str]] = defaultdict(list)
            for unit in units:
                if unit["student"] == student and unit[flag]:
                    by_scenario[unit["scenario"]].append(unit["task"])
            kind, owner = ("coach_checked", student) if form == "note" else ("compile", "shared")
            for scenario, tasks in sorted(by_scenario.items()):
                rent = [latest[("cloud_alone", teacher, task)] for task in tasks]
                if not all(row["success"] for row in rent):
                    continue
                run_cost = statistics.mean(latest[(condition, student, task)]["cost_usd"] for task in tasks)
                rent_cost = statistics.mean(row["cost_usd"] for row in rent)
                build = build_cost(teach, kind, owner, scenario)
                saving = rent_cost - run_cost
                rows.append({"student": student, "form": form, "scenario": scenario, "build_usd": round(build, 6),
                             "run_usd_per_task": round(run_cost, 6), "rent_usd_per_task": round(rent_cost, 6),
                             "uses_to_break_even": round(build / saving, 2) if saving > 0 else None})
    summary = {}
    for form in SKILL_ARMS:
        mine = [row for row in rows if row["form"] == form]
        finite = [row["uses_to_break_even"] for row in mine if row["uses_to_break_even"] is not None]
        summary[form] = {"n_student_scenarios": len(mine), "n_never_pays_back": len(mine) - len(finite),
                         "median_uses_to_break_even": statistics.median(finite) if finite else None}
    return {"definition": "build cost, all attempts / (mean rent cost - mean skill run cost) on fixed failed test tasks; "
                          "a function's build cost is charged in full to each student",
            "summary": summary, "rows": rows}


def break_even_including_failures(runs: list[dict], teach: list[dict], units: list[dict], students: tuple[str, ...],
                                  teacher: str) -> dict:
    """Added Nov 24, 2026, after review. Not part of the analysis fixed in PROTOCOL.md before the students ran.

    One row per student, form and scenario where a build was attempted and the student has a failed test task the
    teacher passed. Failed skill runs are paid for, and a task the skill does not fix is rented as well, at what the
    teacher's own run of that task cost.
    """
    latest = {(row["condition"], row["model_key"], row["task_id"]): row for row in pilot.latest_repeats(runs)}
    functions = final_builds(teach, "compile", "shared")
    rows = []
    for student in students:
        notes = final_builds(teach, "coach_checked", student)
        by_scenario: dict[str, list[dict]] = defaultdict(list)
        for unit in units:
            if unit["student"] == student and latest[("cloud_alone", teacher, unit["task"])]["success"]:
                by_scenario[unit["scenario"]].append(unit)
        for form, (condition, _) in SKILL_ARMS.items():
            kind, owner, builds = (("coach_checked", student, notes) if form == "note"
                                   else ("compile", "shared", functions))
            for scenario, mine in sorted(by_scenario.items()):
                build = builds.get(scenario)
                if build is None or build["status"].startswith("skipped"):
                    continue
                built = build["status"] == "built"
                n_fixed = sum(1 for unit in mine if unit[f"{form}_fixed"])
                rent = statistics.mean(latest[("cloud_alone", teacher, unit["task"])]["cost_usd"] for unit in mine)
                row = {"student": student, "form": form, "scenario": scenario,
                       "note_eligible": bool(mine[0]["note_eligible"]), "build_status": build["status"],
                       "n_failed_test_tasks": len(mine), "n_fixed": n_fixed,
                       "build_usd": round(build_cost(teach, kind, owner, scenario), 6),
                       "rent_usd_per_task": round(rent, 6), "run_usd_per_task": None, "cost_usd_per_use": None,
                       "uses_to_break_even": None}
                if built:  # a failed build has no skill to run, so it never pays back
                    run = statistics.mean(latest[(condition, student, unit["task"])]["cost_usd"] for unit in mine)
                    per_use = statistics.mean(
                        latest[(condition, student, unit["task"])]["cost_usd"]
                        + (0.0 if unit[f"{form}_fixed"] else latest[("cloud_alone", teacher, unit["task"])]["cost_usd"])
                        for unit in mine)
                    saving = rent - per_use
                    row.update(run_usd_per_task=round(run, 6), cost_usd_per_use=round(per_use, 6),
                               uses_to_break_even=round(row["build_usd"] / saving, 2) if saving > 0 else None)
                rows.append(row)

    def summary(chosen: list[dict]) -> dict:
        result = {}
        for form in SKILL_ARMS:
            mine = [row for row in chosen if row["form"] == form]
            finite = [row["uses_to_break_even"] for row in mine if row["uses_to_break_even"] is not None]
            result[form] = {"n_student_scenarios": len(mine),
                            "n_failed_builds": sum(1 for row in mine if row["build_status"] != "built"),
                            "n_built_with_no_fix": sum(1 for row in mine if row["build_status"] == "built"
                                                       and row["n_fixed"] == 0),
                            "n_never_pays_back": len(mine) - len(finite),
                            "median_uses_to_break_even": statistics.median(finite) if finite else None}
        return result

    return {"added": "Nov 24, 2026, after review; post hoc, not part of the analysis fixed before the students ran",
            "why": "break_even reads only the failed test tasks a skill fixed, so failed skill runs, failed builds and "
                   "builds that fixed nothing are left out of it; this block counts them",
            "definition": "per student, form and scenario with an attempted build, on the student's failed test tasks "
                          "that the teacher passed: cost per use = mean over those tasks of (skill run cost, failed "
                          "runs included, + that task's own rent cost if the skill did not fix it); uses to break "
                          "even = build cost, all attempts / (mean rent cost - cost per use), or never if that saving "
                          "is not positive; a failed build never pays back; a function's build cost is charged in "
                          "full to each student",
            "summary": summary(rows),
            "summary_note_eligible_scenarios_only": summary([row for row in rows if row["note_eligible"]]),
            "rows": rows}


def differences(earlier, now, path: str = "") -> list[dict]:
    """Every value of an earlier report that this one does not reproduce, with where it sits."""
    if isinstance(earlier, dict) and isinstance(now, dict):
        found = []
        for key, value in earlier.items():
            where = f"{path}.{key}" if path else str(key)
            found += differences(value, now[key], where) if key in now else [{"key": where, "earlier": value,
                                                                              "now": "(absent)"}]
        return found
    if isinstance(earlier, list) and isinstance(now, list) and len(earlier) == len(now):
        return [item for index, (a, b) in enumerate(zip(earlier, now)) for item in differences(a, b, f"{path}[{index}]")]
    same = type(earlier) is type(now) and earlier == now
    return [] if same else [{"key": path, "earlier": earlier, "now": now}]


def n_values(report) -> int:
    if isinstance(report, dict):
        return sum(n_values(value) for value in report.values())
    return sum(n_values(value) for value in report) if isinstance(report, list) else 1


def refusal_reasons() -> list[str]:
    """Why no result may be computed: a stage 1 run or build, or a generic-note control run, is not on file."""
    reasons = sweep.incomplete_reasons()
    if not reasons:
        reasons = [f"generic-note control: {reason}" for reason in sweep.control_incomplete_reasons()]
    return reasons


def function_failures(runs: list[dict], students: tuple[str, ...]) -> dict:
    result = {}
    for student in students:
        failed = [row for row in pilot.latest_repeats(runs) if row["condition"] == "compile"
                  and row["model_key"] == student and not row["success"]]
        result[student] = {f"{stop} / {kind}": count for (stop, kind), count in
                           sorted(Counter((row["stop_reason"], str(row["failure_type"])) for row in failed).items())}
    return result


RECOUNTED_FIELDS = ("requests", "input_tokens", "output_tokens", "cost_usd", "model_seconds")


def resources_in_raw(raw: dict) -> dict:
    """What a raw trajectory file says its run used, summed the way the run's row was. Empty if it holds no steps."""
    if "steps" not in raw:
        return {}
    parts = list(raw["steps"]) + ([raw["forecast"]] if raw.get("forecast") else []) + list(
        raw.get("unfinished_replies") or [])
    return {"requests": len(parts), "input_tokens": sum(part["input_tokens"] for part in parts),
            "output_tokens": sum(part["output_tokens"] for part in parts),
            "cost_usd": round(sum(part["cost_usd"] for part in parts), 6),
            "model_seconds": round(sum(part["seconds"] for part in parts), 2)}


def recount_from_raw(run_dir: Path, runs: list[dict]) -> dict:
    """Checks every run row against its raw trajectory file: the outcome and the resources the report sums.

    Every repeat is checked, not only the latest, because an earlier try's tokens, dollars and seconds are summed into
    the report (`latest_repeats`). The check can only see what the raw file holds. A reply that was charged but never
    stored as a step is in neither the row nor the raw file of runs made before Nov 24, 2026, so it cannot show up
    here; `ledger_vs_rows.py` measures that against the spend ledger.
    """
    problems, n_checked, n_files = [], 0, 0
    newest = {(row["condition"], row["model_key"], row["task_id"]): row["repeat"] for row in pilot.latest_repeats(runs)}
    tolerance = {"cost_usd": 1.5e-6, "model_seconds": 0.011}
    for row in runs:
        name = f"{row['condition']}__{row['model_key']}__{row['task_id']}__r{row['repeat']}.json"
        path = run_dir / "raw_large" / name
        if not path.exists():
            problems.append(f"missing raw file: {name}")
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        n_files += 1
        n_checked += int(newest[(row["condition"], row["model_key"], row["task_id"])] == row["repeat"])
        if bool(raw["evaluation"]["success"]) != bool(row["success"]):
            problems.append(f"success differs from raw: {name}")
        for field, in_raw in resources_in_raw(raw).items():
            if field in row and abs(row[field] - in_raw) > tolerance.get(field, 0):
                problems.append(f"{field} differs from raw: {name} (row {row[field]}, raw {in_raw})")
        if row["condition"] in ("coach_checked", "compile", "generic_note") and not raw.get("guidance"):
            problems.append(f"skill run without guidance: {name}")
        if row["condition"] == "compile" and not raw.get("preload_code"):
            problems.append(f"function run without the function: {name}")
    return {"n_checked": n_checked, "problems": problems, "n_raw_files_checked_every_repeat": n_files,
            "resource_fields_compared": list(RECOUNTED_FIELDS)}


def analyze(runs: list[dict], teach: list[dict], scenarios: list[str], students: tuple[str, ...], teacher: str,
            n_resamples: int = N_RESAMPLES) -> dict:
    units, strength = build_units(runs, teach, scenarios, students, teacher)
    resamples = draws(len(scenarios), n_resamples)
    eligible = [unit for unit in units if unit["note_eligible"]]
    return {
        "bootstrap": {"unit": "scenario", "resamples": n_resamples, "seed": SEED, "interval": "percentile, 2.5 to 97.5"},
        "primary_note_eligible": estimate(eligible, scenarios, students, strength, resamples, with_control=True),
        "secondary_as_first_written": estimate(units, scenarios, students, strength, resamples),
        "sensitivity_equal_weight_per_student": estimate(eligible, scenarios, students, strength, resamples,
                                                         equal_students=True),
        "per_student": per_student(runs, teach, units, strength, students),
        "builds": builds_report(teach, students),
        "by_arm": pilot.condition_table(runs),
        "break_even": break_even(runs, teach, units, students, teacher),
        "break_even_including_failures": break_even_including_failures(runs, teach, units, students, teacher),
        "function_run_failures": function_failures(runs, students),
        "n_rerun_rows": len(runs) - len(pilot.latest_repeats(runs)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-dir", default=str(REPO_ROOT / "results" / "pilot" / "stage1"))
    parser.add_argument("--scenarios", default=str(HERE / "scenarios.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--corrects", default=None, help="an earlier report of the same rows; every value of it that "
                                                         "this run does not reproduce is listed in the output")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    sweep.RUN_DIR = run_dir
    sweep.SCENARIO_FILE = Path(args.scenarios)
    reasons = refusal_reasons()
    if reasons:
        print("STATUS INCOMPLETE; no result computed: " + "; ".join(reasons))
        return 2
    runs, teach = read_jsonl(run_dir / "runs.jsonl"), read_jsonl(run_dir / "teach.jsonl")
    recount = recount_from_raw(run_dir, runs)
    if recount["problems"]:
        print(f"STATUS RECOUNT FAILED; no result computed: {len(recount['problems'])} problems, first: "
              f"{recount['problems'][0]}")
        return 3
    scenarios = [item["scenario_id"] for item in json.loads(Path(args.scenarios).read_text(encoding="utf-8"))["chosen"]]
    report = {"status": "COMPLETE", "raw_recount": recount,
              **analyze(runs, teach, scenarios, sweep.STUDENTS, sweep.TEACHER)}
    if args.corrects:
        earlier = json.loads(Path(args.corrects).read_text(encoding="utf-8"))
        changed = differences(earlier, report)
        report[f"corrections_to_{Path(args.corrects).stem}"] = {
            "earlier_report": Path(args.corrects).name,
            "what": "every value of the earlier report that this run does not reproduce; PROTOCOL.md says why",
            "n_values_compared": n_values(earlier), "n_values_changed": len(changed),
            "top_level_keys_added": [key for key in report if key not in earlier], "changed": changed}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(f"STATUS COMPLETE; written, not printed: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
