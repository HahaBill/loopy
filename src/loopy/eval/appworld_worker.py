"""AppWorld side of the bridge.

AppWorld pins pydantic 1 and the Loopy app needs pydantic 2, so they cannot share one Python environment.
This script runs with the AppWorld environment's Python and talks to `loopy.eval.bridge` over stdin and
stdout, one JSON object per line. It imports nothing from Loopy.

    <appworld python> src/loopy/eval/appworld_worker.py --root <folder holding data/>

Requests: {"cmd": "open" | "execute" | "evaluate" | "reference_solution" | "close" | "quit", ...}
Replies:  {"ok": true, ...} or {"ok": false, "error": "<traceback>"}

`reference_solution` returns the benchmark's own solution for a train or dev task. It exists for harness
checks (a correct solution must pass, doing nothing must fail). It must never be shown to an agent.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

OPEN_OPTIONS = ("experiment_name", "max_interactions", "timeout_seconds", "ground_truth_mode", "random_seed")
METADATA_KEYS = ("difficulty", "num_apps", "num_apis", "num_api_calls", "num_solution_code_lines")


def _load_shim() -> Any:
    spec = importlib.util.spec_from_file_location("appworld_win_compat", HERE / "appworld_win_compat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _field(record: Any, name: str) -> Any:
    if isinstance(record, dict):
        return record.get(name)
    return getattr(record, name, None)


def _task_summary(task: Any) -> dict[str, Any]:
    metadata = {}
    if getattr(task, "ground_truth", None) is not None:
        metadata = dict(getattr(task.ground_truth, "metadata", None) or {})
    return {
        "id": task.id,
        "instruction": task.instruction,
        "supervisor": {
            key: _field(task.supervisor, key) for key in ("first_name", "last_name", "email", "phone_number")
        },
        "datetime": str(task.datetime),
        **{key: metadata.get(key) for key in METADATA_KEYS},
    }


def main() -> int:
    arguments = sys.argv[1:]
    root = arguments[arguments.index("--root") + 1] if "--root" in arguments else os.environ.get("APPWORLD_ROOT", ".")
    root = os.path.abspath(root)

    # Keep the protocol on the real stdout and send every other print (AppWorld's included) to stderr.
    protocol_out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", newline="\n")
    sys.stdout = sys.stderr
    protocol_in = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")

    def send(payload: dict[str, Any]) -> None:
        protocol_out.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        protocol_out.flush()

    os.environ["APPWORLD_ROOT"] = root
    try:
        import appworld

        appworld.update_root(root)
        patched = _load_shim().apply()
        from appworld.environment import AppWorld
    except Exception:
        send({"ok": False, "event": "ready", "error": traceback.format_exc()})
        return 1
    send({"ok": True, "event": "ready", "appworld_version": appworld.__version__, "root": root, "patched": patched})

    world: Any = None
    for line in protocol_in:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            command = request["cmd"]
            if command == "quit":
                break
            if command == "open":
                if world is not None:
                    world.close()
                    world = None
                options = {key: request[key] for key in OPEN_OPTIONS if request.get(key) is not None}
                world = AppWorld(task_id=request["task_id"], **options)
                send({"ok": True, "task": _task_summary(world.task)})
            elif command == "close":
                if world is not None:
                    world.close()
                    world = None
                send({"ok": True})
            elif world is None:
                send({"ok": False, "error": f"no task is open (command: {command})"})
            elif command == "execute":
                try:
                    output = world.execute(request["code"])
                except Exception as error:  # for example an Ellipsis passed to an API breaks AppWorld's call logger
                    output = f"Execution failed. Traceback:\n{type(error).__name__}: {str(error)[:500]}"
                send({"ok": True, "output": output, "task_completed": bool(world.task_completed())})
            elif command == "evaluate":
                send({"ok": True, "evaluation": world.evaluate().to_dict()})
            elif command == "reference_solution":
                code = world.task.ground_truth.compiled_solution_code + "\nsolution(apis, requester)"
                send({"ok": True, "code": code})
            else:
                send({"ok": False, "error": f"unknown command: {command}"})
        except Exception:
            send({"ok": False, "error": traceback.format_exc()})
    if world is not None:
        try:
            world.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
