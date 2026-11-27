"""Run records: one JSON line per task run, a meta file per batch, and a spend ledger across batches.

Rules this module enforces (from CLAUDE.md): every number comes from a file written by a committed script,
completed records are never overwritten, and spending is checked before a batch starts.

What is committed and what stays local: `runs.jsonl` and `meta.json` hold ids, counts, tokens, dollars and
timings only, so they can be public. Full trajectories contain AppWorld task text and app data, which
AppWorld's license asks not to be republished in plain text; they go to `raw_large/`, which is gitignored.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import os
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

REPO_ROOT = Path(__file__).resolve().parents[3]


def now_et() -> str:
    """Local wall-clock time with its UTC offset (the laptop is on New York time)."""
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    def run(*arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, text=True).stdout.strip()

    return {"commit": run("rev-parse", "HEAD"), "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty_files": [line for line in run("status", "--porcelain").splitlines() if line]}


def record_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (record["task_id"], record["condition"], record["model_key"], record["repeat"])


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Hold an OS lock on `<path>.lock`. The OS releases it if the process dies."""
    with open(str(path) + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.02)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def append_jsonl(path: Path | str, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _locked(path):
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)


def write_new_json(path: Path | str, payload: Any) -> None:
    """Create a JSON file, refusing to replace one that exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)


def completed_keys(path: Path | str) -> set[tuple[Any, ...]]:
    return {record_key(record) for record in read_jsonl(path)}


def environment_summary() -> dict[str, Any]:
    import pydantic_ai

    return {"platform": platform.platform(), "python": platform.python_version(),
            "pydantic_ai": pydantic_ai.__version__}


# -- spend ledger ----------------------------------------------------------------------------------------
def ledger_total(ledger: Path | str, provider: str | None = None) -> float:
    return sum(
        float(entry["usd"]) for entry in read_jsonl(ledger) if provider is None or entry.get("provider") == provider
    )


def ledger_add(ledger: Path | str, provider: str, usd: float, run_name: str, note: str = "") -> None:
    append_jsonl(ledger, {"time": now_et(), "provider": provider, "usd": round(usd, 6), "run": run_name, "note": note})


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    n = len(records)
    passed = sum(1 for record in records if record["success"])
    return {
        "n_runs": n,
        "n_passed": passed,
        "pass_rate": (passed / n) if n else None,
        "cost_usd": round(sum(record["cost_usd"] for record in records), 6),
        "cloud_calls": sum(record["cloud_calls"] for record in records),
        "input_tokens": sum(record["input_tokens"] for record in records),
        "output_tokens": sum(record["output_tokens"] for record in records),
        "wall_seconds": round(sum(record["wall_seconds"] for record in records), 1),
    }
