"""Loopy side of the AppWorld bridge: drives `appworld_worker.py`, which runs in AppWorld's own Python.

    with AppWorldBridge() as bridge:
        task = bridge.open_task("50e1ac9_1", experiment_name="pilot")
        result = bridge.execute("print(apis.api_docs.show_app_descriptions())")
        evaluation = bridge.evaluate()        # AppWorld's own checker
        bridge.close_task()

The AppWorld interpreter is `.venv-appworld` next to the repository root unless LOOPY_APPWORLD_PYTHON says
otherwise. See the README for why AppWorld lives in a separate environment.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, IO

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER = Path(__file__).resolve().parent / "appworld_worker.py"


class BridgeError(RuntimeError):
    """The AppWorld worker failed, hung or answered with an error."""


@dataclass(frozen=True)
class TaskInfo:
    id: str
    instruction: str
    supervisor: dict[str, Any]
    datetime: str
    difficulty: int | None = None
    num_apps: int | None = None
    num_apis: int | None = None
    num_api_calls: int | None = None
    num_solution_code_lines: int | None = None

    @property
    def scenario_id(self) -> str:
        return self.id.rsplit("_", 1)[0]

    @property
    def version(self) -> int:
        return int(self.id.rsplit("_", 1)[1])


@dataclass(frozen=True)
class Execution:
    output: str
    task_completed: bool


def default_appworld_python(repo_root: Path = REPO_ROOT) -> Path:
    override = os.environ.get("LOOPY_APPWORLD_PYTHON")
    if override:
        return Path(override)
    if os.name == "nt":
        return repo_root / ".venv-appworld" / "Scripts" / "python.exe"
    return repo_root / ".venv-appworld" / "bin" / "python"


class AppWorldBridge:
    def __init__(
        self,
        appworld_root: Path | str | None = None,
        python: Path | str | None = None,
        stderr_path: Path | str | None = None,
        startup_timeout: float = 300.0,
        call_timeout: float = 400.0,
    ) -> None:
        self.appworld_root = Path(appworld_root) if appworld_root else REPO_ROOT
        self.python = Path(python) if python else default_appworld_python()
        self.stderr_path = Path(stderr_path) if stderr_path else None
        self.startup_timeout = startup_timeout
        self.call_timeout = call_timeout
        self.info: dict[str, Any] = {}
        self._process: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._stderr_handle: IO[str] | None = None

    # -- lifecycle -----------------------------------------------------------------------------------
    def start(self) -> "AppWorldBridge":
        if self._process is not None:
            return self
        if not self.python.exists():
            raise BridgeError(
                f"AppWorld's Python was not found at {self.python}. Create it with the commands in the README "
                "(a separate environment, because AppWorld pins pydantic 1), or set LOOPY_APPWORLD_PYTHON."
            )
        if self.stderr_path is not None:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_handle = open(self.stderr_path, "a", encoding="utf-8")
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self._process = subprocess.Popen(
            [str(self.python), str(WORKER), "--root", str(self.appworld_root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_handle if self._stderr_handle is not None else subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            cwd=str(self.appworld_root),
            env=environment,
        )
        threading.Thread(target=self._pump, daemon=True).start()
        ready = self._read(self.startup_timeout)
        if not ready.get("ok"):
            self.stop()
            raise BridgeError("AppWorld worker failed to start:\n" + str(ready.get("error")))
        self.info = ready
        return self

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            try:
                if process.poll() is None and process.stdin is not None:
                    process.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
                    process.stdin.flush()
                process.wait(timeout=30)
            except Exception:
                process.kill()
        if self._stderr_handle is not None:
            self._stderr_handle.close()
            self._stderr_handle = None

    def __enter__(self) -> "AppWorldBridge":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- protocol ------------------------------------------------------------------------------------
    def _pump(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _read(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            raise BridgeError(f"AppWorld worker did not answer within {timeout:.0f} s") from None
        if line is None:
            raise BridgeError("AppWorld worker exited unexpectedly (see its stderr log)")
        return json.loads(line)

    def _call(self, **request: Any) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None:
            raise BridgeError("bridge is not started")
        self._process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self._process.stdin.flush()
        reply = self._read(self.call_timeout)
        if not reply.get("ok"):
            raise BridgeError(str(reply.get("error")))
        return reply

    # -- commands ------------------------------------------------------------------------------------
    def open_task(self, task_id: str, experiment_name: str = "default", **options: Any) -> TaskInfo:
        reply = self._call(cmd="open", task_id=task_id, experiment_name=experiment_name, **options)
        return TaskInfo(**reply["task"])

    def execute(self, code: str) -> Execution:
        reply = self._call(cmd="execute", code=code)
        return Execution(output=reply["output"], task_completed=bool(reply["task_completed"]))

    def evaluate(self) -> dict[str, Any]:
        return self._call(cmd="evaluate")["evaluation"]

    def reference_solution(self) -> str:
        """The benchmark's own solution (train and dev only). For harness checks; never show it to an agent."""
        return self._call(cmd="reference_solution")["code"]

    def close_task(self) -> None:
        self._call(cmd="close")


if __name__ == "__main__":  # quick manual check: python -m loopy.eval.bridge <task_id>
    with AppWorldBridge() as bridge:
        print(bridge.info, file=sys.stderr)
        info = bridge.open_task(sys.argv[1] if len(sys.argv) > 1 else "50e1ac9_1", experiment_name="bridge_check")
        print(info.id, "difficulty", info.difficulty)
        print(bridge.execute("print(1 + 2)"))
        bridge.close_task()
