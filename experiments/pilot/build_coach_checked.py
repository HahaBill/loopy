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
import types
from dataclasses import asdict
from pathlib import Path

from loopy.agent.llm import ModelSpec, PydanticAIChat, load_env_file
from loopy.agent.react import Budget, CostCapReached, run_task
from loopy.eval.bridge import REPO_ROOT, AppWorldBridge
from loopy.eval.runlog import append_jsonl, git_state, ledger_total, now_et, read_jsonl
from loopy.skills.coach import build_coach_prompt, build_revision_prompt, parse_coach_reply
from loopy.skills.teach import PaidRequestFailed, cap_stop_status, complete_uncut, run_check, stale_skips, stop_status

HERE = Path(__file__).resolve().parent
LEDGER = REPO_ROOT / "results" / "spend_ledger.jsonl"
KIND = "coach_checked"
PENDING_GLOB = "coach_checked_PENDING_log_*.json"
RESUME_KEYS = ("messages", "attempts", "broken_checks", "teacher_cost_usd", "student_cost_usd", "teacher_calls",
               "student_requests", "cut_off_requests", "first")


def find_record(records: list[dict], task_id: str, condition: str, model_key: str) -> dict | None:
    matches = [record for record in records if record["task_id"] == task_id
               and record["condition"] == condition and record["model_key"] == model_key]
    return matches[-1] if matches else None


def load_records(source_dirs: list[Path]) -> list[dict]:
    """Every run row of the run folder and of the source run, each marked with the folder it came from.

    The source run's rows come first, so `find_record`, which takes the last match, picks the run's own row over an
    older one in the source run (review item 5), and the trajectory file is read from the folder of the row picked.
    """
    return [{**record, "_folder": str(folder)} for folder in reversed(source_dirs)
            for record in read_jsonl(folder / "runs.jsonl")]


def ledger_note(student: str, scenario_id: str) -> str:
    """The ledger note of every request a note build sends. The cost audit reads the scenario from it (item 7)."""
    return f"build_coach_checked {student} {scenario_id}"


IDENTITY_KEYS = ("teacher_model_key", "small_model_key", "learn_task_id")


def pending_state(folder: Path, expected: dict | None = None) -> dict | None:
    """What an interrupted build of this scenario already did and paid for, from its latest pending log (item 4).

    A build whose validation the provider or the bridge kept breaking writes a pending log and no row. A restart goes
    on from there: the same conversation with the teacher, the attempts already made (so it does not get a fresh set)
    and the spend so far (so the row it finally writes carries all of it). Each pending log holds the whole state up to
    its interruption, so only the latest one is read. A pending log without that state cannot be resumed safely.
    """
    logs = sorted(folder.glob(PENDING_GLOB))
    if not logs:
        return None
    state = json.loads(logs[-1].read_text(encoding="utf-8"))
    missing = [key for key in RESUME_KEYS if key not in state]
    if missing:
        raise SystemExit(f"{logs[-1]}: a pending build without {missing}; it cannot be resumed. Decide it by hand.")
    wrong = [key for key, value in (expected or {}).items() if key in state and state[key] != value]
    if wrong:
        raise SystemExit(f"{logs[-1]}: a pending build for another {wrong} in this folder; it cannot be resumed here. "
                         "Decide it by hand.")
    return {**state, "file": logs[-1].name}


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
    records = load_records(source_dirs)
    earlier = [row for row in read_jsonl(teach_path)
               if row["kind"] == KIND and row["teacher_model_key"] == args.cloud_model
               and row["small_model_key"] == args.small_model]

    def learned(condition: str, model_key: str, scenario_id: str) -> bool | None:
        record = find_record(records, f"{scenario_id}_{args.learn_version}", condition, model_key)
        return None if record is None else bool(record["success"])

    # A recorded skip is a decision only while the runs it was read from are still the latest ones.
    done = {row["scenario_id"] for row in earlier} - {key[0] for key in stale_skips(earlier, learned)}

    def budget_for(who: str) -> Budget:
        """The invocation's guard (--max-usd, over both budgets when there are two) and this provider's own stop."""
        max_usd = args.max_usd if args.max_usd is not None else config.get("max_usd_per_invocation")
        ledger_cap = (config.get("ledger_caps_usd") or {}).get(who)
        if ledger_cap is not None and ledger_total(LEDGER, who) >= ledger_cap:
            raise SystemExit(f"{who}: the ${ledger_cap:.2f} cap is used up. Stopping.")
        return Budget(max_usd=max_usd, ledger=LEDGER, provider=who, run_name=args.run_name,
                      note=f"build_coach_checked {args.small_model}", ledger_cap=ledger_cap,
                      reserve_usd=(config.get("ledger_reserve_usd") or {}).get(who, 0.0))

    provider = teacher_spec.provider
    ledger_cap = (config.get("ledger_caps_usd") or {}).get(provider)
    budget = budget_for(provider)
    # The note's check is a student run. When the student is billed by another provider than the teacher, its
    # requests go to that provider's ledger rows and stop, not the teacher's. With one provider this is one budget.
    student_budget = budget if student_spec.provider == provider else budget_for(student_spec.provider)
    if student_budget is not budget:  # one invocation guard (--max-usd) over both providers' spend
        budget.shares_cap_with, student_budget.shares_cap_with = student_budget, budget
    student = PydanticAIChat(student_spec)
    git = git_state()

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
                       "git_commit": git["commit"], "command": " ".join(sys.argv), "cutoff_fix_version": 3}
                if small["success"] or not cloud["success"]:
                    status = "skipped_small_passed" if small["success"] else "skipped_cloud_failed"
                    append_jsonl(teach_path, {**row, "status": status, "validated": False, "attempts": 0,
                                              "requests": 0, "cloud_calls": 0, "cost_usd": 0.0})
                    print(f"{scenario_id}: {status}", flush=True)
                    continue

                def raw(record: dict) -> dict:
                    name = f"{record['condition']}__{record['model_key']}__{task_id}__r{record['repeat']}.json"
                    return json.loads((Path(record["_folder"]) / "raw_large" / name).read_text(encoding="utf-8"))

                folder = skills_dir / scenario_id
                budget.note = student_budget.note = ledger_note(args.small_model, scenario_id)
                identity = {"teacher_model_key": args.cloud_model, "small_model_key": args.small_model,
                            "learn_task_id": task_id}
                state = pending_state(folder, identity)
                if state:  # an earlier start was interrupted during validation: go on from where it stopped
                    messages, attempts, broken_checks = state["messages"], state["attempts"], state["broken_checks"]
                    teacher_cost, student_cost = state["teacher_cost_usd"], state["student_cost_usd"]
                    teacher_calls, student_requests = state["teacher_calls"], state["student_requests"]
                    cut_off_requests = state["cut_off_requests"]
                    teacher_cached = state.get("teacher_cached_input_tokens", 0)
                    first = types.SimpleNamespace(**state["first"]) if state["first"] else None
                    pending_text = state.get("pending_reply")  # paid for, its check broke: checked again, not bought
                    print(f"{scenario_id}: resuming the build interrupted in {state['file']} after "
                          f"{len(attempts)} attempt(s) | already paid ${teacher_cost + student_cost:.4f}", flush=True)
                else:
                    small_raw, cloud_raw = raw(small), raw(cloud)
                    messages = [{"role": "user", "content": build_coach_prompt(
                        small_raw["instruction"], small_raw["steps"], cloud_raw["steps"])}]
                    teacher_cost = student_cost = 0.0
                    teacher_calls = student_requests = cut_off_requests = teacher_cached = 0
                    attempts, broken_checks, first, pending_text = [], [], None, None
                validated, note, stopped, pending_reply = False, None, None, None
                untouched = False  # the spend limit came before this build's first request
                interrupted = None  # why the validation could not run to its own end, if it could not
                attempt = len(attempts) + 1
                for attempt in range(len(attempts) + 1, args.max_repairs + 2):
                    if pending_text is not None:
                        text, pending_text = pending_text, None
                    else:
                        try:
                            reply, usage = complete_uncut(teacher_spec, messages, budget)
                        except CostCapReached as error:
                            # A spend limit before this attempt's first request. A build that has paid for nothing
                            # gets no record, so the next start builds it; one that has paid stays pending and resumes
                            # on the next start, within the provider's own stop.
                            if cap_stop_status(teacher_calls + student_requests) is None:
                                untouched = True
                            else:
                                interrupted = f"spend limit reached: {error}"
                            break
                        except PaidRequestFailed as error:  # part of the reply was paid for, then it failed
                            teacher_cost += error.usage["cost_usd"]
                            teacher_cached += error.usage["cached_input_tokens"]
                            teacher_calls += error.usage["requests"]
                            cut_off_requests += error.usage["cut_off_requests"]
                            interrupted = f"teacher request failed: {error}"
                            break
                        except Exception as error:  # the provider failed after the client's own retries
                            interrupted = f"teacher request failed: {type(error).__name__}: {str(error)[:300]}"
                            break
                        teacher_cost += usage["cost_usd"]
                        teacher_cached += usage["cached_input_tokens"]
                        teacher_calls += usage["requests"]
                        cut_off_requests += usage["cut_off_requests"]
                        if usage["stopped_by_cap"]:  # a spend limit between two parts of one reply
                            interrupted = "spend limit reached during a reply"
                            break
                        stopped = stop_status(usage)
                        if stopped:  # cut off even at the ceiling: the reply never fit
                            break
                        text = reply.text
                    try:
                        note = parse_coach_reply(text)
                    except ValueError as error:
                        attempts.append({"attempt": attempt, "reply": text, "parse_error": str(error)})
                        messages += [{"role": "assistant", "content": text},
                                     {"role": "user", "content": f"Your reply could not be used: {error}. "
                                                                  "Reply again in exactly the required format."}]
                        continue
                    first = first or note

                    def check_once() -> tuple[str, dict]:
                        """One run of the student with the note. A bridge failure around the run is a `model_error`."""
                        trace = None
                        try:
                            task = bridge.open_task(task_id, experiment_name=f"{args.run_name}__coach_check__"
                                                                             f"{args.small_model}__a{attempt}",
                                                    timeout_seconds=config["appworld_timeout_seconds"])
                            trace = run_task(bridge, student, task.instruction, task.supervisor,
                                             max_steps=config["max_steps"],
                                             output_char_limit=config["output_char_limit"],
                                             guidance=note.guidance(), forecast=False, budget=student_budget)
                            passed = bool(bridge.evaluate()["success"])
                            bridge.close_task()
                            stop_reason, error = trace.stop_reason, trace.error
                        except Exception as broke:  # outside the run itself: opening, grading or closing the task
                            passed, stop_reason, error = False, "model_error", f"{type(broke).__name__}: {broke}"
                            try:
                                bridge.close_task()
                            except Exception:
                                pass
                        totals = trace.totals() if trace else {"cost_usd": 0.0, "requests": 0}
                        return stop_reason, {"passed": passed, "stop_reason": stop_reason, "error": error,
                                             "cost_usd": totals["cost_usd"], "requests": int(totals["requests"]),
                                             "steps": [asdict(step) for step in trace.steps] if trace else []}

                    # A check that the provider, the bridge or a spend limit ended says nothing about the note. It is
                    # not an attempt: it is started again (not after a spend stop), and it never ends a build as failed.
                    ran, checks = run_check(check_once)
                    student_cost += sum(check["cost_usd"] for check in checks)
                    student_requests += sum(check["requests"] for check in checks)
                    check = checks[-1]
                    broken_checks += [{"attempt": attempt, "stop_reason": item["stop_reason"], "error": item["error"],
                                       "n_steps": len(item["steps"])} for item in (checks if not ran else checks[:-1])]
                    if not ran:
                        interrupted, pending_reply = f"{check['stop_reason']}: {check['error']}", text
                        break
                    attempts.append({"attempt": attempt, "reply": text, "note": note.note,
                                     "passed": check["passed"], "stop_reason": check["stop_reason"],
                                     "n_steps": len(check["steps"]), "steps": check["steps"]})
                    if check["passed"]:
                        validated = True
                        break
                    messages += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": build_revision_prompt(check["steps"])}]

                if untouched:
                    print(f"{scenario_id}: coach_checked not started, the spend limit came first; left pending. "
                          "Stopping.", flush=True)
                    break
                folder.mkdir(parents=True, exist_ok=True)
                if interrupted:
                    # No row: a row would mark the build as decided. What was paid is in the ledger and in this log,
                    # which also holds everything a restart needs to go on from here (`pending_state`).
                    (folder / f"coach_checked_PENDING_log_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
                        json.dumps({"prompt": messages[0]["content"], "messages": messages, "attempts": attempts,
                                    "interrupted": interrupted, "interrupted_attempt": attempt,
                                    "pending_reply": pending_reply, **identity,
                                    "broken_checks": broken_checks, "teacher_cost_usd": teacher_cost,
                                    "student_cost_usd": student_cost, "teacher_calls": teacher_calls,
                                    "student_requests": student_requests, "cut_off_requests": cut_off_requests,
                                    "teacher_cached_input_tokens": teacher_cached,
                                    "first": None if first is None else {"divergence_step": first.divergence_step,
                                                                         "failure_kind": first.failure_kind},
                                    "resumed_from": state["file"] if state else None},
                                   indent=2, ensure_ascii=False),
                        encoding="utf-8")
                    print(f"{scenario_id}: coach_checked validation could not run ({interrupted[:120]}); no row "
                          f"written, the build stays pending | paid, in the ledger: teacher ${teacher_cost:.4f} + "
                          f"student ${student_cost:.4f}. Stopping.", flush=True)
                    break
                if validated and note is not None:
                    (folder / "coach_checked_note.txt").write_text(note.guidance(), encoding="utf-8")
                elif note is not None:  # kept for the record; not used as a skill
                    (folder / "coach_checked_FAILED_last_note.txt").write_text(note.guidance(), encoding="utf-8")
                (folder / f"coach_checked_log_{time.strftime('%Y%m%d_%H%M%S')}.json").write_text(
                    json.dumps({"prompt": messages[0]["content"], "attempts": attempts,
                                "broken_checks": broken_checks}, indent=2, ensure_ascii=False), encoding="utf-8")
                final_status = "built" if validated else stopped or "failed_validation"
                append_jsonl(teach_path, {
                    **row, "status": final_status, "validated": validated,
                    "attempts": len(attempts), "requests": teacher_calls, "cloud_calls": teacher_calls,
                    "teacher_cost_usd": round(teacher_cost, 6), "student_cost_usd": round(student_cost, 6),
                    "teacher_cached_input_tokens": teacher_cached,
                    "student_requests": student_requests, "cut_off_requests": cut_off_requests, "cost_usd": round(teacher_cost + student_cost, 6),
                    "divergence_step": first.divergence_step if first else None,
                    "failure_kind": first.failure_kind if first else None,
                    "resumed_from": state["file"] if state else None,
                })
                for path in folder.glob(PENDING_GLOB):  # decided now: kept for the record, never resumed again
                    path.rename(path.with_name(path.name.replace("_PENDING_", "_RESUMED_")))
                print(f"{scenario_id}: coach_checked {final_status} after "
                      f"{len(attempts)} attempt(s) | teacher ${teacher_cost:.4f} + student ${student_cost:.4f}",
                      flush=True)
                if stopped == "cost_cap":
                    print("cost cap reached; stopping. A cost_cap build is not resumed: the stage is incomplete.",
                          flush=True)
                    break
    except CostCapReached as error:
        print(f"cost cap reached: {error}")
    print(f"spent ${budget.spent_usd:.4f} | {provider} ledger total ${ledger_total(LEDGER, provider):.4f}")
    if student_budget is not budget:
        print(f"student checks spent ${student_budget.spent_usd:.4f} | {student_spec.provider} ledger total "
              f"${ledger_total(LEDGER, student_spec.provider):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
