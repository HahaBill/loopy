"""One teacher request that is not lost to the output limit.

The teacher thinks before it answers. A reply that ends with finish reason "length" was stopped by the output
limit, whether it came back empty or stopped partway through its text. That is a limit of the harness, not a
failed attempt at the task, so the same request is sent again with twice the limit, up to `ceiling`, and up to
three times at the ceiling. If it is still cut off, `usage["still_cut_off"]` is True and the caller must end the
build as "cut_off" instead of counting the reply as an attempt. If the cost cap stops the resending,
`usage["stopped_by_cap"]` is True and the usage so far is returned, so no paid request goes unrecorded.
Coach notes and compiled functions both go through this, so the two forms get the same treatment.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from loopy.agent.llm import ChatModel, Message, ModelSpec, PydanticAIChat, Reply
from loopy.agent.react import Budget, CostCapReached

CEILING_TOKENS = 64000
REQUESTS_AT_CEILING = 3
SECONDS_PER_1K_TOKENS = 20.0


def was_cut_off(reply: Reply) -> bool:
    return reply.finish_reason == "length"


def stop_status(usage: dict[str, Any]) -> str | None:
    """The build status when a request never produced a whole reply; None when it did."""
    if usage["stopped_by_cap"]:
        return "cost_cap"
    return "cut_off" if usage["still_cut_off"] else None


CHECK_TRIES = 3  # how often one validation may be started when the provider or the bridge breaks under it
NOT_A_VERDICT = ("model_error", "cost_cap")  # stops that say nothing about the skill being checked


def run_check(start: Callable[[], tuple[str, Any]], tries: int = CHECK_TRIES) -> tuple[bool, list[Any]]:
    """Runs a skill's validation until it ends on its own, at most `tries` times.

    `start` runs the validation once and returns (stop reason, whatever the caller wants to keep). A validation that
    the provider or the bridge broke (`model_error`) is not a failed attempt of the skill, so it is started again. One
    that a spend limit stopped (`cost_cap`) is not started again: the next one would stop the same way.
    Returns (whether a validation ran to its own end, everything `start` returned, in order).
    """
    kept = []
    for _ in range(tries):
        stop_reason, result = start()
        kept.append(result)
        if stop_reason not in NOT_A_VERDICT:
            return True, kept
        if stop_reason == "cost_cap":
            break
    return False, kept


def skip_still_holds(status: str, student_passed: bool | None, teacher_passed: bool | None) -> bool:
    """Whether a recorded skip still agrees with the latest runs of the learning task (None: no run on file).

    A build is skipped because the student passed the task or the teacher failed it. If that run is later redone and
    comes out the other way, the recorded skip is no longer a decision and the build has to be made.
    """
    if status == "skipped_cloud_failed":
        return not teacher_passed
    if status == "skipped_small_passed":
        return student_passed is not False
    return True


def stale_skips(teach_rows: list[dict[str, Any]],
                passed: Callable[[str, str, str], bool | None]) -> set[tuple[str, str, str, str]]:
    """Builds whose latest row is a skip that the latest runs no longer support.

    `passed(condition, model key, scenario)` is the outcome of the latest run of the scenario's learning task.
    Returns (scenario, kind, teacher model key, small model key) for each such build. The builders drop these from
    what they treat as done, so a restart decides them again.
    """
    latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in teach_rows:
        latest[(row["scenario_id"], row["kind"], row["teacher_model_key"], row["small_model_key"])] = row
    return {key for key, row in latest.items()
            if not skip_still_holds(row["status"], passed("small_alone", key[3], key[0]),
                                    passed("cloud_alone", key[2], key[0]))}


def cap_stop_status(requests_sent: int) -> str | None:
    """What a build records when the spend limit stops it before its next request.

    A build that already sent requests is recorded as `cost_cap`, with what it paid. A build that sent nothing is not
    recorded at all (None): a record would mark it as decided, and a restart with more budget would skip it.
    """
    return "cost_cap" if requests_sent > 0 else None


def complete_uncut(
    spec: ModelSpec,
    messages: list[Message],
    budget: Budget,
    make_chat: Callable[[ModelSpec], ChatModel] = PydanticAIChat,
    ceiling: int = CEILING_TOKENS,
) -> tuple[Reply, dict[str, Any]]:
    """Returns the last reply and the usage summed over every request it took."""
    limit = min(spec.max_tokens, ceiling)
    usage: dict[str, Any] = {"requests": 0, "cut_off_requests": 0, "input_tokens": 0, "output_tokens": 0,
                             "cost_usd": 0.0, "seconds": 0.0, "still_cut_off": False, "stopped_by_cap": False}
    at_ceiling = 0
    reply: Reply | None = None
    while True:
        try:
            budget.check()
        except CostCapReached:
            if reply is None:
                raise
            usage["stopped_by_cap"] = True
            return reply, usage
        current = dataclasses.replace(spec, max_tokens=limit,
                                      request_timeout=max(spec.request_timeout, limit / 1000 * SECONDS_PER_1K_TOKENS))
        reply = make_chat(current).complete(messages)
        cost = spec.cost_usd(reply.input_tokens, reply.output_tokens)
        budget.add(cost)
        usage["requests"] += 1
        usage["input_tokens"] += reply.input_tokens
        usage["output_tokens"] += reply.output_tokens
        usage["cost_usd"] += cost
        usage["seconds"] += reply.seconds
        if not was_cut_off(reply):
            return reply, usage
        usage["cut_off_requests"] += 1
        if limit >= ceiling:
            at_ceiling += 1
            if at_ceiling >= REQUESTS_AT_CEILING:
                usage["still_cut_off"] = True
                return reply, usage
        limit = min(limit * 2, ceiling)
