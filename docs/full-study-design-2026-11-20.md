# Full-study design: advice or program? (proposal, not frozen)

Written Nov 20, 2026, after pilots 1 and 2. A proposal from the research side for Alfredo to change or approve.
Bill and Harsh have not seen it. Nothing here has been run. Background: `docs/paper-direction-2026-11-20.md`.

## 1. The claim, in one sentence
For a weak agent that fails a repeating task, help from a stronger model works as a **function it can call**
long before it works as a **note it must follow**; the note only starts to work once the student is strong
enough, and which form to buy can be told in advance.

## 2. What the pilots showed and what they cannot show
Four students, same 9 dev tasks, same teacher, one run per task (`results/pilot/pilot2/summary.json`):

| Student | Passed alone | Failed test tasks | Fixed by checked note | Fixed by function |
|---|---|---|---|---|
| Qwen3-30B-A3B | 0 of 9 | 6 | 0 | 5 |
| Gemma-3-27B | 0 of 9 | 6 | 1 | 6 |
| gpt-oss-120b | 0 of 9 | 6 | 1 | 6 |
| Qwen3.8-27B | 6 of 9 | 2 | 2 | 2 |

They cannot show a curve: three students sit at the floor and the fourth has two failed test tasks in one
scenario. They also show something against the simple story: the function was cheaper to build and to run
than the note for every student. So the paper cannot be "pick the cheaper form". It is a measurement of where
advice stops working and a program still does, and of whether that can be predicted.

## 3. Questions and hypotheses
- **H1 (primary, the interaction).** Among test tasks a student fails alone, the checked note fixes a larger
  share for stronger students than for weaker ones, while the function fixes most of them for both.
- **H2 (the gap closes).** The function's advantage over the note shrinks as the student gets stronger.
- **Q3 (prediction).** Before paying, can we tell whether a note will be enough? Candidates: the student's
  pass rate on other tasks, the teacher's own prediction asked before any build, the teacher's diagnosis
  label, features of the failed run (steps, error share, gave up or not), the student's self-forecast.
- **Q4 (economics).** Break-even against renting per scenario, in dollars, cloud calls and seconds, with
  failed builds priced.
- **Q5 (policy).** Replayed over the measured table: always rent, function first with rent as fallback, note
  first, a strength-threshold rule, and an oracle. Cost per solved task and success.
- **Q6 (limits of the function).** Where does a function fail on a new version, and what does filling its
  arguments still demand of the student? This is the answer to "the teacher is just doing the task".

## 4. Design

**Tasks.** AppWorld 0.1.0 data.
- Development set (prompts, the predictor, tier cut-offs): the 16 dev scenarios not used in the pilots and
  the 30 train scenarios.
- Confirmatory set: 30 scenarios from `test_normal` (56 available), a seeded draw stratified by difficulty,
  90 tasks. This is the "30 scenarios" the Oct 26 proposal promised. Version 1 is where help is built;
  versions 2 and 3 are the test tasks. Learning within a test scenario is the point of the study, so results
  are not comparable to AppWorld's leaderboard, and the paper says so.

**Teacher.** GLM-5.3-Flash (9 of 9 in pilot 1). A second teacher is a stretch goal.

**Students.** At least four, spread over strength. Known: Qwen3-30B-A3B, Gemma-3-27B and gpt-oss-120b at the
floor, Qwen3.8-27B at 6 of 9. Stage 0 screens for one or two in the middle (candidates on Nebius:
DeepSeek-V4.1-Flash, MiniMax-M3.1-Flash, Nemotron-3-Super-120b) and, if Alfredo approves the download,
the plan's own qwen3:8b on the laptop. Strength tiers are fixed from the development set, before any
confirmatory run: lower = passes under 25% alone, upper = 50% or more, middle = between.

**Arms, per student and scenario**
1. alone (all 3 versions);
2. checked note: built from version 1 only where the student failed it; counts only if the student passes
   version 1 with it; up to 2 revisions;
3. function: one per scenario, built from the teacher's passing version 1 run, checked on version 1, up to 2
   repairs; the same function for every student;
4. rent: the teacher alone on all 3 versions;
5. control, on a subset: a generic note (general AppWorld advice, not about the failure), to separate
   "this note" from "any note".

Both forms get the same repair budget, are checked on version 1 only, and never see the checker's test
descriptions. Every build attempt is priced, including the student's re-runs for the note.

**Runs.** Stage 1: one run per task and arm. Stage 2, only if H1 is supported in stage 1: two more runs of
the test tasks for arms 1 to 3, so each has three (the proposal's three runs per task) and a noise floor.

**What is recorded.** As now (pass by AppWorld's checker, tokens, dollars, cloud calls, seconds, steps,
failure type, forecast), plus: the teacher's prediction before the build, whether the student's run with the
note actually did what the note said (scored from its API calls), and for function runs whether the miss was
in the arguments or inside the function.

## 5. Analysis, fixed before the confirmatory runs
- **Unit.** A test task (version 2 or 3) that the student failed alone. Scenarios are the clusters.
- **Primary statistic (H1).** D = note fix rate in the upper tier minus note fix rate in the lower tier.
  95% interval by bootstrap over scenarios, 10,000 resamples. A task with no built note counts as not fixed.
- **Decision labels.** SUPPORTED: the interval's lower end is above 0 and the function fixes at least 70% in
  the lower tier. NOT SUPPORTED: D below 0.15 and the interval includes 0. INCONCLUSIVE: anything else.
- **H2.** (function minus note) in the lower tier minus the same in the upper tier, same bootstrap.
- **Q3.** AUROC for "the checked note fixes this test task", fitted on the development set, reported on the
  confirmatory set. Baselines: the student's tier alone, and chance.
- **Q4, Q5.** Counts and replays from the run table; no model calls.
- **Harm.** Share of test tasks passed alone and failed with a skill, by form.
- **Verification.** An independent recount from the raw trajectory files by a reviewer who does not get the
  analysis code, before any number is quoted.
- Anything decided after seeing confirmatory data is labeled post-data.

## 6. What would make this not a paper
- The function fixes about as much as the note for the upper tier and far more for the lower tier, but the
  note fix rate does not rise with strength (H1 not supported). Then the result is "compile dominates", which
  PACE and PLVR already imply.
- Functions fail often on new versions in the larger set. Then pilot 2's 23 of 24 was luck of three
  scenarios and the contrast weakens. That is still a finding (Q6), but a different paper.
- A paper appears that runs the same contrast. Re-check the citing trails of Skill Transfer (2611.18624) and
  Teaching the Harness (2611.13144) before writing.

## 7. Threats a reviewer will raise
- One benchmark, one teacher, AppWorld's bare prompt for every student.
- Strength is varied by swapping models, so size, family and training differ together.
- Hosted models are not fully deterministic at temperature 0.
- The note is written for one student and the function for none. A student-agnostic note is a stage 2 arm
  if time allows.

## 8. Cost and time (estimates from pilot prices, not quotes)
- Stage 0, ladder screen on dev: about $2.
- Stage 1: about $25 (alone runs dominate; Qwen3.8-27B costs about 7 cents a task, the others 1 to 5).
- Stage 2: about $25 more.
- Money so far: $2.50 of a $5 cap, all prepaid credit. Stage 1 does not fit under that cap.
- Compute time: stage 1 is roughly 8 to 12 hours unattended, no GPU.

| When | What |
|---|---|
| by Sun Nov 22 | Stage 0; Alfredo edits or approves this design and the budget; the team is told |
| Mon Nov 23 | Freeze the protocol (Alfredo's call), draw the 30 scenarios |
| Nov 24 to 27 | Stage 1 runs |
| Nov 28 to 30 | Analysis, independent recount, paper go or no-go (the Nov 30 decision already on the calendar) |
| Dec 1 to 3 | Stage 2 if supported |
| Dec 4 to 6 | Slides and demo for Dec 7 |
| Dec 8 to 15 | Report and repository |

For the class, stage 1 alone already gives baselines, an ablation by form, significance by bootstrap, cost and
error analysis, which is what the rubric scores. The paper needs stage 2 and the predictor.

## 9. Decisions that are Alfredo's
1. This thesis, or a different one.
2. Budget: raise the cap for stage 1 (about $25).
3. Freezing the protocol before stage 1.
4. The 5 GB download for qwen3:8b on the laptop.
