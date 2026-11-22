"""Windows compatibility for AppWorld. Runs inside the AppWorld environment, never inside the Loopy app.

AppWorld 0.1.3 is developed on Linux and macOS. On Windows two things break:

1. `appworld.common.utils.timeout_call` stops runaway agent code with `signal.SIGALRM`, which Windows does
   not have. Every `world.execute(...)` goes through it, so without a replacement no task can run.
2. `appworld.common.utils.Timer(bypass_freezegun=True)` asks for `winloop.WinLoopPolicy`, which newer
   winloop releases call `EventLoopPolicy`.

`apply()` replaces the first with a version built on SIGINT (the one signal Windows can deliver to the main
thread, and one that also wakes `time.sleep`) and aliases the second. The raised exception, its message and
the frame it is raised in are the same as on Linux, so AppWorld's own handling of timeouts is unchanged.

Nothing here touches how tasks are set up or graded. `experiments/appworld_env_check.py` runs AppWorld's own
unit tests and its end-to-end task validation with this shim applied; trust results from a Windows run only
if that check passed on the same machine.

This file imports only the standard library at module level so that it can be loaded by path.
"""

from __future__ import annotations

import os
import signal
import threading
from typing import Any, Callable

_APPLIED = False


def _timeout_call_windows(utils_module: Any) -> Callable[..., Any]:
    def timeout_call(
        function: Callable[..., Any],
        timeout_seconds: int | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if timeout_seconds is None:
            return function(*args, **kwargs)
        timeout_seconds = int(timeout_seconds)
        timeout_message = f"Function {function.__name__} execution timed out after {timeout_seconds} seconds."
        fired = threading.Event()
        previous_handler: Any = None

        def handler(signum: int, frame: Any) -> None:
            if fired.is_set():
                raise utils_module.TimeoutError(timeout_message)
            # A real Ctrl+C while the call is running: behave as before.
            if callable(previous_handler):
                previous_handler(signum, frame)
                return
            raise KeyboardInterrupt

        def fire() -> None:
            fired.set()
            signal.raise_signal(signal.SIGINT)

        previous_handler = signal.signal(signal.SIGINT, handler)
        timer = threading.Timer(timeout_seconds, fire)
        timer.daemon = True
        timer.start()
        try:
            result = function(*args, **kwargs)
        except utils_module.TimeoutError as exception:
            raise Exception(timeout_message) from exception
        finally:
            timer.cancel()
            signal.signal(signal.SIGINT, previous_handler)
        return result

    return timeout_call


def apply() -> dict[str, bool]:
    """Patch AppWorld for Windows. Does nothing on other systems. Returns what was patched."""
    global _APPLIED
    patched = {"timeout_call": False, "winloop_policy": False}
    if os.name != "nt" or _APPLIED:
        return patched

    import appworld.common.utils as utils_module
    import appworld.environment as environment_module

    if not hasattr(signal, "SIGALRM"):
        replacement = _timeout_call_windows(utils_module)
        utils_module.timeout_call = replacement
        environment_module.timeout_call = replacement
        patched["timeout_call"] = True

    try:
        import winloop

        if not hasattr(winloop, "WinLoopPolicy") and hasattr(winloop, "EventLoopPolicy"):
            winloop.WinLoopPolicy = winloop.EventLoopPolicy
            patched["winloop_policy"] = True
    except ImportError:
        pass

    _APPLIED = True
    return patched
