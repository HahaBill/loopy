"""Connectivity check: send one tiny prompt to each named model and print what came back and what it cost.

    .venv/Scripts/python.exe experiments/check_models.py qwen3-30b-a3b glm-5.3

Uses the same config and model wrapper as the pilot. A check costs a fraction of a cent on a hosted model;
it is still written to the spend ledger so the ledger stays complete.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loopy.agent.llm import ModelSpec, PydanticAIChat, load_env_file
from loopy.eval.bridge import REPO_ROOT
from loopy.eval.runlog import ledger_add

LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+", help="keys under 'models' in the config")
    parser.add_argument("--config", default=str(REPO_ROOT / "experiments" / "pilot" / "config.json"))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    load_env_file(REPO_ROOT / ".env")
    failures = 0
    for key in args.models:
        spec = ModelSpec.from_dict(key, {**config["models"][key], "max_tokens": 200})
        try:
            reply = PydanticAIChat(spec, retries=1).complete(
                [{"role": "user", "content": "Reply with exactly this Python line and nothing else: print('ready')"}]
            )
        except Exception as error:
            failures += 1
            print(f"{key}: FAILED {type(error).__name__}: {str(error)[:300]}")
            continue
        cost = spec.cost_usd(reply.input_tokens, reply.output_tokens)
        if cost > 0:
            ledger_add(LEDGER, spec.provider, cost, "check_models", key)
        print(f"{key}: ok | model_id {reply.model_id} | in {reply.input_tokens} out {reply.output_tokens} tokens | "
              f"{reply.seconds:.1f}s | ${cost:.6f} | finish {reply.finish_reason} | "
              f"thinking {len(reply.thinking)} chars | reply {reply.text.strip()[:80]!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
