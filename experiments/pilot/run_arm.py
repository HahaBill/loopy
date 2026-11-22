"""Run one arm of the pilot: one condition, one model, a list of AppWorld tasks.

    .venv/Scripts/python.exe experiments/pilot/run_arm.py --run-name pilot1 --condition small_alone --model <key>

Conditions
    small_alone   the small model with AppWorld's minimal ReAct prompt, plus the "will you fail?" forecast
    cloud_alone   the same loop with the bigger model (renting)
    coach         the small model plus a coach note written once by the bigger model   (needs --skills-dir)
    compile       the small model plus a saved workflow function it only has to call   (needs --skills-dir)

Every finished task run appends one line to results/pilot/<run-name>/runs.jsonl (ids, counts, tokens,
dollars, timings; no task text). The full trajectory goes to results/pilot/<run-name>/raw_large/, which is
never committed. A run already in runs.jsonl is skipped, never redone or overwritten.

Spending: a hard cap per invocation (--max-usd, checked before every model request) and a cap per provider
across all invocations (the ledger in results/spend_ledger.jsonl against `ledger_caps_usd` in the config).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from loopy.agent.llm import ModelSpec, PydanticAIChat, load_env_file
from loopy.agent.react import Budget, classify_failure, run_task
from loopy.eval.bridge import REPO_ROOT, AppWorldBridge
from loopy.eval.runlog import (
    append_jsonl,
    completed_keys,
    environment_summary,
    git_state,
    ledger_add,
    ledger_total,
    now_et,
    read_jsonl,
    sha256_file,
    summarize,
    write_new_json,
)

HERE = Path(__file__).resolve().parent
CONDITIONS = ("small_alone", "cloud_alone", "coach", "coach_checked", "compile")
LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"


def pick_tasks(args: argparse.Namespace, config: dict) -> list[str]:
    if args.tasks:
        task_ids = [item.strip() for item in args.tasks.split(",") if item.strip()]
    else:
        scenarios = json.loads((REPO_ROOT / config["scenario_file"]).read_text(encoding="utf-8"))
        task_ids = [task_id for item in scenarios["chosen"] for task_id in item["task_ids"]]
    if args.versions:
        wanted = {int(item) for item in args.versions.split(",")}
        task_ids = [task_id for task_id in task_ids if int(task_id.rsplit("_", 1)[1]) in wanted]
    if args.only_failed_of:
        failed = {
            record["task_id"]
            for record in read_jsonl(args.only_failed_of)
            if not record["success"]
            and record["condition"] == args.failed_condition
            and (args.failed_model is None or record["model_key"] == args.failed_model)
        }
        task_ids = [task_id for task_id in task_ids if task_id in failed]
    return task_ids


def load_skill(skills_dir: Path, condition: str, scenario_id: str) -> tuple[str | None, str | None]:
    """(guidance text, code to define in the environment first) for a coach or compile run."""
    folder = skills_dir / scenario_id
    if condition == "coach":
        return (folder / "coach_note.txt").read_text(encoding="utf-8"), None
    if condition == "coach_checked":
        return (folder / "coach_checked_note.txt").read_text(encoding="utf-8"), None
    if condition == "compile":
        return (folder / "compiled_guidance.txt").read_text(encoding="utf-8"), (
            folder / "compiled_workflow.py"
        ).read_text(encoding="utf-8")
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--condition", required=True, choices=CONDITIONS)
    parser.add_argument("--model", required=True, help="a key under 'models' in the config")
    parser.add_argument("--config", default=str(HERE / "config.json"))
    parser.add_argument("--tasks", default=None, help="comma-separated task ids (default: the chosen scenarios)")
    parser.add_argument("--versions", default=None, help="keep only these versions, for example 2,3")
    parser.add_argument("--only-failed-of", default=None, help="a runs.jsonl; keep only tasks that failed there")
    parser.add_argument("--failed-condition", default="small_alone")
    parser.add_argument("--failed-model", default=None)
    parser.add_argument("--skills-dir", default=None, help="folder with <scenario>/coach_note.txt and so on")
    parser.add_argument("--repeat", type=int, default=1, help="repeat index recorded with each run")
    parser.add_argument("--max-usd", type=float, default=None, help="hard cap for this invocation")
    parser.add_argument("--no-forecast", action="store_true")
    parser.add_argument("--label", default=None, help="written into every record, for example \"stand-in models\"")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and stop; no model is called")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    load_env_file(REPO_ROOT / ".env")
    spec = ModelSpec.from_dict(args.model, config["models"][args.model])
    expected_role = "cloud" if args.condition == "cloud_alone" else "small"
    if spec.role != expected_role:
        raise SystemExit(f"condition {args.condition} needs a '{expected_role}' model; {args.model} is '{spec.role}'")
    if args.condition in ("coach", "coach_checked", "compile") and not args.skills_dir:
        raise SystemExit(f"condition {args.condition} needs --skills-dir")

    task_ids = pick_tasks(args, config)
    run_dir = REPO_ROOT / "results" / "pilot" / args.run_name
    runs_path = run_dir / "runs.jsonl"
    raw_dir = run_dir / "raw_large"
    done = completed_keys(runs_path)
    todo = [task_id for task_id in task_ids if (task_id, args.condition, args.model, args.repeat) not in done]

    provider = spec.provider
    max_usd = args.max_usd if args.max_usd is not None else config.get("max_usd_per_invocation")
    ledger_cap = (config.get("ledger_caps_usd") or {}).get(provider)
    spent_before = ledger_total(LEDGER, provider)
    if ledger_cap is not None:
        remaining = ledger_cap - spent_before
        if remaining <= 0 and spec.usd_per_mtok_in + spec.usd_per_mtok_out > 0:
            raise SystemExit(f"{provider}: ${spent_before:.2f} already spent of the ${ledger_cap:.2f} cap. Stopping.")
        max_usd = remaining if max_usd is None else min(max_usd, remaining)
    budget = Budget(max_usd=max_usd)

    print(f"run {args.run_name} | {args.condition} | {args.model} = {spec.name} via {provider}")
    print(f"tasks: {len(todo)} to run, {len(task_ids) - len(todo)} already done -> {', '.join(todo) or '-'}")
    print(f"cap for this invocation: {'none' if max_usd is None else f'${max_usd:.2f}'}"
          f" | {provider} ledger so far: ${spent_before:.4f}")
    if args.dry_run or not todo:
        return 0

    git = git_state()
    started_stamp = time.strftime("%Y%m%d_%H%M%S")
    prompt_path = REPO_ROOT / "src" / "loopy" / "agent" / "prompts" / "appworld_minimal_react.txt"
    meta = {
        "run_name": args.run_name,
        "label": args.label,
        "started": now_et(),
        "command": " ".join(sys.argv),
        "condition": args.condition,
        "model_key": args.model,
        "model": {key: value for key, value in asdict(spec).items()},
        "provider": provider,
        "task_ids": todo,
        "repeat": args.repeat,
        "settings": {key: config[key] for key in ("max_steps", "output_char_limit", "appworld_timeout_seconds")},
        "max_usd": max_usd,
        "git": git,
        "environment": environment_summary(),
        "sha256": {
            "config": sha256_file(config_path),
            "prompt": sha256_file(prompt_path),
            "run_arm.py": sha256_file(Path(__file__).resolve()),
            "react.py": sha256_file(REPO_ROOT / "src" / "loopy" / "agent" / "react.py"),
            "scenarios": sha256_file(REPO_ROOT / config["scenario_file"]),
        },
    }
    meta_path = run_dir / f"meta_{started_stamp}_{args.condition}_{args.model}.json"
    write_new_json(meta_path, meta)

    model = PydanticAIChat(spec)
    skills_dir = Path(args.skills_dir) if args.skills_dir else None
    new_records = []
    meta_appworld: dict = {}
    ledgered = 0.0
    experiment_name = f"{args.run_name}__{args.condition}__{args.model}__r{args.repeat}"
    try:
        with AppWorldBridge(stderr_path=run_dir / "raw_large" / "appworld_worker.log") as bridge:
            meta_appworld = {key: bridge.info.get(key) for key in ("appworld_version", "patched")}
            for task_id in todo:
                scenario_id = task_id.rsplit("_", 1)[0]
                guidance, preload = (None, None)
                if skills_dir is not None:
                    try:
                        guidance, preload = load_skill(skills_dir, args.condition, scenario_id)
                    except FileNotFoundError:
                        print(f"  {task_id}: no {args.condition} skill was built for {scenario_id}; skipped", flush=True)
                        continue
                if ledger_cap is not None and ledger_total(LEDGER, provider) >= ledger_cap:
                    print("  provider cap reached; stopping this invocation", flush=True)
                    break
                started, clock = now_et(), time.perf_counter()
                task = bridge.open_task(task_id, experiment_name=experiment_name,
                                        timeout_seconds=config["appworld_timeout_seconds"])
                trace = run_task(
                    bridge, model, task.instruction, task.supervisor,
                    max_steps=config["max_steps"], output_char_limit=config["output_char_limit"],
                    guidance=guidance, preload_code=preload, forecast=not args.no_forecast, budget=budget,
                )
                evaluation = bridge.evaluate()
                bridge.close_task()
                wall_seconds = time.perf_counter() - clock
                success = bool(evaluation["success"])
                totals = trace.totals()
                record = {
                    "run_name": args.run_name,
                    "label": args.label,
                    "started": started,
                    "finished": now_et(),
                    "task_id": task_id,
                    "scenario_id": scenario_id,
                    "version": task.version,
                    "difficulty": task.difficulty,
                    "condition": args.condition,
                    "model_key": args.model,
                    "model_name": spec.name,
                    "model_role": spec.role,
                    "provider": provider,
                    "runs_locally": model.runs_locally,
                    "repeat": args.repeat,
                    "seed": spec.seed,
                    "temperature": spec.temperature,
                    "success": success,
                    "failure_type": classify_failure(success, trace),
                    "stop_reason": trace.stop_reason,
                    "task_completed": trace.task_completed,
                    "n_steps": len(trace.steps),
                    "n_execution_failures": trace.n_execution_failures,
                    "n_replies_without_code": sum(1 for step in trace.steps if not step.had_code),
                    "forecast_p_fail": trace.forecast.probability_of_failure if trace.forecast else None,
                    "requests": int(totals["requests"]),
                    "cloud_calls": int(totals["requests"]) if spec.role == "cloud" else 0,
                    "input_tokens": int(totals["input_tokens"]),
                    "output_tokens": int(totals["output_tokens"]),
                    "cost_usd": round(totals["cost_usd"], 6),
                    "model_seconds": round(totals["model_seconds"], 2),
                    "wall_seconds": round(wall_seconds, 2),
                    "checker_tests_passed": len(evaluation.get("passes", [])),
                    "checker_tests_failed": len(evaluation.get("failures", [])),
                    "error": trace.error,
                    "git_commit": git["commit"],
                    "meta_file": meta_path.name,
                }
                raw_path = raw_dir / f"{args.condition}__{args.model}__{task_id}__r{args.repeat}.json"
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                with open(raw_path, "x", encoding="utf-8") as handle:
                    json.dump({
                        "record": record,
                        "instruction": task.instruction,
                        "guidance": guidance,
                        "preload_code": preload,
                        "preload_output": trace.preload_output,
                        "forecast": asdict(trace.forecast) if trace.forecast else None,
                        "steps": [asdict(step) for step in trace.steps],
                        "messages": trace.messages,
                        "evaluation": evaluation,
                    }, handle, indent=2, ensure_ascii=False, default=str)
                append_jsonl(runs_path, record)
                if budget.spent_usd > ledgered:
                    ledger_add(LEDGER, provider, budget.spent_usd - ledgered, args.run_name,
                               f"{args.condition} {args.model} {task_id}")
                    ledgered = budget.spent_usd
                new_records.append(record)
                p_fail = record["forecast_p_fail"]
                print(f"  {task_id} d{task.difficulty}: {'PASS' if success else 'FAIL (' + str(record['failure_type']) + ')'}"
                      f" | {record['stop_reason']} | steps {record['n_steps']} | p_fail "
                      f"{'-' if p_fail is None else f'{p_fail:.2f}'} | ${record['cost_usd']:.4f} | {wall_seconds:.0f}s",
                      flush=True)
                if trace.stop_reason == "cost_cap":
                    print("  cost cap reached; stopping this invocation")
                    break
    finally:
        # Record what this invocation spent even if it crashed, so the provider cap stays honest.
        if budget.spent_usd > ledgered:
            ledger_add(LEDGER, provider, budget.spent_usd - ledgered, args.run_name,
                       f"{args.condition} {args.model}")

    summary = summarize(new_records)
    finish = {"finished": now_et(), "summary": summary, "appworld": meta_appworld,
              "ledger_total_after": round(ledger_total(LEDGER, provider), 6)}
    write_new_json(meta_path.with_name(meta_path.stem + "_finish.json"), finish)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
