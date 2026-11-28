"""Pilot step 3, first half: build a coach note and a compiled workflow from version 1 of each scenario.

For each pilot scenario where the small model failed the learning version and the bigger model passed it:

- coach:   one request to the bigger model, which reads both runs and writes a short note;
- compile: one request for a reusable function, then a check that the function solves the same task again
           in a fresh copy of the apps (AppWorld's checker stands in for the user saying "that's right").
           A failed check gets up to --max-repairs more tries. A compile that never passes is recorded as
           failed, with its cost.

    .venv/Scripts/python.exe experiments/pilot/build_skills.py --run-name pilot1 \
        --small-model <key> --cloud-model <key>

Needs the small_alone and cloud_alone runs of the learning version in results/pilot/<run-name>/.
Writes one line per attempt to results/pilot/<run-name>/teach.jsonl (ids, counts, dollars) and the note and
function themselves to raw_large/skills/<scenario>/ (not committed: they are derived from AppWorld tasks).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

from loopy.agent.llm import ModelSpec, load_env_file
from loopy.agent.react import Budget, CostCapReached
from loopy.eval.bridge import REPO_ROOT, AppWorldBridge
from loopy.eval.runlog import append_jsonl, git_state, ledger_total, now_et, read_jsonl
from loopy.skills.coach import build_coach_prompt, parse_coach_reply
from loopy.skills.compile import build_compile_prompt, build_repair_prompt, parse_compile_reply
from loopy.skills.teach import PaidRequestFailed, cap_stop_status, complete_uncut, run_check, stale_skips, stop_status

HERE = Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"
COMPILE_PENDING_GLOB = "compile_PENDING_*.json"
COMPILE_RESUME_KEYS = ("messages", "attempts", "usages", "last_error")
IDENTITY_KEYS = ("teacher_model_key", "small_model_key", "learn_task_id")


def compile_pending_state(folder: Path, expected: dict | None = None) -> dict | None:
    """What an interrupted function build of this scenario already did and paid for (review item 4).

    The same rule as the note builder: a build whose validation the bridge kept breaking writes a pending file and no
    row, and a restart goes on with the same conversation, the attempts already used and the spend already paid. Each
    pending file holds the whole state up to its interruption, so only the latest one is read.
    """
    logs = sorted(folder.glob(COMPILE_PENDING_GLOB))
    if not logs:
        return None
    state = json.loads(logs[-1].read_text(encoding="utf-8"))
    missing = [key for key in COMPILE_RESUME_KEYS if key not in state]
    if missing:
        raise SystemExit(f"{logs[-1]}: a pending function build without {missing}; it cannot be resumed. "
                         "Decide it by hand.")
    wrong = [key for key, value in (expected or {}).items() if key in state and state[key] != value]
    if wrong:
        raise SystemExit(f"{logs[-1]}: a pending function build for another {wrong} in this folder; it cannot be "
                         "resumed here. Decide it by hand.")
    return {**state, "file": logs[-1].name}


def retire_pending(folder: Path, pattern: str) -> None:
    """A build that now has its row is decided: its pending files are kept for the record but never resumed again."""
    for path in folder.glob(pattern):
        path.rename(path.with_name(path.name.replace("_PENDING_", "_RESUMED_")))


def find_record(records: list[dict], task_id: str, condition: str, model_key: str) -> dict | None:
    matches = [record for record in records if record["task_id"] == task_id
               and record["condition"] == condition and record["model_key"] == model_key]
    return matches[-1] if matches else None


def load_raw(raw_dir: Path, condition: str, model_key: str, task_id: str, repeat: int) -> dict:
    return json.loads((raw_dir / f"{condition}__{model_key}__{task_id}__r{repeat}.json").read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--small-model", required=True)
    parser.add_argument("--cloud-model", required=True)
    parser.add_argument("--config", default=str(HERE / "config.json"))
    parser.add_argument("--learn-version", type=int, default=1)
    parser.add_argument("--max-repairs", type=int, default=2)
    parser.add_argument("--max-usd", type=float, default=None)
    parser.add_argument("--label", default=None, help="written into every teach record")
    parser.add_argument("--teach-max-tokens", type=int, default=16000,
                        help="output limit for skill-writing requests; a model that thinks first needs room")
    parser.add_argument("--skills-dir", default=None, help="where notes and functions go (default: raw_large/skills)")
    parser.add_argument("--only", choices=("coach", "compile"), default=None, help="build just one kind")
    parser.add_argument("--no-student", action="store_true",
                        help="build functions for every scenario the cloud model passed; no student run needed")
    parser.add_argument("--retry-only", default=None, help="with --retry-compile: only these scenarios")
    parser.add_argument("--retry-compile", action="store_true",
                        help="try compile again where the last attempt did not pass; earlier rows are kept")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    load_env_file(REPO_ROOT / ".env")
    teacher_spec = ModelSpec.from_dict(args.cloud_model, config["models"][args.cloud_model])
    teacher_spec = dataclasses.replace(teacher_spec, max_tokens=args.teach_max_tokens)
    if args.no_student and args.only != "compile":
        raise SystemExit("--no-student needs --only compile")
    if teacher_spec.role != "cloud":
        raise SystemExit(f"{args.cloud_model} is not a 'cloud' model")
    scenarios = json.loads((REPO_ROOT / config["scenario_file"]).read_text(encoding="utf-8"))["chosen"]

    run_dir = REPO_ROOT / "results" / "pilot" / args.run_name
    raw_dir = run_dir / "raw_large"
    teach_path = run_dir / "teach.jsonl"
    records = read_jsonl(run_dir / "runs.jsonl")
    earlier = read_jsonl(teach_path)
    done = {(row["scenario_id"], row["kind"], row["teacher_model_key"], row["small_model_key"]) for row in earlier}
    if args.retry_compile:  # a compile whose last row did not pass may be tried again
        last = {(row["scenario_id"], row["kind"], row["teacher_model_key"], row["small_model_key"]): row
                for row in earlier}
        only = set(args.retry_only.split(",")) if args.retry_only else None
        retryable = {"failed_validation"} | ({"cut_off"} if only is not None else set())
        done -= {key for key, row in last.items() if key[1] == "compile" and row["status"] in retryable
                 and (only is None or key[0] in only)}

    def learned(condition: str, model_key: str, scenario_id: str) -> bool | None:
        record = find_record(records, f"{scenario_id}_{args.learn_version}", condition, model_key)
        return None if record is None else bool(record["success"])

    # A recorded skip is a decision only while the runs it was read from are still the latest ones.
    done -= stale_skips(earlier, learned)
    build_round = 1 + max((row.get("round", 1) for row in earlier), default=0) if earlier else 1

    provider = teacher_spec.provider
    max_usd = args.max_usd if args.max_usd is not None else config.get("max_usd_per_invocation")
    ledger_cap = (config.get("ledger_caps_usd") or {}).get(provider)
    if ledger_cap is not None:
        remaining = ledger_cap - ledger_total(LEDGER, provider)
        if remaining <= 0:
            raise SystemExit(f"{provider}: the ${ledger_cap:.2f} cap is used up. Stopping.")
        max_usd = remaining if max_usd is None else min(max_usd, remaining)
    budget = Budget(max_usd=max_usd, ledger=LEDGER, provider=provider, run_name=args.run_name,
                    note=f"build_skills {args.cloud_model}", ledger_cap=ledger_cap,
                    reserve_usd=(config.get("ledger_reserve_usd") or {}).get(provider, 0.0))
    git = git_state()

    def base_row(scenario_id: str, task_id: str, kind: str) -> dict:
        return {"run_name": args.run_name, "label": args.label, "time": now_et(), "scenario_id": scenario_id, "learn_task_id": task_id,
                "kind": kind, "teacher_model_key": args.cloud_model, "teacher_model_name": teacher_spec.name,
                "small_model_key": args.small_model, "git_commit": git["commit"], "command": " ".join(sys.argv),
                "round": build_round, "teach_max_tokens": args.teach_max_tokens, "cutoff_fix": True,
                "cutoff_fix_version": 3}

    def ask(messages: list[dict]) -> tuple[str, dict]:
        reply, usage = complete_uncut(teacher_spec, messages, budget)
        return reply.text, usage

    def total(usages: list[dict]) -> dict:
        n_requests = sum(usage["requests"] for usage in usages)
        return {"requests": n_requests, "cloud_calls": n_requests,
                "cut_off_requests": sum(usage["cut_off_requests"] for usage in usages),
                "input_tokens": sum(usage["input_tokens"] for usage in usages),
                "output_tokens": sum(usage["output_tokens"] for usage in usages),
                "cached_input_tokens": sum(usage.get("cached_input_tokens", 0) for usage in usages),
                "cost_usd": round(sum(usage["cost_usd"] for usage in usages), 6),
                "model_seconds": round(sum(usage["seconds"] for usage in usages), 2)}

    try:
        with AppWorldBridge(stderr_path=raw_dir / "appworld_worker.log") as bridge:
            for item in scenarios:
                scenario_id = item["scenario_id"]
                task_id = f"{scenario_id}_{args.learn_version}"
                small = ({"success": False, "repeat": 1} if args.no_student
                         else find_record(records, task_id, "small_alone", args.small_model))
                cloud = find_record(records, task_id, "cloud_alone", args.cloud_model)
                if small is None:
                    raise SystemExit(f"{task_id}: no small_alone run with {args.small_model}. Run that arm first.")
                skip = None
                if small["success"]:
                    skip = "skipped_small_passed"
                elif cloud is None:
                    raise SystemExit(f"{task_id}: no cloud_alone run with {args.cloud_model}. Run that arm first.")
                elif not cloud["success"]:
                    skip = "skipped_cloud_failed"
                if skip:
                    for kind in ("coach", "compile"):
                        if (scenario_id, kind, args.cloud_model, args.small_model) not in done:
                            append_jsonl(teach_path, {**base_row(scenario_id, task_id, kind), "status": skip,
                                                      "validated": False, **total([])})
                    print(f"{scenario_id}: {skip}")
                    continue

                small_raw = (None if args.no_student
                             else load_raw(raw_dir, "small_alone", args.small_model, task_id, small["repeat"]))
                cloud_raw = load_raw(raw_dir, "cloud_alone", args.cloud_model, task_id, cloud["repeat"])
                folder = (Path(args.skills_dir) if args.skills_dir else raw_dir / "skills") / scenario_id
                folder.mkdir(parents=True, exist_ok=True)
                build_log: dict = {}

                if args.only != "compile" and (scenario_id, "coach", args.cloud_model, args.small_model) not in done:
                    prompt = build_coach_prompt(small_raw["instruction"], small_raw["steps"], cloud_raw["steps"])
                    text, usage = ask([{"role": "user", "content": prompt}])
                    row = {**base_row(scenario_id, task_id, "coach"), **total([usage])}
                    if stop_status(usage):
                        row.update(status=stop_status(usage), validated=False,
                                   error=f"no whole reply: {stop_status(usage)}")
                    else:
                        try:
                            note = parse_coach_reply(text)
                            (folder / "coach_note.txt").write_text(note.guidance(), encoding="utf-8")
                            row.update(status="built", validated=False, divergence_step=note.divergence_step,
                                       failure_kind=note.failure_kind, note_lines=len(note.note.splitlines()))
                        except ValueError as error:
                            row.update(status="failed_parse", validated=False, error=str(error))
                    append_jsonl(teach_path, row)
                    build_log["coach"] = {"prompt": prompt, "reply": text}
                    print(f"{scenario_id}: coach {row['status']} | step {row.get('divergence_step')} | "
                          f"{row.get('failure_kind')} | ${row['cost_usd']:.4f}")

                untouched = False  # the spend limit came before this build's first request
                interrupted = None  # why the function's validation could not run, if it could not
                state = None
                if args.only != "coach" and (scenario_id, "compile", args.cloud_model, args.small_model) not in done:
                    identity = {"teacher_model_key": args.cloud_model, "small_model_key": args.small_model,
                                "learn_task_id": task_id}
                    state = compile_pending_state(folder, identity)
                    if state:  # an earlier start was interrupted during validation: go on from where it stopped
                        messages, attempts, usages = state["messages"], state["attempts"], state["usages"]
                        last_error = state["last_error"]
                        pending_text = state.get("pending_reply")  # paid for, its check broke: checked again, not bought
                        print(f"{scenario_id}: resuming the function build interrupted in {state['file']} after "
                              f"{len(attempts)} attempt(s) | already paid ${total(usages)['cost_usd']:.4f}")
                    else:
                        messages = [{"role": "user", "content": build_compile_prompt(cloud_raw["instruction"],
                                                                                     cloud_raw["steps"])}]
                        usages, attempts, last_error, pending_text = [], [], None, None
                    validated, status, pending_reply = False, "failed_validation", None
                    attempt = len(attempts) + 1
                    for attempt in range(len(attempts) + 1, args.max_repairs + 2):
                        if pending_text is not None:
                            text, pending_text = pending_text, None
                        else:
                            try:
                                text, usage = ask(messages)
                            except CostCapReached as error:
                                # A spend limit before this attempt's first request. A build that has paid for
                                # nothing gets no record, so the next start builds it; one that has paid stays
                                # pending and resumes on the next start, within the provider's own stop.
                                if cap_stop_status(sum(paid["requests"] for paid in usages)) is None:
                                    untouched = True
                                else:
                                    interrupted = f"spend limit reached: {error}"
                                break
                            except PaidRequestFailed as error:  # part of the reply was paid for, then it failed
                                usages.append(error.usage)
                                interrupted = f"teacher request failed: {error}"
                                break
                            except Exception as error:  # the provider failed after the client's own retries
                                interrupted = f"teacher request failed: {type(error).__name__}: {str(error)[:300]}"
                                break
                            usages.append(usage)
                            if usage["stopped_by_cap"]:  # a spend limit between two parts of one reply
                                interrupted = "spend limit reached during a reply"
                                break
                            if stop_status(usage):  # cut off even at the ceiling: the reply never fit
                                status, last_error = stop_status(usage), f"no whole reply: {stop_status(usage)}"
                                break
                        try:
                            workflow = parse_compile_reply(text)
                        except (ValueError, SyntaxError) as error:
                            last_error = f"{type(error).__name__}: {error}"
                            attempts.append({"attempt": attempt, "reply": text, "parse_error": last_error})
                            messages += [{"role": "assistant", "content": text},
                                         {"role": "user", "content": f"Your reply could not be used: {last_error}. "
                                                                      "Reply again in exactly the required format."}]
                            continue

                        def check_once() -> tuple[str, dict]:
                            """One validation in a fresh copy of the apps. A bridge failure is a `model_error`."""
                            try:
                                bridge.open_task(task_id, experiment_name=f"{args.run_name}__compile_check__a{attempt}",
                                                 timeout_seconds=config["appworld_timeout_seconds"])
                                execution = bridge.execute(workflow.validation_code())
                                passed = bool(bridge.evaluate()["success"])
                                bridge.close_task()
                            except Exception as broke:  # the bridge, not the function: its errors come back as output
                                try:
                                    bridge.close_task()
                                except Exception:
                                    pass
                                return "model_error", {"error": f"{type(broke).__name__}: {broke}"}
                            return "completed", {"output": execution.output, "passed": passed}

                        # A validation the bridge broke says nothing about the function. It is not an attempt.
                        ran, checks = run_check(check_once)
                        if not ran:
                            interrupted, pending_reply = checks[-1]["error"], text
                            break
                        output, passed = checks[-1]["output"], checks[-1]["passed"]
                        attempts.append({"attempt": attempt, "reply": text, "output": output, "passed": passed})
                        if passed:
                            validated, status = True, "built"
                            (folder / "compiled_workflow.py").write_text(workflow.source + "\n", encoding="utf-8")
                            (folder / "compiled_guidance.txt").write_text(workflow.guidance(), encoding="utf-8")
                            break
                        messages += [{"role": "assistant", "content": text},
                                     {"role": "user", "content": build_repair_prompt(output, passed)}]
                    if untouched:
                        print(f"{scenario_id}: compile not started, the spend limit came first; left pending")
                    elif interrupted:
                        # No row: a row would mark the build as decided. What was paid is in the ledger and in the
                        # pending file, which also holds everything a restart needs (`compile_pending_state`).
                        (folder / f"compile_PENDING_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
                            json.dumps({"messages": messages, "attempts": attempts, "usages": usages,
                                        "last_error": last_error, "interrupted": interrupted,
                                        "interrupted_attempt": attempt, "pending_reply": pending_reply,
                                        **identity,
                                        "resumed_from": state["file"] if state else None},
                                       indent=2, ensure_ascii=False), encoding="utf-8")
                        build_log["compile"] = {"prompt": messages[0]["content"], "attempts": attempts,
                                                "status": "pending", "interrupted": interrupted,
                                                "cost_usd": total(usages)["cost_usd"]}
                        print(f"{scenario_id}: compile validation could not run ({interrupted[:120]}); no row written, "
                              f"the build stays pending | paid, in the ledger: ${total(usages)['cost_usd']:.4f}")
                    else:
                        append_jsonl(teach_path, {**base_row(scenario_id, task_id, "compile"), **total(usages),
                                                  "status": status, "validated": validated, "attempts": len(attempts),
                                                  "error": None if validated else last_error,
                                                  "resumed_from": state["file"] if state else None})
                        retire_pending(folder, COMPILE_PENDING_GLOB)
                        build_log["compile"] = {"prompt": messages[0]["content"], "attempts": attempts,
                                                "status": status}
                        print(f"{scenario_id}: compile {status} after {len(attempts)} attempt(s) | "
                              f"${total(usages)['cost_usd']:.4f}")

                if build_log:
                    log_path = folder / f"build_log_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    log_path.write_text(json.dumps(build_log, indent=2, ensure_ascii=False), encoding="utf-8")
                if untouched:
                    print("cost cap reached; stopping. The build that was not started stays pending.")
                    break
                if interrupted:
                    print("the build could not finish; stopping. It stays pending and resumes on the next start.")
                    break
                if build_log.get("compile", {}).get("status") == "cost_cap":
                    print("cost cap reached; stopping. A cost_cap build is not resumed: the stage is incomplete.")
                    break
    except CostCapReached as error:
        print(f"cost cap reached: {error}")
    print(f"spent ${budget.spent_usd:.4f} | {provider} ledger total ${ledger_total(LEDGER, provider):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
