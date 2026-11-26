"""POST HOC, exploratory. Reads stage 1 rows only; writes nothing. Run from the loopy checkout.

Eligible task = a test task (version 2 or 3) the student failed alone, in a scenario where the student failed
version 1 and the teacher passed it (the same set the control ran on). A missing run counts as not fixed.
"""
import collections
import json
import pathlib

R = pathlib.Path("results/pilot/stage1")
TEACHER = "glm-5.3-flash"
STUDENTS = ["gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash", "deepseek-v4.1-flash", "qwen3.8-27b"]
rows = [json.loads(s) for s in (R / "runs.jsonl").open(encoding="utf8") if s.strip()]
latest = {}
for r in rows:
    k = (r["condition"], r["model_key"], r["task_id"])
    if k not in latest or r["repeat"] >= latest[k]["repeat"]:
        latest[k] = r
teach = [json.loads(s) for s in (R / "teach.jsonl").open(encoding="utf8") if s.strip()]
last_build = {}
for t in teach:
    last_build[(t["kind"], t["small_model_key"], t["scenario_id"])] = t


def ok(cond, model, task):
    row = latest.get((cond, model, task))
    return bool(row and row["success"])


def has(cond, model, task):
    return (cond, model, task) in latest


tot = collections.Counter()
print("student | v1 alone | eligible | note | func | generic | both | func only | note only | neither")
for s in STUDENTS:
    v1 = sum(1 for (c, m, t), r in latest.items() if c == "small_alone" and m == s and t.endswith("_1") and r["success"])
    elig = []
    for (c, m, t), r in latest.items():
        sc, ver = t.rsplit("_", 1)
        if c != "small_alone" or m != s or ver == "1" or r["success"]:
            continue
        own, tea = latest.get(("small_alone", s, sc + "_1")), latest.get(("cloud_alone", TEACHER, sc + "_1"))
        if own and tea and not own["success"] and tea["success"]:
            elig.append(t)
    n = [ok("coach_checked", s, t) for t in elig]
    f = [ok("compile", s, t) for t in elig]
    g = [ok("generic_note", s, t) for t in elig]
    both = sum(a and b for a, b in zip(n, f)); fo = sum(b and not a for a, b in zip(n, f))
    no = sum(a and not b for a, b in zip(n, f)); ne = sum((not a) and (not b) for a, b in zip(n, f))
    print(f"{s:20s} | {v1:2d}/30 | {len(elig):3d} | {sum(n):3d} | {sum(f):3d} | {sum(g):3d} | {both:3d} | {fo:3d} | {no:3d} | {ne:3d}")
    # per protocol: only where the artifact was built and run
    nb = [t for t in elig if has("coach_checked", s, t)]; fb = [t for t in elig if has("compile", s, t)]
    bb = [t for t in elig if has("coach_checked", s, t) and has("compile", s, t)]
    print(f"   built-note tasks {len(nb):3d}: note fixed {sum(ok('coach_checked', s, t) for t in nb):3d}"
          f" | built-function tasks {len(fb):3d}: function fixed {sum(ok('compile', s, t) for t in fb):3d}"
          f" | both built {len(bb):3d}: note {sum(ok('coach_checked', s, t) for t in bb)} function {sum(ok('compile', s, t) for t in bb)}")
    stops = collections.Counter(latest[("compile", s, t)]["stop_reason"] for t in fb if not ok("compile", s, t))
    nstops = collections.Counter(latest[("coach_checked", s, t)]["stop_reason"] for t in nb if not ok("coach_checked", s, t))
    print(f"   failed function runs by stop: {dict(stops)} | failed note runs by stop: {dict(nstops)}")
    bd = collections.Counter(); bdn = collections.Counter(); bdf = collections.Counter()
    for t in elig:
        d = latest[("small_alone", s, t)]["difficulty"]; bd[d] += 1
        bdn[d] += ok("coach_checked", s, t); bdf[d] += ok("compile", s, t)
    print("   by difficulty (n, note, function):", {d: (bd[d], bdn[d], bdf[d]) for d in sorted(bd)})
    # harm: tasks passed alone, then run with the artifact
    pa = [t for (c, m, t), r in latest.items() if c == "small_alone" and m == s and not t.endswith("_1") and r["success"]]
    hf = [t for t in pa if has("compile", s, t)]; hn = [t for t in pa if has("coach_checked", s, t)]
    print(f"   passed alone {len(pa)}: with function run {len(hf)} broke {sum(not ok('compile', s, t) for t in hf)}"
          f" | with note run {len(hn)} broke {sum(not ok('coach_checked', s, t) for t in hn)}")
    for name, val in (("elig", len(elig)), ("note", sum(n)), ("func", sum(f)), ("gen", sum(g))):
        tot[name] += val
print("totals", dict(tot))
