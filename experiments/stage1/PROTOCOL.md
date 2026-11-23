# Stage 1 protocol (fixed Nov 22, 2026, before any stage 1 run)

Design: `docs/full-study-design-2026-11-20.md`. Alfredo asked for the experiment to be run on Nov 22 without
reviewing this text; the choices below were filled in so it could start, and each differs from the design
only where listed under "Changes from the design".

## What runs (`experiments/stage1/run_stage1.sh`)
- **Tasks:** 30 scenarios from `test_normal`, 10 per difficulty level, drawn by seed
  (`scenarios.json`, seed text `loopy-stage1-scenarios-v1`). 90 tasks. Version 1 is where help is built;
  versions 2 and 3 are the test tasks.
- **Teacher:** GLM-5.3-Flash. It runs all 90 tasks alone (rent) and writes one function per scenario it
  passes on version 1 (checked on version 1, up to 2 repairs).
- **Students:** Gemma-3-27B, gpt-oss-120b, MiniMax-M3.1-Flash, DeepSeek-V4.1-Flash, Qwen3.8-27B.
- **Arms per student:** alone (90 tasks); checked note (built from version 1 where the student failed it,
  counts only if the student passes version 1 with it, up to 2 revisions; tested on versions 2 and 3);
  function (the teacher's function, tested on versions 2 and 3).
- Settings as in the pilots: AppWorld's minimal prompt, temperature 0, seed 123, at most 50 steps, one run
  per task and arm.
- **Money:** a hard cap of $25 in total on the provider ledger (pilots included), checked before every task.

## Analysis, fixed now
- **Unit:** a test task (version 2 or 3) the student failed alone. Scenarios are the clusters.
- **Tiers:** by the student's pass rate alone on the 30 version 1 tasks (not test tasks): lower under 25%,
  upper 50% or more, middle between.
- **H1, primary:** D = note fix rate over upper-tier students minus note fix rate over lower-tier students.
  95% interval by bootstrap over scenarios, 10,000 resamples, seed 123. A test task with no built note counts
  as not fixed.
- **Labels:** SUPPORTED if the interval's lower end is above 0 and the function fixes at least 70% in the
  lower tier. NOT SUPPORTED if D is below 0.15 and the interval includes 0. INCONCLUSIVE otherwise, and also
  if either tier has no student.
- **H2:** (function minus note) in the lower tier minus the same in the upper tier, same bootstrap.
- **Also reported:** fix rates per student and form, harm (passed alone, failed with a skill), build
  success and cost by form including failed builds, cost and seconds per task by arm, break-even against
  renting per scenario, and where function runs fail.
- Numbers are recounted from the raw trajectory files before any is quoted. Anything decided after seeing
  the data is labeled post-data.

## Changes from the design
- No separate screening stage. Two unscreened candidates for the middle of the ladder are included as
  students, and tiers come from version 1 of the confirmatory scenarios.
- Qwen3-30B-A3B is left out: it is slow (about 2 minutes a task) and two other students cover the floor.
- Not collected: the teacher's prediction before a build, note-compliance scoring, the generic-note control.
  So the prediction question (Q3) can only use what the records already hold.
- One run per task. The repeats are stage 2.

## Infrastructure fixes, Nov 22, 2026, 9:10 PM ET (after the teacher arm and 18 of 30 builds, before any student run)
The run was paused to fix three faults in the harness. The design, the arms, the analysis and the decision labels
above are unchanged. No student had run, so no fix was made after seeing any student result.

1. **Replies cut off by the output limit are not attempts.** The teacher thinks before it answers. In 9 of the 18
   function builds it used the whole 16,000-token limit and returned nothing, so those builds never had the
   protocol's three real tries. Now a cut-off reply is sent again with twice the limit, up to 64,000, for coach
   notes and functions alike. All requests are priced. The 9 voided builds are redone from the start; their first
   rows stay in `teach.jsonl` and their cost counts. A build that fails on real attempts stays failed.
2. **A crash inside AppWorld is returned to the agent as a failed execution** instead of ending the run. It happened
   once (`0d01c76_3`, teacher: the agent passed `...` to an API and AppWorld's call logger crashed).
3. **Infrastructure errors are rerun once.** A task that ended in `model_error` is rerun as repeat 2 and repeat 1
   stays in the file. The analysis uses the latest repeat of a task and reports how many were rerun.

Also: parallel processes now take a lock before appending to `runs.jsonl`, `teach.jsonl` and the spend ledger.
