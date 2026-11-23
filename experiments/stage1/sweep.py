"""Find the work the stage 1 runner has to redo because of an infrastructure fault. Prints a comma-separated list.

    sweep.py infra --condition small_alone --model gemma-3-27b
        tasks whose latest run ended in `model_error` (the provider or the bridge failed, the model did not)
        and that have not been rerun yet. The rerun is recorded as repeat 2; repeat 1 stays in the file.

    sweep.py voided
        function builds that failed with at least one reply cut off by the output limit before the Nov 22 fix.
        Those builds never got their protocol budget of three real attempts, so they are redone from the start.
        A build that failed on real attempts only is left as failed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import read_jsonl

RUN_DIR = REPO_ROOT / "results" / "pilot" / "stage1"


def infra_tasks(condition: str, model: str) -> list[str]:
    latest: dict[str, dict] = {}
    for row in read_jsonl(RUN_DIR / "runs.jsonl"):
        if row["condition"] == condition and row["model_key"] == model:
            if row["task_id"] not in latest or row["repeat"] >= latest[row["task_id"]]["repeat"]:
                latest[row["task_id"]] = row
    return sorted(task for task, row in latest.items() if row["stop_reason"] == "model_error" and row["repeat"] == 1)


def had_cut_off_reply(scenario_id: str) -> bool:
    for path in sorted((RUN_DIR / "raw_large" / "skills" / "shared" / scenario_id).glob("build_log_*.json")):
        log = json.loads(path.read_text(encoding="utf-8"))
        if any(not attempt.get("reply", "").strip() for attempt in log.get("compile", {}).get("attempts", [])):
            return True
    return False


def voided_builds() -> list[str]:
    latest = {row["scenario_id"]: row for row in read_jsonl(RUN_DIR / "teach.jsonl")
              if row["kind"] == "compile" and row["small_model_key"] == "shared"}
    return sorted(scenario for scenario, row in latest.items()
                  if row["status"] == "failed_validation" and not row.get("cutoff_fix") and had_cut_off_reply(scenario))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("infra", "voided"))
    parser.add_argument("--condition")
    parser.add_argument("--model")
    args = parser.parse_args()
    print(",".join(infra_tasks(args.condition, args.model) if args.what == "infra" else voided_builds()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
