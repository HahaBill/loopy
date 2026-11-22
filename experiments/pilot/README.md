# The pilot: how to run it, and every choice the plan left open

The plan is `CLAUDE.md`, "Step 1: the pilot". This file does not change it. It records how the plan was
turned into commands, so that anyone can see which choices came from the plan and which were filled in.
Written Nov 20, 2026, **before any pilot arm ran**.

## Commands, in order

Python is `.venv/Scripts/python.exe` on Windows and `.venv/bin/python` elsewhere. `<small>` and `<cloud>` are
keys under `models` in `config.json`.

```bash
# 0. once per machine: the environment gate (no model, no cost)
.venv-appworld/Scripts/python.exe experiments/appworld_env_check.py

# 1. small model alone on all 9 tasks, with the "will you fail?" forecast
python experiments/pilot/run_arm.py --run-name pilot1 --condition small_alone --model <small>

# 2. cloud model on the tasks the small model failed
python experiments/pilot/run_arm.py --run-name pilot1 --condition cloud_alone --model <cloud> \
    --only-failed-of results/pilot/pilot1/runs.jsonl --failed-model <small>

# 3a. build a coach note and a compiled workflow from version 1 of each scenario
python experiments/pilot/build_skills.py --run-name pilot1 --small-model <small> --cloud-model <cloud>

# 3b. test both on versions 2 and 3
python experiments/pilot/run_arm.py --run-name pilot1 --condition coach   --model <small> --versions 2,3 \
    --skills-dir results/pilot/pilot1/raw_large/skills
python experiments/pilot/run_arm.py --run-name pilot1 --condition compile --model <small> --versions 2,3 \
    --skills-dir results/pilot/pilot1/raw_large/skills
```

Add `--dry-run` to see what a command would run. Every command appends to `results/pilot/pilot1/` and needs a
row in `LOG.md`. Commit the scripts before running, so each result points at a commit.

## Open items for the team (the plan does not settle these)

- **O-1. Which models.** The plan says "an open ~8B model" for the small model (the README names `qwen3:8b`)
  and names no cloud model. `config.json` lists candidates; none is chosen.
- **O-2. Does a hosted 27B to 30B model count as "small"?** Nebius hosts nothing near 8B. A hosted
  Qwen3-30B-A3B is cheap and needs no GPU, but it is not what a laptop without a big GPU would run.
- **O-3. How the four pilot signals are read.** The plan lists them without numbers. Proposed readings are
  below. Agree on them before the first arm runs, or the reading becomes a judgment made after seeing data.
- **O-4. Scenarios where the small model passes version 1.** As written, nothing is learned there
  (interpretation I-8). The alternative is to learn from the first version it fails.
- **O-5. AppWorld's sharing rule.** Its license asks that task data and anything derived from it not be
  republished in plain text. Trajectories, coach notes and compiled functions therefore stay in `raw_large/`
  (gitignored). Decide whether to publish them encrypted with `appworld pack`, or not at all.

## Proposed readings of the four signals (not agreed yet)

With 9 tasks these are coarse on purpose.

1. **The small model fails often:** `small_alone` fails at least 3 of the 9 tasks.
2. **Coach or compile fixes new versions:** among the version 2 and 3 tasks that `small_alone` failed, coach or
   compile passes at least half.
3. **No option always wins:** the cheapest option per solved task (rent, coach or compile, counting the cost
   of teaching) is not the same in all three scenarios.
4. **The forecast tracks outcomes:** over the small model's runs, the forecast separates failures from passes
   with AUROC of at least 0.65 (the threshold the literature review named). Not computable if every run
   passes or every run fails.

The plan's rule then applies: 3 or 4 signals = scale to about 30 scenarios; 2 = a class project, swap the
forecast source; 0 or 1 = change the model or the tasks.

## Choices filled in (each can still be changed before the pilot runs)

- **I-1. Scenarios.** One per difficulty level from the dev split, by a seeded draw
  (`select_scenarios.py`, seed text `loopy-pilot-scenarios-v1`): `d4e9306`, `37a8675`, `530b157`.
- **I-2. Agent.** AppWorld's published minimal ReAct prompt, unchanged, with its defaults: temperature 0,
  seed 123, at most 50 steps. One change: up to 1,500 output tokens per step (4,000 for cloud models) instead
  of 400, so that models that think before answering are not cut off.
- **I-3. Reading a reply.** Code inside ``` fences is unwrapped, `<think>` blocks are dropped, and a reply
  with no code is not executed (the model is told so).
- **I-4. What the model sees.** Each output is cut to 8,000 characters (start and end kept). Old steps are
  dropped only when the prompt would exceed the model's context budget in `config.json`.
- **I-5. The forecast.** One separate request before step 1, with a fixed question (`FORECAST_QUESTION` in
  `src/loopy/agent/react.py`). It is not part of the run's history. The last number in the reply, from 0 to
  100, is the probability of failing. In coach and compile runs the model sees the note or workflow first.
- **I-6. Failure type.** Bug-level: the run never declared the task done (step limit, context overflow, model
  error, cost cap) or its last step raised an error. Quality-level: it declared the task done and the
  checker says it is wrong.
- **I-7. Cloud runs.** Only on tasks the small model failed, as the plan says.
- **I-8. What is learned from.** Version 1, and only where the small model failed it and the cloud model
  passed it. Other scenarios are recorded as skipped.
- **I-9. Coach.** One request to the cloud model, which reads both runs and writes a note of at most 12
  lines. The note is placed right before the task statement.
- **I-10. Compile.** One function `workflow(apis, ...)`. It counts as built only if it solves version 1
  again in a fresh copy of the apps. Up to 2 repair tries, which see the run's output and pass or fail, not
  the checker's test descriptions. The small model sees the signature and docstring; the function is
  already defined in its environment.
- **I-11. Cost.** Tokens times the provider's listed price on the day. A small model served by a host is
  priced at the host's price and marked `runs_locally: false`. "Cloud calls" counts requests to the model in
  the cloud role only, including the requests that build skills.
- **I-12. Repeats.** One run per task and condition. The proposal's three runs per task are for the full
  study.
