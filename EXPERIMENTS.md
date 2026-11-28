# Experiments

Everything I ran for Loopy so far, in order. For each experiment the rules were written down and committed before it
ran. Every command is a row in `LOG.md`, and the result files are in `results/`. Full trajectories, notes and functions
stay out of git, because AppWorld asks that its task data not be republished.

The setup: a small model fails an AppWorld task, and the teacher (GLM-5.3-Flash) gives it either a note to read or a
working Python function to call. The question is which kind of help works for which model, and whether it beats paying
the teacher to do the task. All model runs use temperature 0, seed 123, at most 50 steps and one run per task and arm,
on Nebius.

| When | What | Runs | Result | Files |
|---|---|---|---|---|
| Nov 19 | AppWorld install check, no model | none | 138 of 138 tests and 147 of 147 reference solutions pass; doing nothing passes 0 of 57 | `results/env_gate/` |
| Nov 20 | Smoke run | 1 | Qwen3-30B-A3B fails a practice task at the 50-step limit | `results/pilot/smoke/` |
| Nov 20 | Pilot 1: one small model, 9 dev tasks | 30 | small model alone 0 of 9, teacher 9 of 9; on failed tasks the function fixed 5 of 6, a one-shot note 1 of 6 | `results/pilot/standin1/` |
| Nov 20 | Pilot 2: three more small models, same 9 tasks | 53 | the function passed 18 of 18 test runs; a checked note passed 4 of 8, and only the strongest model passed both of its own | `results/pilot/pilot2/`, `docs/paper-direction-2026-11-20.md` |
| Nov 22 to 23 | Stage 1: 5 small models, 30 test scenarios, plus a generic-note control | 993 | weak models' failed tasks: function 69%, checked note 27%, generic note 11%. INCONCLUSIVE by the preset rule, which needed the function at 70% | `experiments/stage1/PROTOCOL.md`, `results/pilot/stage1/analysis_stage1_2026-11-23.json` |
| Nov 24 | Stage 2, part B: the function shown to the weak models as text, not loaded | 138 | code as text fixed 40 of 63, between the note (27) and the loaded function (48). MIXED | `experiments/stage2/PROTOCOL.md`, `results/pilot/stage2b/analysis_part_b_2026-11-24.json` |
| Nov 25 | Stage 2, part A screen: 4 new models alone on 12 tasks | 48 | Nemotron-3-Super-120B (7 of 12) and Qwen3-235B (8 of 12) land in the middle band and are kept | `experiments/stage2/PROTOCOL_PART_A.md`, `results/pilot/stage2a/screen_part_a_2026-11-25.json` |
| Nov 25 | Stage 2, part A: the two kept models through the stage 1 arms | 271 | their failed tasks: note 69%, function 85%, generic note 19%, against 25%, 81% and 11% for the weak models on the same scenarios. CATCHES UP | `experiments/stage2/PROTOCOL_PART_A.md`, `results/pilot/stage2a/analysis_part_a_2026-11-25.json` |

## Designed, not run yet

**Stage 3, designed by Alfredo on Nov 27, to be run by Bill.** It uses GPT-6.2 Sol as the teacher, with the same four
students (the three weak ones and Nemotron-3-Super) on part A's 23 scenarios. Everything is run the same way. The
students' solo runs are reused, so only the teacher's runs and the help arms are new. It tests whether the cheap
teacher's answers hold when renting is expensive. The rules, predictions and the meaning of each result are in
`experiments/stage3/PROTOCOL.md`, and how to run it is in `experiments/stage3/README.md`.

## What it says so far

- For weak models the function is the help that works: on the 23 scenarios that have a function, it fixed 81% of
  their failed tasks and the note 25%.
- For models of middle strength the note catches up (69%), and that holds after taking out what a generic note does.
  The function still fixes a bit more (85%) and is much cheaper per use: it pays back in about 1.5 uses, while the note
  mostly never beats paying the teacher, because this teacher costs about $0.02 a run.
- That is two middle models, one teacher and one benchmark, with one run per cell. Repeats and a second teacher are
  not done.

## Reading behind it

`docs/lit/next-move-2026-11-24.md` has the closest prior work and what is still open, with one note per paper read in
`docs/lit/notes-2026-11-20/` and `docs/lit/notes-2026-11-24/`. PACE (arXiv 2610.02932) already compared renting with
compiling, so we cite it.

## Check it yourself

- `pytest` runs the 124 tests. They use no model and cost nothing.
- `python experiments/stage2/posthoc/recount_part_a.py` and `recount_part_b.py` recount the stage 2 results from the
  committed rows. They are separate from the analysis code and call no model.
- Spend on the provider is in `results/spend_ledger.jsonl`: $59.01 for everything above.
- Known open issues in the harness code are listed in `experiments/stage1/OPEN_REVIEW_FINDINGS.md`.
