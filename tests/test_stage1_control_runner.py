"""The control runner, run for real in a sandbox. No model, no AppWorld, nothing read from or written to the repo.

The sandbox holds copies of run_control.sh, sweep.py and the scenario file, hand-made stage 1 rows, and a stand-in for
run_arm.py that only records how it was called. So the shell logic and sweep.py are the real ones, on made-up rows.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")
# On Windows, bash.exe under System32 is the WSL launcher: it would not see these paths.
pytestmark = pytest.mark.skipif(BASH is None or "system32" in BASH.lower(), reason="needs a bash that sees local paths")

FAKE_ARM = '''"""Stand-in for run_arm.py in the sandbox: records the call; a rerun (repeat above 1) is written as a finished run."""
import argparse
import json
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--model")
parser.add_argument("--tasks")
parser.add_argument("--condition")
parser.add_argument("--repeat", type=int, default=1)
parser.add_argument("--max-usd", type=float)
args, _ = parser.parse_known_args()
calls, runs = sys.argv[1], sys.argv[2]
with open(calls, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"model": args.model, "tasks": args.tasks.split(","), "repeat": args.repeat,
                             "max_usd": args.max_usd, "condition": args.condition}) + "\\n")
if args.repeat > 1:
    with open(runs, "a", encoding="utf-8", newline="\\n") as handle:
        for task in args.tasks.split(","):
            handle.write(json.dumps({"condition": args.condition, "model_key": args.model, "task_id": task,
                                     "repeat": args.repeat, "stop_reason": "completed", "success": False}) + "\\n")
'''


def load_sweep():
    spec = importlib.util.spec_from_file_location("stage1_sweep_for_the_runner_test", ROOT / "experiments/stage1/sweep.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(condition, model, task, success, repeat=1, stop_reason="completed"):
    return {"condition": condition, "model_key": model, "task_id": task, "repeat": repeat, "stop_reason": stop_reason,
            "success": success}


def make_sandbox(folder: Path, control_rows) -> dict:
    """A finished stage 1 in which every student failed everything alone and no note or function was built."""
    sweep = load_sweep()
    scenarios = sweep.manifest_scenarios()
    tasks = [f"{scenario}_{version}" for scenario in scenarios for version in (1, 2, 3)]
    (folder / "experiments" / "stage1").mkdir(parents=True)
    for name in ("run_control.sh", "sweep.py", "scenarios.json"):
        shutil.copy(ROOT / "experiments" / "stage1" / name, folder / "experiments" / "stage1" / name)
    run_dir = folder / "results" / "pilot" / "stage1"
    (run_dir / "raw_large").mkdir(parents=True)
    (run_dir / "raw_large" / "console.log").write_text("STAGE1 DONE made up for the test\n", encoding="utf-8")
    runs = [row("cloud_alone", sweep.TEACHER, task, True) for task in tasks]
    runs += [row("small_alone", student, task, False) for student in sweep.STUDENTS for task in tasks]
    runs += control_rows(sweep.STUDENTS, [task for task in tasks if not task.endswith("_1")])
    (run_dir / "runs.jsonl").write_text("".join(json.dumps(item) + "\n" for item in runs), encoding="utf-8")
    teach = [{"kind": "compile", "small_model_key": "shared", "scenario_id": scenario, "status": "failed_validation",
              "cut_off_requests": 0, "cutoff_fix_version": 3} for scenario in scenarios]  # real failures, not voided
    teach += [{"kind": "coach_checked", "small_model_key": student, "scenario_id": scenario,
               "status": "failed_validation"} for student in sweep.STUDENTS for scenario in scenarios]
    (run_dir / "teach.jsonl").write_text("".join(json.dumps(item) + "\n" for item in teach), encoding="utf-8")

    (folder / "fake_arm.py").write_text(FAKE_ARM, encoding="utf-8")
    python, calls = Path(sys.executable).as_posix(), (folder / "calls.jsonl").as_posix()
    wrapper = folder / ".venv" / "bin" / "python"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        "# Sandbox interpreter: sweep.py runs for real on the sandbox rows; run_arm.py is a recorder, no model.\n"
        'case "$*" in\n'
        f'  *"run_arm.py"*) exec "{python}" "{(folder / "fake_arm.py").as_posix()}" "{calls}" '
        f'"{(run_dir / "runs.jsonl").as_posix()}" "$@";;\n'
        f'  *) exec "{python}" "$@" --run-dir "{run_dir.as_posix()}";;\n'
        "esac\n", encoding="utf-8", newline="\n")
    os.chmod(wrapper, 0o755)
    return {"folder": folder, "run_dir": run_dir, "students": sweep.STUDENTS, "calls": folder / "calls.jsonl"}


def start_control(sandbox: dict) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "experiments/stage1/run_control.sh"], cwd=sandbox["folder"], capture_output=True,
                          text=True, timeout=600)


def calls_of(sandbox: dict) -> list[dict]:
    path = sandbox["calls"]
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_control_run_cut_short_at_repeat_2_is_rerun_as_repeat_3(tmp_path):
    """The case from review: the start gate must not stop on the very control run the retry is there to repair."""
    cut_short = {}

    def control_rows(students, test_tasks):
        cut_short.update(student=students[0], task=test_tasks[0])
        rows = [row("generic_note", student, task, False) for student in students for task in test_tasks
                if (student, task) != (students[0], test_tasks[0])]
        return rows + [row("generic_note", students[0], test_tasks[0], False, 1, "model_error"),
                       row("generic_note", students[0], test_tasks[0], False, 2, "cost_cap")]

    sandbox = make_sandbox(tmp_path, control_rows)
    done = start_control(sandbox)
    assert done.returncode == 0, done.stdout + done.stderr
    calls = calls_of(sandbox)
    reruns = [call for call in calls if call["repeat"] > 1]
    assert reruns == [{"model": cut_short["student"], "tasks": [cut_short["task"]], "repeat": 3, "max_usd": 1.0,
                       "condition": "generic_note"}]
    first_pass = [call for call in calls if call["repeat"] == 1]
    assert sorted(call["model"] for call in first_pass) == sorted(sandbox["students"])
    assert all(call["max_usd"] == 4.0 and len(call["tasks"]) == 60 for call in first_pass)
    log = (sandbox["run_dir"] / "raw_large" / "console.log").read_text(encoding="utf-8").splitlines()
    assert log[-1].startswith("CONTROL FINISHED")   # the stand-in wrote the repeat 3 run as finished


def test_the_control_does_not_start_while_stage_1_itself_is_incomplete(tmp_path):
    sandbox = make_sandbox(tmp_path, lambda students, test_tasks: [])
    runs = sandbox["run_dir"] / "runs.jsonl"
    lines = runs.read_text(encoding="utf-8").splitlines()
    runs.write_text("".join(line + "\n" for line in lines[1:]), encoding="utf-8")   # one teacher run is gone
    refused = start_control(sandbox)
    assert refused.returncode == 2 and "stage 1 is not complete on file" in refused.stdout
    assert calls_of(sandbox) == []                                                  # the old DONE line was not enough
    log = (sandbox["run_dir"] / "raw_large" / "console.log").read_text(encoding="utf-8")
    assert "CONTROL" not in log


def test_the_control_is_marked_incomplete_when_a_rerun_still_does_not_count(tmp_path):
    def control_rows(students, test_tasks):
        return [row("generic_note", student, task, False) for student in students for task in test_tasks[1:]]

    sandbox = make_sandbox(tmp_path, control_rows)   # the first control task of every student has no run at all, and
    left = start_control(sandbox)                    # the stand-in never writes a first-pass run
    assert left.returncode == 1
    log = (sandbox["run_dir"] / "raw_large" / "console.log").read_text(encoding="utf-8").splitlines()
    assert log[-1].startswith("CONTROL INCOMPLETE") and "1 of 60 control runs missing" in log[-1]
