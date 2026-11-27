"""Environment gate: is AppWorld on this machine grading tasks the way it should?

Run it with the AppWorld environment's Python, from the repository root:

    .venv-appworld/Scripts/python.exe experiments/appworld_env_check.py          (Windows)
    .venv-appworld/bin/python experiments/appworld_env_check.py                  (Linux, macOS)

It does three things and writes one JSON report to results/env_gate/:

1. AppWorld's own unit tests for its core modules (the ones that broke on Windows before the shim in
   src/loopy/eval/appworld_win_compat.py).
2. AppWorld's end-to-end task validation: every train and dev task is solved with the benchmark's own
   reference solution and must pass its own checker.
3. A negative control: on every dev task an agent that does nothing except call `complete_task()` must
   NOT pass, unless the task's reference answer is itself empty. A grader that passes everything is useless.

No model is called and nothing is spent. Exit code 0 means all three passed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import platform
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHIM_PATH = REPO / "src" / "loopy" / "eval" / "appworld_win_compat.py"


def load_shim():
    spec = importlib.util.spec_from_file_location("appworld_win_compat", SHIM_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def real_now() -> dt.datetime:
    """Wall-clock time that ignores AppWorld's frozen task clock (it freezes time with freezegun)."""
    try:
        from freezegun.api import real_datetime

        return real_datetime.now().astimezone()
    except Exception:
        return dt.datetime.now().astimezone()


class _SepInsensitiveDict(dict):
    """One AppWorld test looks up an in-memory database by a key written with '/'. On Windows the key is
    built with os.path.join and has a backslash. This lets that test find it. Used for the test run only."""

    @staticmethod
    def _norm(key):
        return key.replace("/", os.sep) if isinstance(key, str) and key.startswith(":memory:") else key

    def __getitem__(self, key):
        return super().__getitem__(self._norm(key))

    def __contains__(self, key):
        return super().__contains__(self._norm(key))

    def get(self, key, default=None):
        return super().get(self._norm(key), default)


def run_core_unit_tests() -> dict:
    import pytest
    from appworld.apps.model_lib import CachedDBHandler
    from appworld.common.path_store import path_store

    cache_dir = path_store.cache
    files = [
        "test_common",
        "test_model_collection",
        "test_sqlite_fts",
        "test_load_task_ids",
        "test_safety_guard",
        "test_sqlmodel",
        "test_appworld",  # last, because it freezes time
    ]
    paths = [os.path.join("tests", "package", f"{name}.py") for name in files]

    class Collector:
        def __init__(self):
            self.outcomes: dict[str, str] = {}

        def pytest_runtest_logreport(self, report):
            if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
                self.outcomes[report.nodeid] = report.outcome

    collector = Collector()
    original_cache = CachedDBHandler.cache
    if os.name == "nt":
        CachedDBHandler.cache = _SepInsensitiveDict(original_cache)
    cwd = os.getcwd()
    os.chdir(cache_dir)
    sys.path.insert(0, cache_dir)
    try:
        status = pytest.main(["-q", "--tb=line", *paths], plugins=[collector])
    finally:
        os.chdir(cwd)
        sys.path.remove(cache_dir)
        if os.name == "nt":
            plain = dict(CachedDBHandler.cache)
            CachedDBHandler.cache = original_cache
            original_cache.clear()
            original_cache.update(plain)
    failed = sorted(node for node, outcome in collector.outcomes.items() if outcome != "passed")
    return {
        "exit_status": int(status),
        "n_tests": len(collector.outcomes),
        "n_passed": sum(1 for outcome in collector.outcomes.values() if outcome == "passed"),
        "failed": failed,
        "passed": int(status) == 0 and not failed,
    }


def run_reference_solutions() -> dict:
    from appworld.environment import AppWorld
    from appworld.task import load_task_ids

    per_split = {}
    failed: list[str] = []
    for split in ("train", "dev"):
        task_ids = load_task_ids(split)
        n_pass = 0
        for task_id in task_ids:
            with AppWorld(
                task_id=task_id,
                experiment_name="env_gate_reference",
                raise_on_failure=False,
                ground_truth_mode="full",
            ) as world:
                code = world.task.ground_truth.compiled_solution_code + "\nsolution(apis, requester)"
                world.execute(code)
                success = bool(world.evaluate().success)
            n_pass += int(success)
            if not success:
                failed.append(task_id)
        per_split[split] = {"n_tasks": len(task_ids), "n_passed": n_pass}
    return {"per_split": per_split, "failed_task_ids": failed, "passed": not failed}


def run_do_nothing_control() -> dict:
    from appworld.environment import AppWorld
    from appworld.task import load_task_ids

    task_ids = load_task_ids("dev")
    wrongly_passed: list[str] = []
    for task_id in task_ids:
        with AppWorld(task_id=task_id, experiment_name="env_gate_do_nothing", raise_on_failure=False) as world:
            world.execute("apis.supervisor.complete_task()")
            if bool(world.evaluate().success):
                wrongly_passed.append(task_id)
    return {
        "n_tasks": len(task_ids),
        "n_passed_by_doing_nothing": len(wrongly_passed),
        "task_ids_passed_by_doing_nothing": wrongly_passed,
        "passed": not wrongly_passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--skip-unit-tests", action="store_true")
    parser.add_argument("--out", default=None, help="report path (default: results/env_gate/<timestamp>.json)")
    args = parser.parse_args()

    os.environ.setdefault("APPWORLD_ROOT", str(REPO))
    import appworld

    appworld.update_root(str(REPO))
    shim = load_shim()
    patched = shim.apply()

    started = real_now()
    report = {
        "started": started.isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "appworld_version": appworld.__version__,
        "data_version": (REPO / "data" / "version.txt").read_text().strip(),
        "shim_sha256": sha256_file(SHIM_PATH),
        "shim_patched": patched,
        "script_sha256": sha256_file(Path(__file__).resolve()),
    }
    if not args.skip_unit_tests:
        print("1/3 AppWorld core unit tests ...", flush=True)
        report["core_unit_tests"] = run_core_unit_tests()
    print("2/3 reference solutions on train and dev ...", flush=True)
    report["reference_solutions"] = run_reference_solutions()
    print("3/3 do-nothing control on dev ...", flush=True)
    report["do_nothing_control"] = run_do_nothing_control()
    report["finished"] = real_now().isoformat(timespec="seconds")
    checks = [value["passed"] for value in report.values() if isinstance(value, dict) and "passed" in value]
    report["gate_passed"] = all(checks)

    out = Path(args.out) if args.out else REPO / "results" / "env_gate" / f"{started:%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8") as handle:  # never overwrite a report
        json.dump(report, handle, indent=2)
    summary = {key: value for key, value in report.items() if key not in ("core_unit_tests",)}
    print(json.dumps(summary, indent=2))
    if "core_unit_tests" in report:
        tests = report["core_unit_tests"]
        print(f"core unit tests: {tests['n_passed']}/{tests['n_tests']} passed; failed: {tests['failed']}")
    print(f"report: {out}")
    print("ENV GATE PASSED" if report["gate_passed"] else "ENV GATE FAILED")
    return 0 if report["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
