"""Find the work the stage 1 runner has to redo because of an infrastructure fault. Prints a comma-separated list.

    sweep.py infra --condition small_alone --model gemma-3-27b
        tasks whose latest run ended in `model_error` (the provider or the bridge failed, the model did not)
        and that have not been rerun yet. The rerun is recorded as repeat 2; repeat 1 stays in the file.

    sweep.py check
        why stage 1 cannot be analyzed yet: missing runs or builds, named against the scenario file, and runs that
        should not be there. Empty means ready. It reads stage 1's own runs and builds only. The control's runs are
        the business of `control-check` and `control-retry`, so a control run that was cut short does not block it.

    sweep.py control-check
        why the generic-note control is not finished: control tasks with no run, or whose latest run ended in an
        infrastructure error or at a spend limit, or control runs that should not be there. Empty means finished.

    sweep.py control-retry --model gemma-3-27b
        control tasks whose latest run ended in an infrastructure error or at a spend limit. One line per repeat
        number to record next: "<repeat> <task>,<task>". The rerun is recorded at the latest repeat plus one.

    sweep.py voided
        the function builds that are redone from the start because tries were lost to the output limit. See
        `voided_builds`.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl
from loopy.skills.teach import skip_still_holds

RUN_DIR = REPO_ROOT / "results" / "pilot" / "stage1"
SCENARIO_FILE = Path(__file__).resolve().parent / "scenarios.json"
NOT_A_RESULT = ("model_error", "cost_cap")  # the provider, the bridge or a spend limit ended the run, not the model
# From reading every attempt of the failed builds on Nov 23, 2026. d18139b's rebuild was stopped by the pause.
AUDITED_LOST_TRIES = {"986aa4e", "d18139b", "f861c32", "ffe6d5e"}
TEACHER = "glm-5.3-flash"
STUDENTS = ("gemma-3-27b", "gpt-oss-120b", "minimax-m3.1-flash", "deepseek-v4.1-flash", "qwen3.8-27b")
N_SCENARIOS, N_TASKS = 30, 90


def manifest_scenarios() -> list[str]:
    """The scenarios fixed for stage 1, in the order they were drawn."""
    return [item["scenario_id"] for item in json.loads(SCENARIO_FILE.read_text(encoding="utf-8"))["chosen"]]


def _names(ids: set[str]) -> str:
    listed = sorted(ids)
    return ",".join(listed[:5]) + (f" and {len(listed) - 5} more" if len(listed) > 5 else "")


def infra_tasks(condition: str, model: str) -> list[str]:
    latest: dict[str, dict] = {}
    for row in read_jsonl(RUN_DIR / "runs.jsonl"):
        if row["condition"] == condition and row["model_key"] == model:
            if row["task_id"] not in latest or row["repeat"] >= latest[row["task_id"]]["repeat"]:
                latest[row["task_id"]] = row
    return sorted(task for task, row in latest.items() if row["stop_reason"] == "model_error" and row["repeat"] == 1)


def manifest_test_tasks() -> set[str]:
    """Versions 2 and 3 of the scenarios fixed for stage 1: the only tasks a skill or control run belongs on."""
    return {f"{scenario}_{version}" for scenario in manifest_scenarios() for version in (2, 3)}


def voided_builds() -> list[str]:
    """Function builds to redo from the start: their latest row failed and tries were lost to the output limit.

    Two rules. (1) The builds audited by hand on Nov 23 (`AUDITED_LOST_TRIES`), until each has a row built after the
    fix (`cutoff_fix_version` 3). Those builds never got their protocol budget of three real attempts.
    (2) Any build whose latest failed row has no `cut_off_requests` count. Such a row was written before cut-off
    replies were counted, so it cannot show how many real attempts the build got. Rule 2 only matters when an early
    checkpoint is resumed: then every such build is rebuilt, not only the four audited ones. On the finished stage 1
    files it selects nothing, because every failed build there has a later row with the count. 270f1ff, audited as a
    failure on real attempts only, is one of those and stays failed.
    """
    latest = {row["scenario_id"]: row for row in read_jsonl(RUN_DIR / "teach.jsonl")
              if row["kind"] == "compile" and row["small_model_key"] == "shared"}
    return sorted(scenario for scenario, row in latest.items()
                  if row["status"] in ("failed_validation", "cut_off")
                  and ((scenario in AUDITED_LOST_TRIES and row.get("cutoff_fix_version") != 3)
                       or row.get("cut_off_requests") is None))


def control_tasks(model: str) -> list[str]:
    """Test tasks the student failed alone, in scenarios where it failed version 1 and the teacher passed it."""
    latest: dict[tuple[str, str, str], dict] = {}
    for row in read_jsonl(RUN_DIR / "runs.jsonl"):
        key = (row["condition"], row["model_key"], row["task_id"])
        if key not in latest or row["repeat"] >= latest[key]["repeat"]:
            latest[key] = row
    tasks = []
    for (condition, student, task), row in latest.items():
        scenario, version = task.rsplit("_", 1)
        if condition != "small_alone" or student != model or version == "1" or row["success"]:
            continue
        own, teacher = latest.get(("small_alone", model, f"{scenario}_1")), latest.get(("cloud_alone", TEACHER, f"{scenario}_1"))
        if own and teacher and not own["success"] and teacher["success"]:
            tasks.append(task)
    return sorted(tasks)


def control_retries(model: str) -> dict[int, list[str]]:
    """Control tasks to run again, by the repeat number to record: the latest run ended in `NOT_A_RESULT`.

    `infra_tasks` only lists `model_error` rows at repeat 1, which is what the stage 1 runner needs. A control task
    whose latest row is a spend-limit stop, or a second failed try, would never be listed there.
    """
    latest: dict[str, dict] = {}
    for row in read_jsonl(RUN_DIR / "runs.jsonl"):
        if row["condition"] == "generic_note" and row["model_key"] == model:
            if row["task_id"] not in latest or row["repeat"] >= latest[row["task_id"]]["repeat"]:
                latest[row["task_id"]] = row
    retries: dict[int, list[str]] = defaultdict(list)
    for task in control_tasks(model):
        if task in latest and latest[task]["stop_reason"] in NOT_A_RESULT:
            retries[latest[task]["repeat"] + 1].append(task)
    return dict(sorted(retries.items()))


def control_incomplete_reasons() -> list[str]:
    """Why the generic-note control is not finished. Empty means every control task has a run that counts."""
    latest: dict[tuple[str, str], dict] = {}
    for row in read_jsonl(RUN_DIR / "runs.jsonl"):
        if row["condition"] == "generic_note":
            key = (row["model_key"], row["task_id"])
            if key not in latest or row["repeat"] >= latest[key]["repeat"]:
                latest[key] = row
    reasons = []
    wanted_by = {student: control_tasks(student) for student in STUDENTS}
    # A control run belongs only on a control task of that student. Anything else changed after the control ran (an
    # alone run redone with another outcome) or was never part of it, and it would be counted in the arm's totals.
    stray = {f"{model}:{task}" for model, task in latest if task not in wanted_by.get(model, ())}
    if stray:
        reasons.append(f"generic_note runs on file that should not exist (not a control task of that student): "
                       f"{_names(stray)}")
    for student in STUDENTS:
        wanted = wanted_by[student]
        missing = {task for task in wanted if (student, task) not in latest}
        bad = {task for task in wanted if (student, task) in latest
               and latest[(student, task)]["stop_reason"] in NOT_A_RESULT}
        if missing:
            reasons.append(f"{student}: {len(missing)} of {len(wanted)} control runs missing ({_names(missing)})")
        if bad:
            reasons.append(f"{student}: {len(bad)} control runs ended in an infrastructure error or the cost cap "
                           f"({_names(bad)})")
    return reasons


def incomplete_reasons() -> list[str]:
    """Why stage 1 cannot be analyzed yet. Empty means every required run and build is on file."""
    runs, teach = read_jsonl(RUN_DIR / "runs.jsonl"), read_jsonl(RUN_DIR / "teach.jsonl")
    reasons = []
    chosen = set(manifest_scenarios())
    chosen_tasks = {f"{scenario}_{version}" for scenario in chosen for version in (1, 2, 3)}

    def against_manifest(who: str, what: str, have: set[str], want: set[str]) -> None:
        """Counts can match while the ids do not, so the ids are compared with the scenario file."""
        if want - have:
            reasons.append(f"{who}: {what} missing for {_names(want - have)}")
        if have - want:
            reasons.append(f"{who}: {what} on file for ids outside the scenario file: {_names(have - want)}")

    capped = sum(1 for row in teach if row["status"] == "cost_cap")
    if capped:
        reasons.append(f"{capped} builds stopped by the cost cap")
    latest: dict[tuple[str, str, str], dict] = {}
    for row in runs:
        # The control's runs are not read here; `control_incomplete_reasons` reads them. This check is also the gate
        # the control starts behind, and a control run cut short must not close that gate on the retry that repairs it.
        if row["condition"] == "generic_note":
            continue
        key = (row["condition"], row["model_key"], row["task_id"])
        if key not in latest or row["repeat"] >= latest[key]["repeat"]:
            latest[key] = row
    bad = sum(1 for row in latest.values() if row["stop_reason"] in NOT_A_RESULT)
    if bad:
        reasons.append(f"{bad} runs ended in an infrastructure error or the cost cap")
    expected_model = {"cloud_alone": (TEACHER,), "small_alone": STUDENTS, "coach_checked": STUDENTS,
                      "compile": STUDENTS}
    strangers = {f"{condition}:{model}" for condition, model, _ in latest
                 if model not in expected_model.get(condition, ())}
    if strangers:
        reasons.append(f"runs on file of a model or arm that is not part of stage 1: {_names(strangers)}")

    def last_builds(kind: str, owner: str) -> dict[str, dict]:
        return {row["scenario_id"]: row for row in teach if row["kind"] == kind and row["small_model_key"] == owner}

    def skips_against_runs(who: str, builds: dict[str, dict], student: str | None) -> None:
        """A skipped build is a decision only while the version 1 run it was read from is still the latest one."""
        def passed(condition: str, model: str | None, scenario: str) -> bool | None:
            row = latest.get((condition, model, f"{scenario}_1"))
            return None if row is None else bool(row["success"])

        # The same rule the builders use to decide whether a recorded skip still counts as done.
        stale = {status: {scenario for scenario, row in builds.items() if row["status"] == status
                          and not skip_still_holds(status, passed("small_alone", student, scenario),
                                                   passed("cloud_alone", TEACHER, scenario))}
                 for status in ("skipped_cloud_failed", "skipped_small_passed")}
        if stale["skipped_cloud_failed"]:
            reasons.append(f"{who}: marked skipped_cloud_failed but the teacher's latest version 1 run passed: "
                           f"{_names(stale['skipped_cloud_failed'])}")
        if stale["skipped_small_passed"]:
            reasons.append(f"{who}: marked skipped_small_passed but the student's latest version 1 run failed: "
                           f"{_names(stale['skipped_small_passed'])}")

    teacher_runs = sum(1 for condition, model, _ in latest if condition == "cloud_alone" and model == TEACHER)
    if teacher_runs != N_TASKS:
        reasons.append(f"{TEACHER}: {teacher_runs} of {N_TASKS} teacher runs")
    against_manifest(TEACHER, "teacher runs",
                     {task for condition, model, task in latest if condition == "cloud_alone" and model == TEACHER},
                     chosen_tasks)
    function_rows = last_builds("compile", "shared")
    if len(function_rows) != N_SCENARIOS:
        reasons.append(f"{len(function_rows)} of {N_SCENARIOS} function decisions")
    against_manifest("shared function", "decisions", set(function_rows), chosen)
    skips_against_runs("shared function", function_rows, None)
    waiting = voided_builds()
    if waiting:
        reasons.append(f"function rebuilds not finished: {','.join(waiting)}")
    functions = {scenario for scenario, row in function_rows.items() if row["status"] == "built"}
    for student in STUDENTS:
        alone = sum(1 for condition, model, _ in latest if condition == "small_alone" and model == student)
        if alone != N_TASKS:
            reasons.append(f"{student}: {alone} of {N_TASKS} alone runs")
        against_manifest(student, "alone runs",
                         {task for condition, model, task in latest if condition == "small_alone" and model == student},
                         chosen_tasks)
        notes = last_builds("coach_checked", student)
        if len(notes) != N_SCENARIOS:
            reasons.append(f"{student}: {len(notes)} of {N_SCENARIOS} note decisions")
        against_manifest(student, "note decisions", set(notes), chosen)
        skips_against_runs(f"{student} note", notes, student)
        built = {scenario for scenario, row in notes.items() if row["status"] == "built"}
        for condition, scenarios in (("coach_checked", built), ("compile", functions)):
            want = {f"{scenario}_{version}" for scenario in scenarios for version in (2, 3)}
            have = {task for cond, model, task in latest if cond == condition and model == student}
            if want - have:
                reasons.append(f"{student}: {len(want - have)} {condition} test runs missing")
            if have - want:  # no built skill behind them, or not a test task of the scenario file
                reasons.append(f"{student}: {condition} runs on file that should not exist (no built skill for the "
                               f"scenario, or not one of its test tasks): {_names(have - want)}")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("infra", "voided", "check", "control", "control-check", "control-retry"))
    parser.add_argument("--condition")
    parser.add_argument("--model")
    parser.add_argument("--run-dir", default=None, help="another stage 1 results folder to read")
    args = parser.parse_args()
    if args.run_dir:
        global RUN_DIR
        RUN_DIR = Path(args.run_dir)
    if args.what == "check":
        print("; ".join(incomplete_reasons()))
        return 0
    if args.what == "control-check":
        print("; ".join(control_incomplete_reasons()))
        return 0
    if args.what == "control":
        print(",".join(control_tasks(args.model)))
        return 0
    if args.what == "control-retry":
        for repeat, tasks in control_retries(args.model).items():
            print(f"{repeat} {','.join(tasks)}")
        return 0
    print(",".join(infra_tasks(args.condition, args.model) if args.what == "infra" else voided_builds()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
