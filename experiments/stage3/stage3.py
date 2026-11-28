"""Stage 3 (experiments/stage3/PROTOCOL.md): part A's pipeline with an OpenAI teacher and the same students.

    stage3.py preflight [--ping]                  checks the setup before anything is paid; --ping also sends one tiny
                                                  request to the teacher and each student (well under a cent)
    stage3.py students                            the four students
    stage3.py source --model M                    the run folder that holds that student's solo runs
    stage3.py ready --model T | --functions       why the teacher's runs or the function builds are not finished
    stage3.py control --model M                   the generic-note tasks (the student's units); refuses until ready
    stage3.py retry --condition C --model M       lines "<repeat> <tasks>": runs missing, or whose latest run ended in
                                                  an infrastructure error or a spend stop (at most two redos)
    stage3.py calibration-retry                   lines "<repeat> <tasks>" for the teacher's 3 calibration runs
    stage3.py project                             after those runs: stops if the projected OpenAI spend passes the
                                                  stop or the output limit cuts the teacher's replies; when it passes,
                                                  the decision is kept in results/pilot/stage3/calibration.json
    stage3.py verify-result --out FILE            whether an existing result file is whole
    stage3.py check                               why stage 3 is not finished; prints nothing when it is
    stage3.py reference --out FILE                the stage 3 measures on the GLM-5.3-Flash runs, before stage 3 runs
    stage3.py analyze --out FILE                  writes the result without printing it; refuses while `check` prints
    stage3.py privacy                             lists result files that hold this computer's home folder
    stage3.py log-row --status S --start T        appends the run's row to LOG.md

The students' solo runs are not run again: they are read from stage 1 (the three weak students) and part A
(Nemotron-3-Super). Everything that depends on the teacher is new: its own runs, the functions, the notes, and the
students' runs with that help. Units and break-even rows come from the stage 1 analysis code and the accuracy contrast
and its label from part A's, so every stage counts the same way. Rows are read, never written (the ping writes only
ledger rows). No task text is read or written here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT, default_appworld_python
from loopy.eval.runlog import ledger_total, read_jsonl
from loopy.skills.teach import skip_still_holds

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
RESULTS = REPO_ROOT / "results" / "pilot"
RUN_DIR = RESULTS / "stage3"
SCENARIO_FILE = REPO_ROOT / "experiments" / "stage2" / "scenarios_part_a.json"
LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"
TEACHER = "gpt-6.2-sol"
FLASH = "glm-5.3-flash"
WEAK = ("gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash")
MIDDLE = ("nemotron-3-super-120b",)
STUDENTS = WEAK + MIDDLE
SOURCE = {"gpt-oss-120b": "stage1", "gemma-3-27b": "stage1", "minimax-m3.1-flash": "stage1",
          "nemotron-3-super-120b": "stage2a"}
ARMS = ("coach_checked", "compile", "generic_note")  # the student arms stage 3 runs; solo runs are reused
NOT_A_RESULT = ("model_error", "cost_cap")
TEST_VERSIONS = (2, 3)
MAX_REPEAT = 3  # the first run and at most two redos
K_PRIMARY, K_CURVE = 10, (1, 3, 10, 30)
CALIBRATION_RUNS = 3
CALIBRATION_FILE = RUN_DIR / "calibration.json"
# OpenAI spend of the whole stage, in teacher solo runs: 69 solo runs, the function builds (2.6 solo runs each, 23
# scenarios) and the note builds (0.78 each, about 68). The ratios are GLM-5.3-Flash's own costs in stage 1.
RUN_EQUIVALENTS = 69 + 2.6 * 23 + 0.78 * 68
MAX_CUT_OFF_SHARE = 0.20
RESAMPLES, SEED = 10_000, 123


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


s1 = _load("stage1_analysis_for_stage3", REPO_ROOT / "experiments" / "stage1" / "analyze_stage1.py")
g2 = _load("part_a_gate2_for_stage3", REPO_ROOT / "experiments" / "stage2" / "part_a_gate2.py")


# ---------------------------------------------------------------- rows and task lists

def scenario_ids() -> list[str]:
    return [item["scenario_id"] for item in json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))["chosen"]]


def all_tasks(scenarios: list[str]) -> list[str]:
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


def solo_rows(scenarios: list[str], students: tuple[str, ...] = STUDENTS) -> list[dict]:
    """Every solo run of the students on these scenarios, from the run folders that hold them (all repeats)."""
    wanted = set(all_tasks(scenarios))
    out = []
    for folder in sorted({SOURCE[student] for student in students}):
        out += [row for row in read_jsonl(RESULTS / folder / "runs.jsonl") if row["condition"] == "small_alone"
                and row["model_key"] in students and SOURCE[row["model_key"]] == folder and row["task_id"] in wanted]
    return out


def final_builds(teach: list[dict], kind: str, owner: str, teacher: str | None = None) -> dict[str, dict]:
    teacher = teacher or TEACHER  # read when called: `measures_for` swaps TEACHER to compute the reference
    return {row["scenario_id"]: row for row in teach if row["kind"] == kind and row["small_model_key"] == owner
            and row["teacher_model_key"] == teacher}


def built(teach: list[dict], kind: str, owner: str) -> set[str]:
    return {scenario for scenario, row in final_builds(teach, kind, owner).items() if row["status"] == "built"}


def arm_reasons(rows: list[dict], condition: str, model: str, scenarios: list[str]) -> list[str]:
    """Why an alone arm is not finished: the teacher's runs here, or a student's reused solo runs."""
    latest = latest_of(rows)
    wanted = all_tasks(scenarios)
    missing = [task for task in wanted if (condition, model, task) not in latest]
    bad = [task for task in wanted if (condition, model, task) in latest
           and latest[(condition, model, task)]["stop_reason"] in NOT_A_RESULT]
    reasons = []
    if missing:
        reasons.append(f"{model}: {len(missing)} of {len(wanted)} {condition} runs missing")
    if bad:
        reasons.append(f"{model}: {len(bad)} {condition} runs ended in an infrastructure error or a spend stop")
    return reasons


def build_reasons(rows: list[dict], teach: list[dict], kind: str, owner: str, scenarios: list[str]) -> list[str]:
    """Why the builds of one kind for one owner ("shared" for functions) are not all decided."""
    latest = latest_of(rows)
    builds = final_builds(teach, kind, owner)
    who = "functions" if owner == "shared" else f"{owner} notes"
    reasons = []
    if set(scenarios) - set(builds):
        reasons.append(f"{who}: {len(set(scenarios) - set(builds))} of {len(scenarios)} decisions missing")
    for scenario, row in sorted(builds.items()):
        if scenario not in scenarios:
            reasons.append(f"{who}: a decision for {scenario}, outside the scenario file")
        if row["status"] == "cost_cap":
            reasons.append(f"{who}: the build for {scenario} was stopped by a spending stop")
        if row["learn_task_id"] != f"{scenario}_1":
            reasons.append(f"{who}: the build for {scenario} was not learned from version 1")
        teacher_row = latest.get(("cloud_alone", TEACHER, f"{scenario}_1"))
        student_row = latest.get(("small_alone", owner, f"{scenario}_1")) if owner != "shared" else None
        if row["status"].startswith("skipped") and teacher_row is not None and not skip_still_holds(
                row["status"], None if student_row is None else bool(student_row["success"]),
                bool(teacher_row["success"])):
            reasons.append(f"{who}: the skip recorded for {scenario} no longer matches the latest runs")
    return reasons


def control_tasks(rows: list[dict], student: str, scenarios: list[str]) -> list[str]:
    """Test tasks the student failed alone, in scenarios where it failed version 1 and the teacher passed it."""
    latest = latest_of(rows)
    tasks = []
    for scenario in scenarios:
        own = latest[("small_alone", student, f"{scenario}_1")]
        if own["success"] or not latest[("cloud_alone", TEACHER, f"{scenario}_1")]["success"]:
            continue
        tasks += [f"{scenario}_{version}" for version in TEST_VERSIONS
                  if not latest[("small_alone", student, f"{scenario}_{version}")]["success"]]
    return tasks


def wanted_tasks(condition: str, model: str, rows: list[dict], teach: list[dict], scenarios: list[str]) -> list[str]:
    if condition == "cloud_alone":
        return all_tasks(scenarios)
    if condition == "coach_checked":
        return test_tasks(sorted(built(teach, "coach_checked", model)))
    if condition == "compile":
        return test_tasks(sorted(built(teach, "compile", "shared")))
    return control_tasks(rows, model, scenarios)


def retry_lines(condition: str, model: str, rows: list[dict], teach: list[dict], scenarios: list[str]) -> list[str]:
    """`rows` are this stage's rows plus the reused solo runs; only this stage's runs are ever redone."""
    latest = latest_of(rows)
    by_repeat: dict[int, list[str]] = defaultdict(list)
    for task in wanted_tasks(condition, model, rows, teach, scenarios):
        row = latest.get((condition, model, task))
        if row is None:
            by_repeat[1].append(task)
        elif row["stop_reason"] in NOT_A_RESULT and row["repeat"] < MAX_REPEAT:
            by_repeat[row["repeat"] + 1].append(task)
    return [f"{repeat} {','.join(sorted(found))}" for repeat, found in sorted(by_repeat.items())]


def incomplete_reasons(own: list[dict], solo: list[dict], teach: list[dict], scenarios: list[str]) -> list[str]:
    """`own` are the rows of this stage's folder; `solo` the reused solo runs."""
    rows = own + solo
    reasons = []
    for student in STUDENTS:
        reasons += arm_reasons(solo, "small_alone", student, scenarios)
    reasons += arm_reasons(own, "cloud_alone", TEACHER, scenarios)
    if reasons:
        return reasons  # every other part depends on the teacher's runs and the solo runs
    reasons += build_reasons(rows, teach, "compile", "shared", scenarios)
    latest = latest_of(own)
    allowed = {("cloud_alone", TEACHER, task) for task in all_tasks(scenarios)}
    for student in STUDENTS:
        reasons += build_reasons(rows, teach, "coach_checked", student, scenarios)
        for condition in ARMS:
            wanted = set(wanted_tasks(condition, student, rows, teach, scenarios))
            allowed |= {(condition, student, task) for task in wanted}
            have = {task for cond, model, task in latest if cond == condition and model == student}
            bad = {task for task in wanted & have if latest[(condition, student, task)]["stop_reason"] in NOT_A_RESULT}
            if wanted - have:
                reasons.append(f"{student}: {len(wanted - have)} of {len(wanted)} {condition} runs missing")
            if bad:
                reasons.append(f"{student}: {len(bad)} {condition} runs ended in an infrastructure error or a spend stop")
    strays = sorted(key for key in latest if key not in allowed)
    if strays and not reasons:
        reasons.append(f"{len(strays)} runs in the stage 3 folder that are not part of stage 3 "
                       f"({', '.join(':'.join(key) for key in strays[:5])})")
    by_key: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in own:
        by_key[(row["condition"], row["model_key"], row["task_id"])].append(row)
    unearned = [key for key, found in by_key.items()
                if any(row["stop_reason"] not in NOT_A_RESULT for row in sorted(found, key=lambda r: r["repeat"])[:-1])]
    if unearned:
        reasons.append(f"{len(unearned)} tasks were run again after a run that counted")
    too_many = [key for key, found in by_key.items() if max(row["repeat"] for row in found) > MAX_REPEAT]
    if too_many:
        reasons.append(f"{len(too_many)} tasks have more than {MAX_REPEAT} runs")
    if ({row["small_model_key"] for row in teach} - set(STUDENTS) - {"shared"}
            or any(row["teacher_model_key"] != TEACHER for row in teach)):
        reasons.append("builds on file for a student or teacher that stage 3 does not use")
    return reasons


# ---------------------------------------------------------------- the measures fixed in the protocol

def cost_of(row: dict, uses: int) -> float:
    """Build cost plus `uses` uses. A failed build has nothing to run, so every use is rented."""
    per_use = row["cost_usd_per_use"] if row["build_status"] == "built" else row["rent_usd_per_task"]
    return row["build_usd"] + uses * per_use


def pairs_of(break_even_rows: list[dict], who: tuple[str, ...]) -> list[dict]:
    """One pair per student and note-eligible scenario that has both a note row and a function row."""
    by_key: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for row in break_even_rows:
        if row["student"] in who and row["note_eligible"]:
            by_key[(row["student"], row["scenario"])][row["form"]] = row
    return [{"student": student, "scenario": scenario, "note": forms["note"], "function": forms["function"]}
            for (student, scenario), forms in sorted(by_key.items()) if {"note", "function"} <= set(forms)]


def note_cheaper_share(pairs: list[dict], uses: int) -> float | None:
    if not pairs:
        return None
    return sum(cost_of(pair["note"], uses) < cost_of(pair["function"], uses) for pair in pairs) / len(pairs)


def share_interval(pairs: list[dict], scenarios: list[str], uses: int = K_PRIMARY, resamples: int = RESAMPLES,
                   seed: int = SEED) -> dict:
    by_scenario: dict[str, list[dict]] = defaultdict(list)
    for pair in pairs:
        by_scenario[pair["scenario"]].append(pair)
    generator, values, undefined = random.Random(seed), [], 0
    for _ in range(resamples):
        drawn = [pair for s in generator.choices(scenarios, k=len(scenarios)) for pair in by_scenario[s]]
        value = note_cheaper_share(drawn, uses)
        if value is None:
            undefined += 1
        else:
            values.append(value)
    values.sort()
    return {"low": g2.percentile(values, 0.025) if values else None,
            "high": g2.percentile(values, 0.975) if values else None,
            "n_undefined_resamples": undefined, "resamples": resamples, "seed": seed, "uses": uses}


def buy_label(point: float | None, interval: dict) -> str:
    if point is None or interval["low"] is None:
        return "UNDECIDED"
    if interval["low"] > 0.5:
        return "NOTE IS THE BETTER BUY"
    if interval["high"] < 0.5:
        return "FUNCTION IS THE BETTER BUY"
    return "UNDECIDED"


def cost_measures(runs: list[dict], teach: list[dict], scenarios: list[str], who: tuple[str, ...],
                  teacher: str) -> dict:
    units, strength = s1.build_units(runs, teach, scenarios, who, teacher)
    rows = s1.break_even_including_failures(runs, teach, units, who, teacher)["rows"]
    pairs = pairs_of(rows, who)
    point = note_cheaper_share(pairs, K_PRIMARY)
    interval = share_interval(pairs, scenarios)

    def pays_back(form: str) -> dict:
        mine = [row for row in rows if row["form"] == form and row["note_eligible"]]
        finite = [row["uses_to_break_even"] for row in mine if row["uses_to_break_even"] is not None]
        return {"student_scenarios": len(mine), "pay_back": len(finite),
                "median_uses_to_break_even": statistics.median(finite) if finite else None}

    def saved(form: str, uses: int) -> float | None:
        """Share of the cost of renting every use that this form saves, over the pairs, failed builds included."""
        rent = sum(uses * pair[form]["rent_usd_per_task"] for pair in pairs)
        return 1 - sum(cost_of(pair[form], uses) for pair in pairs) / rent if rent else None

    return {"students": list(who), "n_scenarios": len(scenarios), "n_pairs": len(pairs),
            "share_of_rent_saved_by_uses": {form: {str(k): saved(form, k) for k in K_CURVE}
                                            for form in ("note", "function")},
            "note_cheaper_share_by_uses": {str(k): note_cheaper_share(pairs, k) for k in K_CURVE},
            "primary_uses": K_PRIMARY, "note_cheaper_share": point, "interval_95": interval,
            "label": buy_label(point, interval),
            "beats_renting_note_eligible": {"note": pays_back("note"), "function": pays_back("function")},
            "v1_pass_rate_alone": {student: strength[student]["v1_pass_rate"] for student in who}}


def billed(runs: list[dict], teach: list[dict], price_in: float, price_cached: float | None) -> tuple[list, list]:
    """Copies of the rows with the teacher's runs and builds at what the provider bills for cached input."""
    if price_cached is None:
        return runs, teach
    cut = (price_in - price_cached) / 1e6
    runs = [{**row, "cost_usd": row["cost_usd"] - cut * row.get("cached_input_tokens", 0)}
            if row["model_key"] == TEACHER else row for row in runs]
    teach = [{**row, "cost_usd": row["cost_usd"] - cut * (row.get("teacher_cached_input_tokens", 0)
                                                          if row["kind"] == "coach_checked"
                                                          else row.get("cached_input_tokens", 0))}
             for row in teach]
    return runs, teach


def student_table(units: list[dict], strength: dict, latest: dict, teach: list[dict], who: tuple[str, ...],
                  scenarios: list[str]) -> dict:
    functions = built(teach, "compile", "shared")
    out = {}
    for student in who:
        mine = [unit for unit in units if unit["student"] == student and unit["note_eligible"]]
        notes = built(teach, "coach_checked", student)
        passed = [task for task in test_tasks(scenarios) if latest[("small_alone", student, task)]["success"]]
        with_note = [task for task in passed if task.rsplit("_", 1)[0] in notes]
        with_function = [task for task in passed if task.rsplit("_", 1)[0] in functions]
        out[student] = {
            "v1_passed_alone": strength[student]["v1_passed"], "v1_pass_rate_alone": strength[student]["v1_pass_rate"],
            "units": len(mine), "note_fixed": sum(u["note_fixed"] for u in mine),
            "function_fixed": sum(u["function_fixed"] for u in mine),
            "control_fixed": sum(u["control_fixed"] for u in mine),
            "harm": {"test_tasks_passed_alone": len(passed),
                     "broken_by_note": sum(not latest[("coach_checked", student, t)]["success"] for t in with_note),
                     "of_those_with_a_note": len(with_note),
                     "broken_by_function": sum(not latest[("compile", student, t)]["success"] for t in with_function),
                     "of_those_with_a_function": len(with_function)}}
    return out


def measures(runs: list[dict], teach: list[dict], scenarios: list[str], teacher: str) -> dict:
    """Everything the protocol fixes, for one teacher's rows: the cost question and the accuracy contrast."""
    latest = latest_of(runs)
    weak_units, weak_strength = s1.build_units(runs, teach, scenarios, WEAK, teacher)
    middle_units, middle_strength = s1.build_units(runs, teach, scenarios, MIDDLE, teacher)
    weak = [unit for unit in weak_units if unit["note_eligible"]]
    mid = [unit for unit in middle_units if unit["note_eligible"]]
    point = g2.contrasts(mid, weak)
    boot = g2.bootstrap(mid, weak, scenarios)
    label, quotable = g2.label_for(point, boot["intervals_95"])
    return {
        "cost_question": {"all_four": cost_measures(runs, teach, scenarios, STUDENTS, teacher),
                          "weak": cost_measures(runs, teach, scenarios, WEAK, teacher),
                          "middle": cost_measures(runs, teach, scenarios, MIDDLE, teacher)},
        "accuracy": {"label": label, "quotable_as_thesis": quotable, "point": point, "bootstrap": boot,
                     "middle_pooled": g2.rates(mid), "weak_pooled": g2.rates(weak)},
        "per_student": {**student_table(weak_units, weak_strength, latest, teach, WEAK, scenarios),
                        **student_table(middle_units, middle_strength, latest, teach, MIDDLE, scenarios)},
        "teacher_alone": {"passed": sum(bool(latest[("cloud_alone", teacher, t)]["success"]) for t in all_tasks(scenarios)),
                          "tasks": len(all_tasks(scenarios)),
                          "v1_passed": sum(bool(latest[("cloud_alone", teacher, f"{s}_1")]["success"]) for s in scenarios),
                          "mean_cost_usd_all_repeats": round(statistics.mean(
                              sum(row["cost_usd"] for row in runs if row["condition"] == "cloud_alone"
                                  and row["model_key"] == teacher and row["task_id"] == t)
                              for t in all_tasks(scenarios)), 6)}}


def reference_rows(scenarios: list[str]) -> tuple[list[dict], list[dict]]:
    """The GLM-5.3-Flash runs of the same four students on the same scenarios (stage 1 and part A)."""
    wanted = set(all_tasks(scenarios))
    stage1, stage2a = read_jsonl(RESULTS / "stage1" / "runs.jsonl"), read_jsonl(RESULTS / "stage2a" / "runs.jsonl")
    runs = [row for row in stage1 if row["task_id"] in wanted and (row["model_key"] in WEAK or row["model_key"] == FLASH)]
    runs += [row for row in stage2a if row["task_id"] in wanted and row["model_key"] in MIDDLE]
    teach = [row for row in read_jsonl(RESULTS / "stage1" / "teach.jsonl")
             if row["scenario_id"] in scenarios and (row["kind"] == "compile" or row["small_model_key"] in WEAK)]
    teach += [row for row in read_jsonl(RESULTS / "stage2a" / "teach.jsonl") if row["small_model_key"] in MIDDLE]
    return runs, teach


def reference() -> dict:
    scenarios = scenario_ids()
    runs, teach = reference_rows(scenarios)
    return {"teacher": FLASH, "n_scenarios": len(scenarios), **measures_for(runs, teach, scenarios, FLASH)}


def measures_for(runs: list[dict], teach: list[dict], scenarios: list[str], teacher: str) -> dict:
    global TEACHER
    saved, TEACHER = TEACHER, teacher  # the helpers above read the teacher's builds by TEACHER
    try:
        return measures(runs, teach, scenarios, teacher)
    finally:
        TEACHER = saved


def analyze(own: list[dict], solo: list[dict], teach: list[dict], scenarios: list[str], config: dict) -> dict:
    runs = own + solo
    price = config["models"][TEACHER]
    runs_b, teach_b = billed(runs, teach, price["usd_per_mtok_in"], price.get("usd_per_mtok_cached_in"))
    latest = latest_of(own)
    ref_runs, ref_teach = reference_rows(scenarios)
    return {
        "teacher": TEACHER, "teacher_model_name": price["name"], "n_scenarios": len(scenarios),
        "config": {"sha256": hashlib.sha256(CONFIG.read_bytes()).hexdigest(), "teacher_entry": price,
                   "teacher_prices_checked_on": config.get("teacher_prices_checked_on")},
        "list_price": measures(runs, teach, scenarios, TEACHER),
        "billed_with_cached_input": {"cost_question": measures(runs_b, teach_b, scenarios, TEACHER)["cost_question"],
                                     "cached_price_per_mtok": price.get("usd_per_mtok_cached_in")},
        "reference_glm_5_3_flash_list_price": measures_for(ref_runs, ref_teach, scenarios, FLASH),
        "functions": dict(Counter(row["status"] for row in final_builds(teach, "compile", "shared").values())),
        "notes": {student: dict(Counter(row["status"] for row in final_builds(teach, "coach_checked", student).values()))
                  for student in STUDENTS},
        "cost_and_steps_by_arm": g2.arm_costs(latest_of(runs), STUDENTS),
        "teacher_cached_input_share": (sum(r.get("cached_input_tokens", 0) for r in own if r["model_key"] == TEACHER)
                                       / max(1, sum(r["input_tokens"] for r in own if r["model_key"] == TEACHER))),
        "run_facts": {"rows": len(own), "redone": sum(1 for row in own if row["repeat"] > 1),
                      "commits": sorted({row["git_commit"] for row in own}),
                      "cost_usd_on_rows_list_price": round(sum(row["cost_usd"] for row in own), 6),
                      "build_cost_usd_list_price": round(sum(row["cost_usd"] for row in teach), 6),
                      "first_started": min(row["started"] for row in own),
                      "last_finished": max(row["finished"] for row in own)},
    }


# ---------------------------------------------------------------- setup checks and the log

def raw_solo_files(scenarios: list[str]) -> list[Path]:
    """The trajectory of each student's latest solo run on version 1: what the note builder reads."""
    latest = latest_of(solo_rows(scenarios))
    files = []
    for student in STUDENTS:
        for scenario in scenarios:
            row = latest.get(("small_alone", student, f"{scenario}_1"))
            if row:
                files.append(RESULTS / SOURCE[student] / "raw_large" /
                             f"small_alone__{student}__{scenario}_1__r{row['repeat']}.json")
    return files


def preflight(ping: bool) -> list[str]:
    from loopy.agent.llm import ModelSpec, PydanticAIChat, load_env_file
    from loopy.agent.react import Budget

    problems = []
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    models, scenarios = config["models"], scenario_ids()
    teacher = models.get(TEACHER, {})
    if teacher.get("role") != "cloud":
        problems.append(f"the config has no cloud entry for {TEACHER}")
    if not config.get("teacher_prices_checked_on"):
        problems.append("check the teacher's model id and prices on OpenAI's pricing page, put them in "
                        "experiments/stage3/config.json, and set teacher_prices_checked_on to today's date")
    problems += [f"the config has no student entry for {s}" for s in STUDENTS if models.get(s, {}).get("role") != "small"]
    load_env_file(REPO_ROOT / ".env")
    for key in sorted({models[m].get("api_key_env") for m in (TEACHER, *STUDENTS) if m in models} - {None}):
        if not os.environ.get(key):
            problems.append(f"{key} is not set: put it in .env (copy .env.example)")
    if not default_appworld_python().exists():
        problems.append(f"no AppWorld environment at {default_appworld_python()}: see 'Experiments on AppWorld' "
                        "in README.md")
    if not (REPO_ROOT / "data").exists():
        problems.append("no AppWorld data folder: run `.venv-appworld/bin/appworld download data --root .`")
    for student in STUDENTS:
        problems += [f"solo runs: {reason}" for reason in arm_reasons(solo_rows(scenarios), "small_alone", student,
                                                                       scenarios)]
    missing = [path for path in raw_solo_files(scenarios) if not path.exists()]
    if missing:
        problems.append(f"{len(missing)} solo trajectories missing (first: {missing[0].relative_to(REPO_ROOT)}); "
                        "unzip the file Alfredo sent at the repository root")
    left = {}
    for provider, cap in config["ledger_caps_usd"].items():
        total = ledger_total(LEDGER, provider)
        left[provider] = cap - (config.get("ledger_reserve_usd") or {}).get(provider, 0.0) - total
        print(f"{provider}: ledger ${total:.2f}, hard stop ${cap:.2f}; new requests stop when ${max(left[provider], 0):.2f} "
              "more is spent there (list prices)")
        if left[provider] <= 0:
            print(f"  warning: nothing is left under the {provider} stop; work on that provider will not run")
    for key in (TEACHER, *STUDENTS):
        spec = ModelSpec.from_dict(key, models[key])
        sent = sent_settings(spec)
        print(f"  {key} is sent: {sent}")
        if spec.temperature is not None and "temperature" not in sent:
            problems.append(f"the library does not send temperature to {key}, so it would run at the provider's "
                            f"default while every row says {spec.temperature}. For the teacher the protocol allows "
                            "one change: \"temperature\": null in experiments/stage3/config.json")
    if ping and not problems:
        for key in (TEACHER, *STUDENTS):
            spec = ModelSpec.from_dict(key, models[key])
            if left.get(spec.provider, 1.0) <= 0:
                print(f"  {key}: not asked, its provider's stop is reached")
                continue
            budget = Budget(max_usd=0.05, ledger=LEDGER, provider=spec.provider, run_name="stage3_ping",
                            note=f"ping {key}", ledger_cap=config["ledger_caps_usd"].get(spec.provider))
            try:
                budget.check()
                reply = PydanticAIChat(spec, retries=2).complete([{"role": "user", "content": "Reply with the word ok."}])
                budget.add(spec.cost_usd(reply.input_tokens, reply.output_tokens))
                print(f"  {key}: answers with temperature {spec.temperature}, seed {spec.seed}, max_tokens "
                      f"{spec.max_tokens} ({reply.model_id})")
            except Exception as error:
                text = f"{type(error).__name__}: {error}"
                hint = (" The protocol's fallback: set \"temperature\": null for it in experiments/stage3/config.json "
                        "(it then runs at the provider's default) and run preflight again."
                        if "temperature" in text.lower() else "")
                problems.append(f"{key} did not answer: {text[:240]}{hint}")
    return problems


def sent_settings(spec) -> dict:
    """The settings the installed library would send for this model, read from one request to a stand-in server.

    Nothing leaves this computer. The library drops settings a model cannot take (an always-reasoning OpenAI model gets
    no temperature), so this is what the provider would actually receive.
    """
    try:
        import httpx2 as httpx  # the HTTP client of the installed OpenAI SDK
    except ImportError:
        import httpx
    import warnings
    from loopy.agent.llm import PydanticAIChat
    from pydantic_ai.direct import model_request_sync
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    seen: dict = {}

    def answer(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "stand-in", "object": "chat.completion", "created": 0, "model": spec.name,
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "ok"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})

    provider = OpenAIProvider(base_url=spec.base_url, api_key="stand-in",
                              http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    settings = PydanticAIChat.settings(type("Stand", (), {"spec": spec})())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model_request_sync(OpenAIChatModel(spec.name, provider=provider),
                           [ModelRequest(parts=[UserPromptPart(content="ok")])], model_settings=settings)
    return {key: seen[key] for key in ("temperature", "seed", "max_completion_tokens", "max_tokens") if key in seen}


def privacy_hits() -> list[str]:
    """Result files that would publish this computer's home folder, in any of the spellings a log can hold."""
    home = str(Path.home())
    forms = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    files = [path for path in RUN_DIR.glob("*") if path.is_file() and not path.name.endswith(".lock")]
    files += [LEDGER, REPO_ROOT / "LOG.md"]
    return [str(path.relative_to(REPO_ROOT)) for path in files
            if path.exists() and any(form and form in path.read_text(encoding="utf-8", errors="replace")
                                     for form in forms)]


def log_row(status: str, start: str) -> str:
    def git(*arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()

    rows = read_jsonl(RUN_DIR / "runs.jsonl")
    spent = sum(row["usd"] for row in read_jsonl(LEDGER) if row.get("run") in ("stage3", "stage3_ping"))
    end = time.strftime("%Y-%m-%d %H:%M:%S")
    row = (f"| {start[:10]} | {start[11:16]} to {end[11:16]} | {git('config', 'user.name') or 'unknown'} | "
           f"`bash experiments/stage3/run_stage3.sh` on commit {git('rev-parse', '--short', 'HEAD')} (seed 123) | "
           f"`results/pilot/stage3/` | {status}. {len(rows)} runs on file; ${spent:.2f} at list prices on the ledger "
           f"for stage 3. Row written by the runner. |\n")
    with open(REPO_ROOT / "LOG.md", "a", encoding="utf-8", newline="\n") as handle:
        handle.write(row)
    return row


def write_once(path: Path, report: dict) -> None:
    """The file appears whole or not at all, and an existing file is never replaced.

    The text goes to a temporary file first, which is then linked to its name in one step: an error, a full disk or a
    hard stop can leave a stray temporary file, never a partial result under the real name.
    """
    text = json.dumps(report, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temporary, path)  # fails if the name exists; never replaces it
    finally:
        temporary.unlink()


def result_is_whole(path: Path) -> bool:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    try:
        primary = report["list_price"]["cost_question"]["all_four"]
        return (report["status"] == "COMPLETE" and primary["label"] in ("NOTE IS THE BETTER BUY",
                "FUNCTION IS THE BETTER BUY", "UNDECIDED") and "interval_95" in primary
                and report["list_price"]["accuracy"]["label"] in ("CATCHES UP", "DOES NOT", "UNDECIDED")
                and "all_four" in report["billed_with_cached_input"]["cost_question"])
    except (KeyError, TypeError):
        return False


def calibration_tasks(scenarios: list[str]) -> list[str]:
    """The teacher's first 3 solo runs, fixed in advance: the first tasks in sorted order."""
    return sorted(all_tasks(scenarios))[:CALIBRATION_RUNS]


def calibration_retry_lines(own: list[dict], scenarios: list[str]) -> list[str]:
    latest = latest_of(own)
    by_repeat: dict[int, list[str]] = defaultdict(list)
    for task in calibration_tasks(scenarios):
        row = latest.get(("cloud_alone", TEACHER, task))
        if row is None:
            by_repeat[1].append(task)
        elif row["stop_reason"] in NOT_A_RESULT and row["repeat"] < MAX_REPEAT:
            by_repeat[row["repeat"] + 1].append(task)
    return [f"{repeat} {','.join(sorted(found))}" for repeat, found in sorted(by_repeat.items())]


def projection(own: list[dict], config: dict, scenarios: list[str]) -> tuple[list[str], dict]:
    """From the teacher's 3 calibration runs: the projected OpenAI spend of the stage, and how often replies were cut."""
    latest = latest_of(own)
    runs = [latest.get(("cloud_alone", TEACHER, task)) for task in calibration_tasks(scenarios)]
    if any(row is None or row["stop_reason"] in NOT_A_RESULT for row in runs):
        return ["the teacher's 3 calibration runs are not all on file with a result"], {}
    paths = [RUN_DIR / "raw_large" / f"cloud_alone__{TEACHER}__{row['task_id']}__r{row['repeat']}.json" for row in runs]
    if not all(path.exists() for path in paths):
        return ["a calibration run has no trajectory file"], {}
    mean = statistics.mean(row["cost_usd"] for row in runs)
    steps = [step for path in paths for step in json.loads(path.read_text(encoding="utf-8"))["steps"]]
    cut = sum(step.get("finish_reason") == "length" for step in steps) / len(steps) if steps else 0.0
    provider = "openai.com"
    left = (config["ledger_caps_usd"][provider] - (config.get("ledger_reserve_usd") or {}).get(provider, 0.0)
            - ledger_total(LEDGER, provider))
    projected = mean * RUN_EQUIVALENTS - sum(row["cost_usd"] for row in runs)
    facts = {"teacher_runs": len(runs), "mean_cost_per_run_usd": round(mean, 4),
             "projected_more_openai_spend_usd": round(projected, 2), "left_under_the_stop_usd": round(left, 2),
             "steps_cut_by_the_output_limit": round(cut, 3)}
    problems = []
    if projected > left:
        problems.append(f"the teacher costs ${mean:.3f} a run, so the stage would need about ${projected:.0f} more on "
                        f"OpenAI and ${left:.0f} is left under the stop")
    if cut > MAX_CUT_OFF_SHARE:
        problems.append(f"{cut:.0%} of the teacher's replies were cut by the output limit")
    return problems, facts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("preflight", "students", "source", "ready", "control", "retry",
                                         "calibration-retry", "project", "verify-result", "check", "reference",
                                         "analyze", "privacy", "log-row"))
    parser.add_argument("--model")
    parser.add_argument("--functions", action="store_true")
    parser.add_argument("--condition", choices=("cloud_alone", *ARMS))
    parser.add_argument("--ping", action="store_true")
    parser.add_argument("--out")
    parser.add_argument("--status")
    parser.add_argument("--start")
    args = parser.parse_args()
    scenarios = scenario_ids()
    if args.what == "preflight":
        problems = preflight(args.ping)
        for problem in problems:
            print("PROBLEM:", problem)
        print("PREFLIGHT OK" if not problems else "PREFLIGHT FAILED: nothing was run")
        return 0 if not problems else 2
    if args.what == "students":
        print(" ".join(STUDENTS))
        return 0
    if args.what == "source":
        print(SOURCE[args.model])
        return 0
    if args.what == "privacy":
        hits = privacy_hits()
        print("\n".join(hits))
        return 0 if not hits else 2
    if args.what == "log-row":
        print(log_row(args.status, args.start), end="")
        return 0
    if args.what == "reference":
        write_once(Path(args.out), reference())
        print(f"written: {args.out}")
        return 0
    own, solo = read_jsonl(RUN_DIR / "runs.jsonl"), solo_rows(scenarios)
    teach = read_jsonl(RUN_DIR / "teach.jsonl")
    rows = own + solo
    if args.what == "ready":
        reasons = (build_reasons(rows, teach, "compile", "shared", scenarios) if args.functions
                   else arm_reasons(own, "cloud_alone", TEACHER, scenarios))
        print("; ".join(reasons))
        return 0
    if args.what == "verify-result":
        return 0 if result_is_whole(Path(args.out)) else 2
    if args.what == "calibration-retry":
        print("\n".join(calibration_retry_lines(own, scenarios)))
        return 0
    if args.what == "project":
        if CALIBRATION_FILE.exists():
            print(CALIBRATION_FILE.read_text(encoding="utf-8").strip())
            return 0
        problems, facts = projection(own, json.loads(CONFIG.read_text(encoding="utf-8")), scenarios)
        print(json.dumps(facts))
        for problem in problems:
            print("STOP:", problem)
        if not problems:
            write_once(CALIBRATION_FILE, {"passed": True, **facts})
        return 0 if not problems else 2
    not_ready = arm_reasons(own, "cloud_alone", TEACHER, scenarios)
    if args.what == "control":
        if not_ready:
            print("; ".join(not_ready), file=sys.stderr)
            return 2
        print(",".join(control_tasks(rows, args.model, scenarios)))
        return 0
    if args.what == "retry":
        if args.condition == "generic_note" and not_ready:
            return 2
        print("\n".join(retry_lines(args.condition, args.model, rows, teach, scenarios)))
        return 0
    reasons = incomplete_reasons(own, solo, teach, scenarios)
    if args.what == "check":
        print("; ".join(reasons))
        return 0
    if reasons:
        print("STATUS INCOMPLETE; no result computed: " + "; ".join(reasons))
        return 2
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    write_once(Path(args.out), {"status": "COMPLETE", **analyze(own, solo, teach, scenarios, config)})
    print(f"STATUS COMPLETE; written, not printed: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
