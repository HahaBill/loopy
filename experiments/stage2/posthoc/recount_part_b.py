"""Independent recount of stage 2 part B, plus exploratory breakdowns. Reads rows only, writes nothing.

It does not import part_b.py. Which notes and functions were built is taken from which runs exist in stage 1
(the note arm and the function arm only ran where the note or function was built), not from the teach file.
Everything after the line "EXPLORATORY" was not fixed before the run.
"""
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
S1 = ROOT / "results/pilot/stage1/runs.jsonl"
S2 = ROOT / "results/pilot/stage2b/runs.jsonl"
SKILLS = ROOT / "results/pilot/stage1/raw_large/skills/shared"
STUDENTS = ["gpt-oss-120b", "gemma-3-27b", "minimax-m3.1-flash"]


def load(path):
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def latest(rows):
    out = {}
    for r in rows:
        key = (r["condition"], r["model_key"], r["task_id"])
        if key not in out or r["repeat"] > out[key]["repeat"]:
            out[key] = r
    return out


def pct(k, n):
    return f"{k}/{n} ({100 * k / n:.0f}%)" if n else "0/0"


def boot(units, stat, seeds=(123, 1, 2, 3, 4), resamples=10000):
    by = defaultdict(list)
    for u in units:
        by[u["scenario"]].append(u)
    names = sorted(by)
    out = []
    for seed in seeds:
        rng = random.Random(seed)
        vals, undefined = [], 0
        for _ in range(resamples):
            sample = [u for name in (rng.choice(names) for _ in names) for u in by[name]]
            v = stat(sample)
            if v is None:
                undefined += 1
            else:
                vals.append(v)
        vals.sort()
        lo = vals[int(0.025 * (len(vals) - 1))]
        hi = vals[int(0.975 * (len(vals) - 1))]
        out.append((seed, round(lo, 3), round(hi, 3), undefined))
    return out


def share(key):
    return lambda us: sum(u[key] for u in us) / len(us) if us else None


def recovered(us):
    us = [u for u in us if u["N"] is not None]
    if not us:
        return None
    n, f, t = (sum(u[k] for u in us) / len(us) for k in ("N", "F", "T"))
    return (t - n) / (f - n) if f - n > 0 else None


def main():
    s1, s2 = latest(load(S1)), latest(load(S2))
    tasks = sorted({k[2] for k in s2})
    print(f"part B rows on file: {len(s2)}; tasks: {len(tasks)}; scenarios: {len({t.split('_')[0] for t in tasks})}")
    print("stop reasons:", dict(Counter(r["stop_reason"] for r in s2.values())))
    print("errors:", sum(1 for r in s2.values() if r["error"]))

    units, harm = [], defaultdict(lambda: Counter())
    for s in STUDENTS:
        for t in tasks:
            alone, fn, tx = s1[("small_alone", s, t)], s1[("compile", s, t)], s2[("code_note", s, t)]
            note = s1.get(("coach_checked", s, t))
            if alone["success"]:
                harm[s]["passed_alone"] += 1
                harm[s]["broken_function"] += not fn["success"]
                harm[s]["broken_text"] += not tx["success"]
                if note:
                    harm[s]["note_runs"] += 1
                    harm[s]["broken_note"] += not note["success"]
                continue
            units.append({
                "student": s, "task": t, "scenario": t.split("_")[0], "difficulty": alone["difficulty"],
                "F": int(fn["success"]), "T": int(tx["success"]), "N": int(note["success"]) if note else None,
                "rows": {"alone": alone, "function": fn, "text": tx, "note": note},
            })

    both = [u for u in units if u["N"] is not None]
    rest = [u for u in units if u["N"] is None]
    print(f"\nFIXED BEFORE THE RUN\nunits failed alone: {len(units)}; with a built note too: {len(both)}")
    for name, us in [("pooled", both)] + [(s, [u for u in both if u["student"] == s]) for s in STUDENTS]:
        n, f, t = (sum(u[k] for u in us) for k in ("N", "F", "T"))
        r = (t - n) / (f - n) if f != n else float("nan")
        print(f"  {name:20s} n={len(us):3d}  note {n:2d}  function {f:2d}  text {t:2d}  R={r:.3f}")
    print("  R interval by seed (seed, low, high, undefined):", boot(both, recovered))
    f_all, t_all = sum(u["F"] for u in units), sum(u["T"] for u in units)
    print(f"  all {len(units)} units: function {pct(f_all, len(units))}, text {pct(t_all, len(units))}")
    print("  F - T interval by seed:", boot(units, lambda us: share("F")(us) - share("T")(us)))
    print("  harm:", {s: dict(c) for s, c in harm.items()})

    print("\nEXPLORATORY (not fixed before the run)")
    print("T - N on the built-note units, interval by seed:",
          boot(both, lambda us: share("T")(us) - share("N")(us)))
    print("F - T on the built-note units, interval by seed:",
          boot(both, lambda us: share("F")(us) - share("T")(us)))
    print(f"units with no built note ({len(rest)}): function {pct(sum(u['F'] for u in rest), len(rest))}, "
          f"text {pct(sum(u['T'] for u in rest), len(rest))}")
    print(f"note counted as no fix where not built, all {len(units)} units: "
          f"{pct(sum(u['N'] or 0 for u in units), len(units))}")

    print("\ncross-tab on built-note units (note, text, function) -> count")
    for key, c in sorted(Counter((u["N"], u["T"], u["F"]) for u in both).items()):
        print("  ", key, c)
    print("cross-tab on all units (text, function) -> count")
    for key, c in sorted(Counter((u["T"], u["F"]) for u in units).items()):
        print("  ", key, c)

    print("\nby student, all failed-alone units")
    for s in STUDENTS:
        us = [u for u in units if u["student"] == s]
        print(f"  {s:20s} n={len(us)}  function {pct(sum(u['F'] for u in us), len(us))}  "
              f"text {pct(sum(u['T'] for u in us), len(us))}")
    print("by difficulty, all failed-alone units")
    for d in sorted({u["difficulty"] for u in units}):
        us = [u for u in units if u["difficulty"] == d]
        print(f"  level {d}: n={len(us)}  function {pct(sum(u['F'] for u in us), len(us))}  "
              f"text {pct(sum(u['T'] for u in us), len(us))}")

    print("\nscenario agreement: text fixes both versions / one / none, per student")
    for s in STUDENTS:
        per = defaultdict(list)
        for u in units:
            if u["student"] == s:
                per[u["scenario"]].append(u["T"])
        print(f"  {s:20s}", dict(Counter(f"{sum(v)} of {len(v)}" for v in per.values())))

    lengths = {}
    for t in tasks:
        f = SKILLS / t.split("_")[0] / "compiled_workflow.py"
        if f.exists():
            lengths[t.split("_")[0]] = len(f.read_text(encoding="utf-8"))
    if lengths:
        cut = sorted(lengths.values())
        lo, hi = cut[len(cut) // 3], cut[2 * len(cut) // 3]
        print(f"\nby function length in characters (thirds at {lo} and {hi}), all failed-alone units")
        for s in STUDENTS:
            for name, test in [("short", lambda n: n < lo), ("middle", lambda n: lo <= n < hi), ("long", lambda n: n >= hi)]:
                us = [u for u in units if u["student"] == s and u["scenario"] in lengths and test(lengths[u["scenario"]])]
                print(f"  {s:20s} {name:6s} n={len(us):2d}  function {pct(sum(u['F'] for u in us), len(us))}  "
                      f"text {pct(sum(u['T'] for u in us), len(us))}")
    else:
        print("\nfunction sources not found under", SKILLS, file=sys.stderr)

    print("\nsteps and cost per run on failed-alone units (median steps, mean cost in USD)")
    for s in STUDENTS:
        us = [u for u in units if u["student"] == s]
        line = f"  {s:20s}"
        for arm in ("alone", "note", "text", "function"):
            rs = [u["rows"][arm] for u in us if u["rows"][arm]]
            line += (f"  {arm}: {statistics.median(r['n_steps'] for r in rs):g} steps, "
                     f"${statistics.mean(r['cost_usd'] for r in rs):.4f} (n={len(rs)})")
        print(line)
    print("stop reasons by student, text arm, all 46 tasks")
    for s in STUDENTS:
        print(f"  {s:20s}", dict(Counter((r["stop_reason"], r["success"]) for k, r in s2.items() if k[1] == s)))
    print(f"\npart B cost on the rows: ${sum(r['cost_usd'] for r in s2.values()):.6f}")


if __name__ == "__main__":
    main()
