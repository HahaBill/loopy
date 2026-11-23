"""One teacher request that is not lost to the output limit.

The teacher thinks before it answers. If it uses the whole output limit on thinking, the reply comes back empty
with finish reason "length". That is a limit of the harness, not a failed attempt at the task, so the same
request is sent again with twice the limit, up to `ceiling`. Every request is priced and counted.
Coach notes and compiled functions both go through this, so the two forms get the same treatment.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from loopy.agent.llm import ChatModel, Message, ModelSpec, PydanticAIChat, Reply
from loopy.agent.react import Budget

CEILING_TOKENS = 64000
SECONDS_PER_1K_TOKENS = 20.0


def was_cut_off(reply: Reply) -> bool:
    return not reply.text.strip() and reply.finish_reason == "length"


def complete_uncut(
    spec: ModelSpec,
    messages: list[Message],
    budget: Budget,
    make_chat: Callable[[ModelSpec], ChatModel] = PydanticAIChat,
    ceiling: int = CEILING_TOKENS,
) -> tuple[Reply, dict[str, Any]]:
    """Returns the last reply and the usage summed over every request it took."""
    limit = spec.max_tokens
    usage: dict[str, Any] = {"requests": 0, "cut_off_requests": 0, "input_tokens": 0, "output_tokens": 0,
                             "cost_usd": 0.0, "seconds": 0.0}
    while True:
        budget.check()
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
        if not was_cut_off(reply) or limit >= ceiling:
            usage["cut_off_requests"] += int(was_cut_off(reply))
            return reply, usage
        usage["cut_off_requests"] += 1
        limit = min(limit * 2, ceiling)
