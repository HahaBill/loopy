"""The fixes made before the stage 1 students ran. No model needed."""

import json
import multiprocessing as mp

from loopy.agent.llm import ModelSpec, Reply
from loopy.agent.react import Budget
from loopy.eval.runlog import append_jsonl, read_jsonl
from loopy.skills.teach import complete_uncut

SPEC = ModelSpec(key="t", role="cloud", name="t", usd_per_mtok_in=1.0, usd_per_mtok_out=1.0, max_tokens=16000)


def scripted(limits_seen, replies):
    class Chat:
        def __init__(self, spec):
            self.spec = spec

        def complete(self, messages):
            limits_seen.append(self.spec.max_tokens)
            return replies.pop(0)

    return Chat


def test_cut_off_reply_is_retried_with_a_larger_limit_and_priced():
    seen = []
    replies = [Reply("", 100, 16000, 1.0, finish_reason="length"), Reply("answer", 100, 20000, 1.0, finish_reason="stop")]
    reply, usage = complete_uncut(SPEC, [{"role": "user", "content": "x"}], Budget(), make_chat=scripted(seen, replies))
    assert reply.text == "answer" and seen == [16000, 32000]
    assert usage["requests"] == 2 and usage["cut_off_requests"] == 1 and usage["output_tokens"] == 36000


def test_stops_at_the_ceiling_and_a_short_empty_reply_is_not_retried():
    seen = []
    replies = [Reply("", 1, 1, 0.1, finish_reason="length") for _ in range(3)]
    reply, usage = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen, replies))
    assert seen == [16000, 32000, 64000] and not reply.text and usage["cut_off_requests"] == 3
    seen2 = []
    _, usage2 = complete_uncut(SPEC, [], Budget(), make_chat=scripted(seen2, [Reply("", 1, 1, 0.1, finish_reason="stop")]))
    assert seen2 == [16000] and usage2["cut_off_requests"] == 0


def _writer(args):
    path, who = args
    for index in range(200):
        append_jsonl(path, {"who": who, "index": index, "padding": "x" * 900})


def test_parallel_appends_keep_every_line(tmp_path):
    path = tmp_path / "runs.jsonl"
    with mp.get_context("spawn").Pool(4) as pool:
        pool.map(_writer, [(str(path), who) for who in range(4)])
    rows = read_jsonl(path)
    assert len(rows) == 800 and len({(row["who"], row["index"]) for row in rows}) == 800
