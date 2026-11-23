"""Build a coach note that is checked before it counts, the same way a compiled workflow is.

The first pilot built coach notes in one shot and never tested them, while compiled workflows were checked on
version 1 and repaired up to twice. That made coach look worse than it may be. Here a note counts as built
only if the small model, given the note, passes version 1 again in a fresh copy of the apps. If it fails,
the cloud model sees the new failed run next to its own passing run and revises the note, up to
--max-repairs times. A note that never passes is a failed build; its cost still counts and Loopy would fall
back to renting. This is the proposal's own rule ("test each on a new version of the task first, else use
the cloud model") and the practice of AgentBrew and D-Skill.

    .venv/Scripts/python.exe experiments/pilot/build_coach_checked.py --run-name pilot2 \
        --small-model <key> --cloud-model <key> --skills-dir results/pilot/pilot2/raw_large/skills/<key>

Needs the small_alone and cloud_alone runs of the learning version in results/pilot/<run-name>/.
Appends one row per scenario to teach.jsonl with kind "coach_checked".
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from loopy.agent.llm import ModelSpec, PydanticAIChat, load_env_file
from loopy.agent.react import Budget, CostCapReached, run_task
from loopy.eval.bridge import REPO_ROOT, AppWorldBridge
from loopy.eval.runlog import append_jsonl, git_state, ledger_add, ledger_total, now_et, read_jsonl
from loopy.skills.coach import build_coach_prompt, build_revision_prompt, parse_coach_reply
from loopy.skills.teach import complete_uncut

HERE = Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"
KIND = "coach_checked"


def find_record(records: list[dict], task_id: str, condition: str, model_key: str) -> dict | None:
    matches = [record for record in records if record["task_id"] == task_id
               and record["condition"] == condition and record["model_key"] == model_key]
    return matches[-1] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--small-model", required=True)
    parser.add_argument("--cloud-model", required=True)
    parser.add_argument("--skills-dir", required=True)
    parser.add_argument("--config", default=str(HERE / "config.json"))
    parser.add_argument("--learn-version", type=int, default=1)
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--teach-max-tokens", type=int, default=16000)
    parser.add_argument("--max-usd", type=float, default=None)
    parser.add_argument("--label", default=None)
    parser.add_argument("--source-run", default=None,
                        help="another run folder that may hold the small_alone or cloud_alone runs to learn from")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    load_env_file(REPO_ROOT / ".env")
    teacher_spec = dataclasses.replace(ModelSpec.from_dict(args.cloud_model, config["models"][args.cloud_model]),
                                       max_tokens=args.teach_max_tokens)
    student_spec = ModelSpec.from_dict(args.small_model, config["models"][args.small_model])
    if teacher_spec.role != "cloud" or student_spec.role != "small":
        raise SystemExit("need a 'cloud' model as teacher and a 'small' model as student")
    scenarios = json.loads((REPO_ROOT / config["scenario_file"]).read_text(encoding="utf-8"))["chosen"]

    run_dir = REPO_ROOT / "results" / "pilot" / args.run_name
    raw_dir = run_dir / "raw_large"
    skills_dir = Path(args.skills_dir)
    teach_path = run_dir / "teach.jsonl"
    source_dirs = [run_dir] + ([REPO_ROOT / "results" / "pilot" / args.source_run] if args.source_run else [])
    records = [record for folder in source_dirs for record in read_jsonl(folder / "runs.jsonl")]
    done = {row["scenario_id"] for row in read_jsonl(teach_path)
            if row["kind"] == KIND and row["teacher_model_key"] == args.cloud_model
            and row["small_model_key"] == args.small_model}

    provider = teacher_spec.provider
    max_usd = args.max_usd if args.max_usd is not None else config.get("max_usd_per_invocation")
    ledger_cap = (config.get("ledger_caps_usd") or {}).get(provider)
    if ledger_cap is not None:
        remaining = ledger_cap - ledger_total(LEDGER, provider)
        if remaining <= 0:
            raise SystemExit(f"{provider}: the ${ledger_cap:.2f} cap is used up. Stopping.")
        max_usd = remaining if max_usd is None else min(max_usd, remaining)
    budget = Budget(max_usd=max_usd)
    student = PydanticAIChat(student_spec)
    git = git_state()
    ledgered = 0.0

    try:
        with AppWorldBridge(stderr_path=raw_dir / "appworld_worker.log") as bridge:
            for item in scenarios:
                scenario_id = item["scenario_id"]
                if scenario_id in done:
                    continue
                if ledger_cap is not None and ledger_total(LEDGER, provider) >= ledger_cap:
                    print("provider cap reached; stopping", flush=True)
                    break
                task_id = f"{scenario_id}_{args.learn_version}"
                small = find_record(records, task_id, "small_alone", args.small_model)
                cloud = find_record(records, task_id, "cloud_alone", args.cloud_model)
                if small is None or cloud is None:
                    raise SystemExit(f"{task_id}: needs the small_alone and cloud_alone runs first")
                row = {"run_name": args.run_name, "label": args.label, "time": now_et(), "scenario_id": scenario_id,
                       "learn_task_id": task_id, "kind": KIND, "teacher_model_key": args.cloud_model,
                       "teacher_model_name": teacher_spec.name, "small_model_key": args.small_model,
                       "git_commit": git["commit"], "command": " ".join(sys.argv)}
                if small["success"] or not cloud["success"]:
                    status = "skipped_small_passed" if small["success"] else "skipped_cloud_failed"
                    append_jsonl(teach_path, {**row, "status": status, "validated": False, "attempts": 0,
                                              "requests": 0, "cloud_calls": 0, "cost_usd": 0.0})
                    print(f"{scenario_id}: {status}", flush=True)
                    continue

                def raw(condition: str, model_key: str, repeat: int) -> dict:
                    name = f"{condition}__{model_key}__{task_id}__r{repeat}.json"
                    path = next(folder / "raw_large" / name for folder in source_dirs
                                if (folder / "raw_large" / name).exists())
                    return json.loads(path.read_text(encoding="utf-8"))

                small_raw = raw("small_alone", args.small_model, small["repeat"])
                cloud_raw = raw("cloud_alone", args.cloud_model, cloud["repeat"])
                messages = [{"role": "user", "content": build_coach_prompt(
                    small_raw["instruction"], small_raw["steps"], cloud_raw["steps"])}]
                teacher_cost = student_cost = 0.0
                teacher_calls = student_requests = cut_off_requests = 0
                attempts: list[dict] = []
                validated, note, first = False, None, None
                for attempt in range(1, args.max_repairs + 2):
                    reply, usage = complete_uncut(teacher_spec, messages, budget)
                    teacher_cost += usage["cost_usd"]
                    teacher_calls += usage["requests"]
                    cut_off_requests += usage["cut_off_requests"]
                    try:
                        note = parse_coach_reply(reply.text)
                    except ValueError as error:
                        attempts.append({"attempt": attempt, "reply": reply.text, "parse_error": str(error)})
                        messages += [{"role": "assistant", "content": reply.text},
                                     {"role": "user", "content": f"Your reply could not be used: {error}. "
                                                                  "Reply again in exactly the required format."}]
                        continue
                    first = first or note
                    task = bridge.open_task(task_id, experiment_name=f"{args.run_name}__coach_check__"
                                                                     f"{args.small_model}__a{attempt}",
                                            timeout_seconds=config["appworld_timeout_seconds"])
                    trace = run_task(bridge, student, task.instruction, task.supervisor,
                                     max_steps=config["max_steps"], output_char_limit=config["output_char_limit"],
                                     guidance=note.guidance(), forecast=False, budget=budget)
                    passed = bool(bridge.evaluate()["success"])
                    bridge.close_task()
                    totals = trace.totals()
                    student_cost += totals["cost_usd"]
                    student_requests += int(totals["requests"])
                    attempts.append({"attempt": attempt, "reply": reply.text, "note": note.note, "passed": passed,
                                     "stop_reason": trace.stop_reason, "n_steps": len(trace.steps),
                                     "steps": [asdict(step) for step in trace.steps]})
                    if passed:
                        validated = True
                        break
                    if trace.stop_reason == "cost_cap":
                        break
                    messages += [{"role": "assistant", "content": reply.text},
                                 {"role": "user", "content": build_revision_prompt(
                                     [asdict(step) for step in trace.steps])}]

                folder = skills_dir / scenario_id
                folder.mkdir(parents=True, exist_ok=True)
                if validated and note is not None:
                    (folder / "coach_checked_note.txt").write_text(note.guidance(), encoding="utf-8")
                elif note is not None:  # kept for the record; not used as a skill
                    (folder / "coach_checked_FAILED_last_note.txt").write_text(note.guidance(), encoding="utf-8")
                (folder / f"coach_checked_log_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
                    json.dumps({"prompt": messages[0]["content"], "attempts": attempts}, indent=2,
                               ensure_ascii=False), encoding="utf-8")
                append_jsonl(teach_path, {
                    **row, "status": "built" if validated else "failed_validation", "validated": validated,
                    "attempts": len(attempts), "requests": teacher_calls, "cloud_calls": teacher_calls,
                    "teacher_cost_usd": round(teacher_cost, 6), "student_cost_usd": round(student_cost, 6),
                    "student_requests": student_requests, "cut_off_requests": cut_off_requests, "cost_usd": round(teacher_cost + student_cost, 6),
                    "divergence_step": first.divergence_step if first else None,
                    "failure_kind": first.failure_kind if first else None,
                })
                print(f"{scenario_id}: coach_checked {'built' if validated else 'FAILED'} after "
                      f"{len(attempts)} attempt(s) | teacher ${teacher_cost:.4f} + student ${student_cost:.4f}",
                      flush=True)
                if budget.spent_usd > ledgered:
                    ledger_add(LEDGER, provider, budget.spent_usd - ledgered, args.run_name,
                               f"build_coach_checked {args.small_model} {scenario_id}")
                    ledgered = budget.spent_usd
    except CostCapReached as error:
        print(f"cost cap reached: {error}")
    finally:
        if budget.spent_usd > ledgered:
            ledger_add(LEDGER, provider, budget.spent_usd - ledgered, args.run_name,
                       f"build_coach_checked {args.cloud_model} for {args.small_model}")
    print(f"spent ${budget.spent_usd:.4f} | {provider} ledger total ${ledger_total(LEDGER, provider):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
