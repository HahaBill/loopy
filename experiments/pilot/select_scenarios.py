"""Pick the pilot's scenarios: one per AppWorld difficulty level, from the dev split, by a seeded draw.

The pilot plan (CLAUDE.md, Step 1) says "3 AppWorld scenarios x 3 versions each (pick across difficulty
levels, from the dev split)". To keep the choice out of anyone's hands, the scenario for each level is drawn
with a random generator seeded from a fixed text string that is written into the output file.

    .venv/Scripts/python.exe experiments/pilot/select_scenarios.py

Writes experiments/pilot/scenarios.json and refuses to overwrite it. The file holds ids and difficulty
levels only, no task text.
"""

from __future__ import annotations

import argparse
import hashlib
import random
from collections import defaultdict
from pathlib import Path

from loopy.eval.bridge import REPO_ROOT, AppWorldBridge
from loopy.eval.runlog import now_et, write_new_json

SEED_TEXT = "loopy-pilot-scenarios-v1"
OUTPUT = Path(__file__).resolve().parent / "scenarios.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--split", default="dev")
    parser.add_argument("--seed-text", default=SEED_TEXT)
    parser.add_argument("--out", default=str(OUTPUT))
    parser.add_argument("--n", type=int, default=None, help="draw this many scenarios, taking levels in turn")
    args = parser.parse_args()

    task_ids = (REPO_ROOT / "data" / "datasets" / f"{args.split}.txt").read_text(encoding="utf-8").split()
    difficulty_of: dict[str, set[int]] = defaultdict(set)
    versions_of: dict[str, list[str]] = defaultdict(list)
    with AppWorldBridge() as bridge:
        for task_id in task_ids:
            task = bridge.open_task(task_id, experiment_name="pilot_select")
            difficulty_of[task.scenario_id].add(int(task.difficulty))
            versions_of[task.scenario_id].append(task_id)
        bridge.close_task()

    mixed = sorted(scenario for scenario, levels in difficulty_of.items() if len(levels) != 1)
    if mixed:
        raise SystemExit(f"scenarios whose versions differ in difficulty: {mixed}")
    by_level: dict[int, list[str]] = defaultdict(list)
    for scenario, levels in difficulty_of.items():
        by_level[next(iter(levels))].append(scenario)

    seed = int(hashlib.sha256(args.seed_text.encode("utf-8")).hexdigest()[:16], 16)
    generator = random.Random(seed)
    chosen = []
    if args.n:
        pools = {level: generator.sample(sorted(by_level[level]), len(by_level[level])) for level in sorted(by_level)}
        while len(chosen) < args.n and any(pools.values()):
            for level in sorted(pools):
                if pools[level] and len(chosen) < args.n:
                    scenario = pools[level].pop(0)
                    chosen.append({"scenario_id": scenario, "difficulty": level,
                                   "task_ids": sorted(versions_of[scenario]),
                                   "n_candidates_at_this_level": len(by_level[level])})
    for level in ([] if args.n else sorted(by_level)):
        candidates = sorted(by_level[level])
        scenario = generator.choice(candidates)
        chosen.append({
            "scenario_id": scenario,
            "difficulty": level,
            "task_ids": sorted(versions_of[scenario]),
            "n_candidates_at_this_level": len(candidates),
        })

    write_new_json(args.out, {
        "created": now_et(),
        "split": args.split,
        "n_requested": args.n,
        "rule": "(with --n: each level is shuffled by the seeded generator, then levels are taken in turn) one scenario per difficulty level, drawn with random.Random(seed).choice over the sorted "
                "scenario ids of that level, levels visited in ascending order",
        "seed_text": args.seed_text,
        "seed": seed,
        "candidates_by_difficulty": {str(level): sorted(by_level[level]) for level in sorted(by_level)},
        "chosen": chosen,
    })
    for item in chosen:
        print(f"difficulty {item['difficulty']}: {item['scenario_id']} "
              f"(1 of {item['n_candidates_at_this_level']}) -> {', '.join(item['task_ids'])}")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
