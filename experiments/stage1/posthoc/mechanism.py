"""POST HOC, exploratory. Reads stage 1 rows only; writes nothing. Run from the loopy checkout.

(a) Does the length of the teacher's own passing run (steps) predict where a note or a function fixes a failed task?
(b) Where a function broke a task a student passed alone: did other students pass that same task with the function?
(c) Per built function and test variant: how many students pass with it.
"""
import collections
import json
import pathlib

R = pathlib.Path("results/pilot/stage1")
TEACHER = "glm-5.3-flash"
WEAK = ["gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash"]
STRONG = ["deepseek-v4.1-flash", "qwen3.8-27b"]
rows = [json.loads(s) for s in (R / "runs.jsonl").open(encoding="utf8") if s.strip()]
latest = {}
for r in rows:
    k = (r["condition"], r["model_key"], r["task_id"])
    if k not in latest or r["repeat"] >= latest[k]["repeat"]:
        latest[k] = r


def ok(cond, model, task):
    row = latest.get((cond, model, task))
    return bool(row and row["success"])


def eligible(s):
    out = []
    for (c, m, t), r in latest.items():
        sc, ver = t.rsplit("_", 1)
        if c != "small_alone" or m != s or ver == "1" or r["success"]:
            continue
        own, tea = latest.get(("small_alone", s, sc + "_1")), latest.get(("cloud_alone", TEACHER, sc + "_1"))
        if own and tea and not own["success"] and tea["success"]:
            out.append(t)
    return out


print("(a) weak tier, eligible failed tasks, by teacher's steps on the SAME test task (teacher passed it)")
bins = [(1, 4), (5, 7), (8, 11), (12, 50)]
agg = {b: [0, 0, 0, 0] for b in bins}
skipped = 0
for s in WEAK:
    for t in eligible(s):
        tr = latest.get(("cloud_alone", TEACHER, t))
        if not tr or not tr["success"]:
            skipped += 1
            continue
        for b in bins:
            if b[0] <= tr["n_steps"] <= b[1]:
                a = agg[b]; a[0] += 1; a[1] += ok("coach_checked", s, t); a[2] += ok("compile", s, t); a[3] += ok("generic_note", s, t)
for b in bins:
    n, no, fu, ge = agg[b]
    if n:
        print(f"   teacher steps {b[0]:2d}-{b[1]:2d}: n={n:3d} note {no:3d} ({no/n:.2f}) function {fu:3d} ({fu/n:.2f}) generic {ge:3d} ({ge/n:.2f})")
print(f"   tasks left out because the teacher failed that test task: {skipped}")

print("(a2) same, by the student's own step count when it failed alone (did it run out of steps?)")
st = collections.Counter(); stn = collections.Counter(); stf = collections.Counter()
for s in WEAK:
    for t in eligible(s):
        r = latest[("small_alone", s, t)]
        key = r["stop_reason"]
        st[key] += 1; stn[key] += ok("coach_checked", s, t); stf[key] += ok("compile", s, t)
for k in st:
    print(f"   alone stop={k}: n={st[k]} note {stn[k]} function {stf[k]}")

print("(b) function broke a task the student passed alone")
for s in WEAK + STRONG:
    for (c, m, t), r in sorted(latest.items()):
        if c == "small_alone" and m == s and not t.endswith("_1") and r["success"] and ("compile", s, t) in latest and not ok("compile", s, t):
            others = {o: ("pass" if ok("compile", o, t) else "fail") for o in WEAK + STRONG if o != s and ("compile", o, t) in latest}
            alone = {o: ("pass" if ok("small_alone", o, t) else "fail") for o in WEAK + STRONG if o != s}
            fr = latest[("compile", s, t)]
            print(f"   {s} {t} d{r['difficulty']} stop={fr['stop_reason']} steps alone {r['n_steps']} with function {fr['n_steps']}"
                  f" | others with function: {others} | teacher alone: {'pass' if ok('cloud_alone', TEACHER, t) else 'fail'}")

print("(c) per built function (scenario) and test variant: students passing with it / students run")
dead = 0; total = 0
per = collections.defaultdict(dict)
for (c, m, t), r in latest.items():
    if c == "compile":
        per[t][m] = r["success"]
dist = collections.Counter()
for t in sorted(per):
    n = len(per[t]); p = sum(per[t].values()); total += 1
    dist[(p, n)] += 1
    if p == 0:
        dead += 1
print("   (passing, run) -> number of test tasks:", dict(sorted(dist.items())))
print(f"   test tasks where NO student passed with the function: {dead} of {total}")
zero = [t for t in sorted(per) if sum(per[t].values()) == 0]
print("   those tasks, teacher alone:", {t: ("pass" if ok("cloud_alone", TEACHER, t) else "fail") for t in zero})
