"""POST HOC, exploratory. Reads stage 1 rows only; writes nothing. Run from the loopy checkout.

Test tasks passed (of 60 per student) under simple rules for when to hand a student the function or the note.
"Gated" means: use the help only in scenarios where the student failed version 1 alone (what a deployed system
would know). Where a form was not built or not run for a task, the student's own result alone is used.
"""
import json
import pathlib

R = pathlib.Path("results/pilot/stage1")
STUDENTS = ["gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash", "deepseek-v4.1-flash", "qwen3.8-27b"]
rows = [json.loads(s) for s in (R / "runs.jsonl").open(encoding="utf8") if s.strip()]
latest = {}
for r in rows:
    k = (r["condition"], r["model_key"], r["task_id"])
    if k not in latest or r["repeat"] >= latest[k]["repeat"]:
        latest[k] = r


def res(cond, s, t):
    row = latest.get((cond, s, t))
    return None if row is None else bool(row["success"])


print("student | alone | always function | gated function | always note* | gated note | best of both per task (oracle) | broken: always fn, gated fn")
print("* the note exists only where the student failed version 1, so always note equals gated note")
for s in STUDENTS:
    tasks = sorted(t for (c, m, t) in latest if c == "small_alone" and m == s and not t.endswith("_1"))
    alone = fn_all = fn_gate = note = oracle = broke_all = broke_gate = 0
    for t in tasks:
        sc = t.rsplit("_", 1)[0]
        a = res("small_alone", s, t)
        f = res("compile", s, t)
        n = res("coach_checked", s, t)
        failed_v1 = not res("small_alone", s, sc + "_1")
        alone += a
        fa = a if f is None else f
        fn_all += fa
        broke_all += bool(a and f is False)
        fg = fa if failed_v1 else a
        fn_gate += fg
        broke_gate += bool(a and failed_v1 and f is False)
        note += a if n is None else n
        oracle += bool(a or f or n)
    print(f"{s:20s} | {alone:2d} | {fn_all:2d} | {fn_gate:2d} | {note:2d} | {note:2d} | {oracle:2d} | {broke_all}, {broke_gate}")
