"""Independent recount of stage 2 part A, gate 2, plus exploratory breakdowns. Reads rows only, writes nothing.

It imports neither part_a_gate2.py nor the stage 1 analysis. Which notes were built is read from which note runs exist
(the note arm ran only where a note was built), not from teach.jsonl. Everything after the line "EXPLORATORY" was not
fixed before the run.
"""
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
S1 = ROOT / "results/pilot/stage1/runs.jsonl"
S2 = ROOT / "results/pilot/stage2a/runs.jsonl"
TEACH2 = ROOT / "results/pilot/stage2a/teach.jsonl"
SCENARIOS = ROOT / "experiments/stage2/scenarios_part_a.json"
LOWER = ["gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash"]
UPPER = ["deepseek-v4.1-flash", "qwen3.8-27b"]
PART_A = ["nemotron-3-super-120b", "qwen3-235b-instruct"]
TEACHER = "glm-5.3-flash"


def load(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def latest(rows):
    out = {}
    for r in rows:
        key = (r["condition"], r["model_key"], r["task_id"])
        if key not in out or r["repeat"] >= out[key]["repeat"]:
            out[key] = r
    return out


def units_of(rows, students, scenarios):
    units = []
    for s in students:
        for sc in scenarios:
            if rows[("small_alone", s, f"{sc}_1")]["success"] or not rows[("cloud_alone", TEACHER, f"{sc}_1")]["success"]:
                continue
            for v in (2, 3):
                t = f"{sc}_{v}"
                alone = rows[("small_alone", s, t)]
                if alone["success"]:
                    continue
                note = rows.get(("coach_checked", s, t))
                units.append({"student": s, "scenario": sc, "task": t, "difficulty": alone["difficulty"],
                              "built": note is not None, "N": int(bool(note and note["success"])),
                              "F": int(rows[("compile", s, t)]["success"]),
                              "C": int(rows[("generic_note", s, t)]["success"])})
    return units


def share(us, key):
    return sum(u[key] for u in us) / len(us)


def contrast(a, low):
    if not a or not low:
        return None
    d = share(a, "N") - share(low, "N")
    return {"D_A": d, "D_A_net": d - (share(a, "C") - share(low, "C")),
            "gap_diff": (share(a, "F") - share(a, "N")) - (share(low, "F") - share(low, "N")),
            "F_diff": share(a, "F") - share(low, "F")}


def boot(a, low, scenarios, seeds=(123, 1, 2, 3, 4), resamples=10000):
    by_a, by_l = defaultdict(list), defaultdict(list)
    for u in a:
        by_a[u["scenario"]].append(u)
    for u in low:
        by_l[u["scenario"]].append(u)
    out = []
    for seed in seeds:
        rng = random.Random(seed)
        vals, undefined = defaultdict(list), 0
        for _ in range(resamples):
            picks = [rng.choice(scenarios) for _ in scenarios]
            point = contrast([u for p in picks for u in by_a[p]], [u for p in picks for u in by_l[p]])
            if point is None:
                undefined += 1
                continue
            for k, v in point.items():
                vals[k].append(v)
        line = {"seed": seed, "undefined": undefined}
        for k, v in vals.items():
            v.sort()
            line[k] = (round(v[int(0.025 * (len(v) - 1))], 3), round(v[int(0.975 * (len(v) - 1))], 3))
        out.append(line)
    return out


def main():
    scenarios = [c["scenario_id"] for c in json.loads(SCENARIOS.read_text(encoding="utf-8"))["chosen"]]
    s1, s2 = load(S1), load(S2)
    L1, LA = latest(s1), latest(s1 + s2)
    low = units_of(L1, LOWER, scenarios)
    up = units_of(L1, UPPER, scenarios)
    a = units_of(LA, PART_A, scenarios)
    gate2 = [r for r in s2 if r["model_key"] in PART_A]
    print(f"scenarios {len(scenarios)} | gate 2 rows {len(gate2)} by arm {dict(Counter(r['condition'] for r in gate2))}")
    print("stop reasons, latest gate 2 rows:", dict(Counter(r["stop_reason"] for k, r in LA.items() if k[1] in PART_A)))
    print("redone:", sum(1 for r in gate2 if r["repeat"] > 1), "| commits:", sorted({r["git_commit"][:7] for r in gate2}))

    print("\nFIXED BEFORE THE RUN")
    for name, us in (("lower tier", low), ("part A", a)):
        print(f"  {name:10s} units {len(us):3d}  note {sum(u['N'] for u in us):3d}  function {sum(u['F'] for u in us):3d}"
              f"  generic {sum(u['C'] for u in us):3d}")
    print("  point:", {k: round(v, 3) for k, v in contrast(a, low).items()})
    for line in boot(a, low, scenarios):
        print("  interval", line)
    print("\nper student (v1 alone of 23; units; note, function, generic; harm on test tasks passed alone)")
    for group, rows, students in (("lower", L1, LOWER), ("upper", L1, UPPER), ("part A", LA, PART_A)):
        us_all = {"lower": low, "upper": up, "part A": a}[group]
        for s in students:
            us = [u for u in us_all if u["student"] == s]
            v1 = sum(bool(rows[("small_alone", s, f"{sc}_1")]["success"]) for sc in scenarios)
            passed = [f"{sc}_{v}" for sc in scenarios for v in (2, 3) if rows[("small_alone", s, f"{sc}_{v}")]["success"]]
            note_broke = sum(1 for t in passed if ("coach_checked", s, t) in rows and not rows[("coach_checked", s, t)]["success"])
            note_n = sum(1 for t in passed if ("coach_checked", s, t) in rows)
            fn_broke = sum(1 for t in passed if not rows[("compile", s, t)]["success"])
            print(f"  {group:6s} {s:24s} v1 {v1:2d}/23  units {len(us):2d}  N {sum(u['N'] for u in us):2d}  "
                  f"F {sum(u['F'] for u in us):2d}  C {sum(u['C'] for u in us):2d}  | passed alone {len(passed):2d}: "
                  f"note broke {note_broke} of {note_n}, function broke {fn_broke}")

    print("\nEXPLORATORY (not fixed before the run)")
    print(f"  scenarios with a unit: lower tier {len({u['scenario'] for u in low})}, part A {len({u['scenario'] for u in a})}")
    for name, us in (("lower tier", low), ("part A", a)):
        built = [u for u in us if u["built"]]
        print(f"  {name:10s} units with a built note {len(built)} of {len(us)}: note {sum(u['N'] for u in built)}, "
              f"function {sum(u['F'] for u in built)}, generic {sum(u['C'] for u in built)}")
    built_low = [u for u in low if u["built"]]
    print("  part A minus lower tier, note rate on units with a built note only, interval by seed:",
          [line["D_A"] for line in boot(a, built_low, scenarios)])
    within = defaultdict(list)
    for u in a:
        within[u["scenario"]].append(u)
    for seed in (123, 1, 2):
        rng, vals = random.Random(seed), []
        for _ in range(10000):
            picks = [u for p in (rng.choice(scenarios) for _ in scenarios) for u in within[p]]
            if picks:
                vals.append(share(picks, "F") - share(picks, "N"))
        vals.sort()
        print(f"  part A, function minus note, seed {seed}: {share(a, 'F') - share(a, 'N'):.3f}, interval "
              f"({vals[int(0.025 * (len(vals) - 1))]:.3f}, {vals[int(0.975 * (len(vals) - 1))]:.3f})")
    for s in PART_A:
        us = [u for u in a if u["student"] == s]
        built = [u for u in us if u["built"]]
        print(f"  {s:24s} units with a built note {len(built)} of {len(us)}: note fixed {sum(u['N'] for u in built)}, "
              f"function {sum(u['F'] for u in built)}, generic {sum(u['C'] for u in built)}")
    for d in (1, 2, 3):
        us = [u for u in a if u["difficulty"] == d]
        if us:
            print(f"  part A, level {d}: units {len(us)}  note {sum(u['N'] for u in us)}  function {sum(u['F'] for u in us)}"
                  f"  generic {sum(u['C'] for u in us)}")
    print("  cost per run and median steps, gate 2 rows (latest):")
    for s in PART_A:
        line = f"    {s:24s}"
        for arm in ("small_alone", "coach_checked", "compile", "generic_note"):
            rs = [r for k, r in LA.items() if k[0] == arm and k[1] == s]
            if rs:
                line += (f"  {arm}: n={len(rs)} ${statistics.mean(r['cost_usd'] for r in rs):.4f} "
                         f"{statistics.median(r['n_steps'] for r in rs):g} steps")
        print(line)
    if TEACH2.exists():
        teach = load(TEACH2)
        for s in PART_A:
            last = {r["scenario_id"]: r for r in teach if r["small_model_key"] == s}
            print(f"  note builds {s}: {dict(Counter(r['status'] for r in last.values()))}, "
                  f"cost ${sum(r['cost_usd'] for r in teach if r['small_model_key'] == s):.4f}")
    print(f"\ngate 2 cost on run rows: ${sum(r['cost_usd'] for r in gate2):.6f}")


if __name__ == "__main__":
    main()
