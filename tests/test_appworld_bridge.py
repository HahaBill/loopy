"""End-to-end check of the AppWorld bridge and the agent loop, with no model.

A scripted "model" that replays the benchmark's own solution must pass AppWorld's checker, and one that
does nothing must fail. Skipped when AppWorld's environment or data is not installed (see the README).
"""

import pytest

from loopy.agent.llm import ModelSpec, ScriptedChat
from loopy.agent.react import classify_failure, run_task
from loopy.eval.bridge import REPO_ROOT, AppWorldBridge, default_appworld_python

pytestmark = pytest.mark.skipif(
    not default_appworld_python().exists() or not (REPO_ROOT / "data" / "datasets" / "dev.txt").exists(),
    reason="AppWorld is not installed in .venv-appworld or its data is missing",
)

TASK_ID = "50e1ac9_1"  # the first dev task
SPEC = ModelSpec(key="scripted", role="small", name="scripted")


@pytest.fixture(scope="module")
def bridge():
    with AppWorldBridge() as running:
        yield running


def test_worker_reports_ready_and_task_metadata(bridge):
    assert bridge.info["ok"] and bridge.info["appworld_version"]
    task = bridge.open_task(TASK_ID, experiment_name="test_bridge")
    assert task.id == TASK_ID and task.scenario_id == "50e1ac9" and task.version == 1
    assert task.instruction and task.supervisor["email"] and task.difficulty in (1, 2, 3)
    assert bridge.execute("print(1 + 2)").output.strip() == "3"
    bridge.close_task()


def test_reference_solution_passes_and_doing_nothing_fails(bridge):
    task = bridge.open_task(TASK_ID, experiment_name="test_bridge", ground_truth_mode="full")
    solution = bridge.reference_solution()
    model = ScriptedChat(SPEC, [solution])
    trace = run_task(bridge, model, task.instruction, task.supervisor, max_steps=3, forecast=False)
    evaluation = bridge.evaluate()
    bridge.close_task()
    assert trace.task_completed and trace.stop_reason == "completed"
    assert evaluation["success"] is True
    assert classify_failure(True, trace) is None

    task = bridge.open_task(TASK_ID, experiment_name="test_bridge")
    model = ScriptedChat(SPEC, ["apis.supervisor.complete_task()"])
    trace = run_task(bridge, model, task.instruction, task.supervisor, max_steps=3, forecast=False)
    evaluation = bridge.evaluate()
    bridge.close_task()
    assert trace.task_completed and evaluation["success"] is False
    assert classify_failure(False, trace) == "quality"


def test_runaway_code_is_stopped_by_the_timeout(bridge):
    bridge.open_task(TASK_ID, experiment_name="test_bridge", timeout_seconds=2)
    output = bridge.execute("counter = 0\nwhile True:\n    counter += 1").output
    still_alive = bridge.execute("print(6 * 7)").output
    bridge.close_task()
    assert "timed out" in output
    assert still_alive.strip() == "42"
