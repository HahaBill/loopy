# Stage 2, part A: students of middle strength

Written Wed Nov 25, 2026, about 1:50 AM ET, before any run of a part A model. Stage 1, part B and their protocols are not
changed by anything here. Their rows are read, never written.

Alfredo approved **gate 1 only** (the screen, with a spending stop of $4) on Nov 25. Gate 2 is written down now so that
the screen cannot shape it, but it does not run without his go.

## Why

The paper's claim is that a note's value depends on how strong the student is and a function's does not, or much less.
Stage 1 has three students that pass 4% to 22% of the 23 version 1 tasks used here alone, and two that pass 91%.
Nothing sits between, so
"the note catches up as the student gets stronger" has not been tested. Part A looks for one or two students in the
middle and runs them through the stage 1 arms.

## Gate 1: the screen

- **Candidates** (four models on the provider that no stage has run, prices read from the provider's list on Nov 25):

  | Key | Model | $ per million tokens, in / out | Why |
  |---|---|---|---|
  | `qwen3-235b-instruct` | Qwen/Qwen3-235B-A22B-Instruct-2507 | 0.20 / 0.60 | large older model; its small sibling passed 0 of 10 in the pilots |
  | `nemotron-3-super-120b` | nvidia/nemotron-3-super-120b-a12b | 0.30 / 0.90 | the family PLVR (2610.19148) used |
  | `inkling-2-small` | thinkingmachines/Inkling-2-Small | 0.30 / 1.00 | unknown strength |
  | `nemotron-3.5-lightning` | nvidia/Nemotron-3_5-Lightning | 0.06 / 0.24 | cheapest; a middle student at this price would make gate 2 fit two students |

  The literature note of Nov 24 named MiniMax-M3 as the fourth candidate. It is replaced by Nemotron-3.5-Lightning for
  price only: its smaller sibling used 403,000 input tokens per run in stage 1, and at M3's price that is about $0.13 a
  run, which does not fit gate 2 under the $12 stop whatever it scores.

- **Tasks:** version 1 of 12 of the 23 scenarios that have a built function, in the proportion of the 23 by AppWorld
  difficulty (9, 6 and 8 scenarios, so 5, 3 and 4 tasks). Within each level the first scenario ids in sorted order:
  level 1 `13547f5 166f4ff 31dc501 552869a 59fae45`, level 2 `0d01c76 3aa1a22 522e5e5`,
  level 3 `042a9fc 0de03ea 2c544f9 3b8fb7a`. The rule looks at no result. Checked after fixing it: the five stage 1
  students passed 1, 3, 2, 11 and 10 of these 12, and 1, 5, 5, 21 and 21 of all 23.

  **Change from what Alfredo was told** ("four models on 23 tasks"): 12 tasks, not 23. A run that goes to the step limit
  uses 340,000 to 480,000 input tokens (pilots), so 92 runs at these prices can cost $3 to $7 and would not reliably
  stay under $4. The other 11 version 1 tasks are run in gate 2 for the students that are kept.

- **Arm and settings:** `small_alone`, exactly as in stage 1 (minimal prompt, temperature 0, seed 123, at most 50 steps,
  output limit 4,000 tokens, the forecast question on). Config: `experiments/stage2/config_part_a.json`, a copy of the
  stage 2 config with the four entries added and the provider stop set to 51.63.
- **Money:** the ledger stands at $47.6333. The provider stop is 51.63, so the screen cannot spend more than $4.00.
  Guards per candidate: $1.20, $1.20, $1.20 and $0.40 (Lightning). One request per candidate is sent first to check that
  the model answers (recorded in the ledger under `stage2a_ping`, a fraction of a cent).
- **Reruns:** a run is redone only if it ended in an infrastructure error (`model_error`), at most twice. The latest run
  counts.
- **A candidate cut short by its guard or by the provider stop is out.** This is a budget rule: more than $0.10 a run
  alone does not fit gate 2.
- **Keep rule:** a candidate is **in the band** if it passes 5 to 9 of the 12 (42% to 75%; 4 of 12 is 33%, under the 35%
  stated to Alfredo). In-band candidates are ranked by distance of their pass rate from 55%, ties by lower cost per run.
  Going down that ranking, a candidate is kept if its estimated gate 2 cost fits in what is left of $12 after the screen
  and after the candidates kept before it. At most two are kept. The estimate is `116 x (its mean cost per screen run) +
  $0.60` (57 more runs alone, about 15 note checks, up to 22 note runs, 46 function runs at about a third of the cost,
  about 15 control runs, and the teacher's note builds).
- **If no candidate is in the band, part A ends there.** The four pass rates are reported as they are.
- A 12-task screen is coarse: a model that truly passes 50% lands in the band about 8 times in 10, one that passes 20%
  about 1 time in 14, one that passes 87% about 1 time in 5. The pass rate that goes on the strength axis is measured
  later, on all 23 version 1 tasks.

**Guesses written before the screen** (passes of 12): Qwen3-235B 3 to 6, Nemotron-3-Super 4 to 8, Inkling-2-Small 6 to
10, Nemotron-3.5-Lightning 2 to 6. My chance that at least one lands in the band: about 65%.

## Gate 2 (not approved, not run): the kept students through the stage 1 arms

- **Scenarios:** the 23 with a built function. No new function is built. The teacher is GLM-5.3-Flash, as in stage 1.
- **Arms per kept student,** same code and settings as stage 1: alone on the other 11 version 1 tasks and on versions 2
  and 3 (46 tasks); checked note, built from version 1 where the student failed it, kept only if the student passes
  version 1 with it, up to 2 revisions, tested on versions 2 and 3; the teacher's function on versions 2 and 3; the
  generic note on the units defined below.
- **Before any note is built:** open review items 4, 5 and 7 (`experiments/stage1/OPEN_REVIEW_FINDINGS.md`) are fixed.
- **Money:** the provider stop moves to 59.63 ($12.00 above $47.6333 for all of part A).

### Measures, fixed now

- **Unit:** a test task (version 2 or 3) the student failed alone, in a scenario with a built function where the student
  also failed version 1 alone. This is stage 1's primary set (note-eligible scenarios), limited to the 23 scenarios
  where both forms can exist. Scenarios are the clusters.
- **N, F, C:** the share of units fixed by the checked note (no built note counts as not fixed), by the function, and by
  the generic note.
- **Reference, stage 1 lower tier under this exact rule** (three students pooled, from stage 1 rows, computed Nov 25
  before any part A run): 108 units; note 27 (25%), function 87 (81%), generic note 12 (11%).
- **Primary:** D_A = N of the part A students (pooled) minus N of the lower tier. 95% interval by bootstrap over the 23
  scenarios, both groups resampled together, 10,000 resamples, seed 123, percentile 2.5 to 97.5. A resample where either
  group has no unit is undefined: dropped and counted.
- **Net of the control:** D_A_net = D_A minus (C of the part A students minus C of the lower tier), same bootstrap. This
  matters more here than in stage 1: a student of middle strength fails partly by chance, so any second try fixes some
  of its failures. The generic note measures that.
- **Label, from the rule of stage 1:**
  - **CATCHES UP** if the interval of D_A has its lower end above 0. It is quoted as the thesis only if the interval of
    D_A_net also has its lower end above 0; otherwise it is reported as "not separated from a generic note".
  - **DOES NOT** if D_A is below 0.15 and its interval includes 0.
  - **UNDECIDED** otherwise, and also if no student is kept or the control cannot finish.
  Stage 1's extra condition (the function fixes at least 70% in the lower tier) is dropped: on these 23 scenarios it is
  81% by construction.
- **Secondary:** the gap F minus N for the part A students against the lower tier's (0.56), same bootstrap; F against the
  lower tier's F; N, F and C per student against the student's pass rate alone on the 23 version 1 tasks, with the five
  stage 1 students on the same axis; harm (tasks passed alone and failed with the note, with the function); cost and
  steps per run by arm; break-even against renting, failed builds priced.
- Nothing is computed until every run is on file and none ends in an infrastructure error or a spending stop. The result
  is written to a file without being printed, then opened once. A second script that shares no code recounts it.

### Predictions, written before any run

P1 to P3 of `docs/lit/next-move-2026-11-24.md` stand as written on Nov 24. In numbers, for a student that passes about
55% alone: note 45% to 65% of its units, function 70% to 85%, generic note 15% to 35%.

- My chance that the note's rate is above the lower tier's 25% by 15 points or more: about 60%.
- My chance that the label is CATCHES UP and separated from the generic note: about 35%. One or two students give 15 to
  40 units from about 10 to 20 scenarios, so the interval will be wide. UNDECIDED is a realistic outcome, for the third
  time.

**What kills the thesis:** the part A students' note rate is no higher than the lower tier's net of the generic note,
while the function stays far ahead. Then the honest paper is "compile if it builds, else rent".

## Limits

One teacher, one benchmark, one run per task and arm. One or two students of middle strength, chosen by a 12-task
screen. Only scenarios where a function was built, which flatters the function's level for every student alike.
Students differ in more than strength (family, size, training), so strength is not isolated.

---

# Gate 1 result, Wed Nov 25, 2026

Nothing above this line was changed after the run, with one correction: the first line said "2:15 AM". The file was
written at about 1:50 AM and committed at 1:55 AM (d5a3646), before the first request to any part A model.

The screen ran from 01:56:44 to 02:10:51 ET on commit c7a1d79. All 48 runs are on file. None ended in an infrastructure
error or at a spending stop, and none was redone. Cost: $1.68 on the rows (ledger $47.6333 to $49.3113, which includes
$0.0003 for the four test requests). `part_a.py check` prints nothing. The decision was written to
`results/pilot/stage2a/screen_part_a_2026-11-25.json` and opened once. A recount from the raw trajectory files, with code
that does not use `part_a.py`, gives the same counts.

| Candidate | Passed of 12 | By level (of 5, 3, 4) | Cost per run | By the rule |
|---|---|---|---|---|
| Nemotron-3-Super-120B | 7 (58%) | 4, 1, 2 | $0.034 | in the band, kept (nearest 55%) |
| Qwen3-235B | 8 (67%) | 4, 2, 2 | $0.025 | in the band, kept |
| Inkling-2-Small | 10 (83%) | 4, 3, 3 | $0.062 | above the band |
| Nemotron-3.5-Lightning | 4 (33%) | 4, 0, 0 | $0.019 | below the band, by one task |

- **Both in-band candidates are kept.** Estimated gate 2 cost by the formula above: $4.58 and $3.51, $8.09 together.
  With the screen that is $9.77 of the $12 stop.
- **Against the guesses written before the screen:** Qwen3-235B was guessed at 3 to 6 and passed 8, so that guess was
  wrong. The other three landed inside their guessed ranges. At least one candidate landed in the band, as guessed.
- Nemotron-3.5-Lightning is out by one task. A 12-task screen cannot tell 33% from 42%; the rule is applied as written.
- Gate 2 has not started. It waits for Alfredo's go.

---

# Gate 2 setup, Wed Nov 25, 2026, 3:40 AM ET (before any gate 2 run)

Alfredo approved gate 2 at 3:15 AM ("Yes", to "Start gate 2 for both students, with the hard stop at $12 for all of
part A?"). Nothing in the gate 2 rules above changes. This section only says how they are carried out.

- **Review items 4, 5 and 7 are fixed in the note builder** (`experiments/pilot/build_coach_checked.py`, tests in
  `tests/test_note_build_fixes.py`). 4: a build whose validation is interrupted writes everything a restart needs, and
  the restart goes on with the same conversation, the attempts already used and the spend already paid. 5: with
  `--source-run`, the run's own rows win over the source run's, and each trajectory is read from the folder of the row
  used. 7: every request of a note build goes to the ledger as `build_coach_checked <student> <scenario>`. The function
  builder is not changed: gate 2 builds no function.
- **Files:** `config_part_a_gate2.json` (the gate 1 config with the provider stop at 59.63 and the scenario file below;
  no model entry or run setting changes), `scenarios_part_a.json` (the 23 scenarios with a built function, in stage 1's
  order), `run_part_a_gate2.sh`, `part_a_gate2.py`. Rows go to `results/pilot/stage2a/`, next to the screen's, so the
  12 screen runs count as those version 1 alone runs. The screen's own check (`part_a.py check`) will now list the
  gate 2 rows as rows that are not screen runs; that is expected and changes nothing, since its decision is written.
- **Order per student, as in stage 1:** alone (57 runs), note builds from version 1 with the teacher's stage 1 runs
  (`--source-run stage1`), the note on versions 2 and 3 where a note was built, the function on versions 2 and 3, the
  generic note on the units. A missing run, or one ended by an infrastructure error or a spending stop, is done again
  at most twice. No build starts until the student's 69 alone runs are all on file and counted.
- **Guards per invocation** (dollars; alone, builds, note, function, control): Nemotron-3-Super 3.5, 1.5, 1.0, 1.2, 1.0;
  Qwen3-235B 3.0, 1.5, 1.0, 1.0, 1.0; $0.50 for a redo. They add up to more than the stop on purpose: the provider stop at
  59.63 is the hard limit for both students together.
- **Analysis code:** units, harm and break-even with failures priced come from stage 1's own functions
  (`build_units`, `break_even_including_failures` in `experiments/stage1/analyze_stage1.py`). With that code, stage 1's
  rows give the lower-tier reference written above (108 units; note 27, function 87, generic note 12), checked at
  3:35 AM before any gate 2 run. The bootstrap and the label follow the rules above (`part_a_gate2.py`).

---

# Gate 2 result, Wed Nov 25, 2026

Nothing above this line was changed after the run. Two clock times in the setup section are wrong: "3:40 AM" and
"3:35 AM" should both read about 3:20 AM. The setup was committed at 3:25:22 AM (a1bcefb) and the run started at
3:25:29 AM.

The run went from 3:25 to 5:22 AM ET, all on commit a1bcefb: 271 runs and 46 note decisions for the two students.
`part_a_gate2.py check` prints nothing.
- **One run was redone.** A generic-note run of Nemotron-3-Super was stopped by its invocation guard ($1.00) and redone,
  as the rules allow. The two control tasks that invocation never reached were run at the same time.
- No other run was redone, and no build was interrupted.
- **Cost:** gate 2 $9.70 (runs $7.98, note builds $1.72). All of part A cost $11.38 of the $12.00 stop (ledger $47.63 to
  $59.01). My estimate of $8.09 for gate 2 was low by about 20%, mostly from Nemotron-3-Super's note builds ($1.26) and
  its generic-note runs ($0.08 each).
- Nov 26, before publishing: two mentions of a personal account balance were removed from this file (one in the gate 2
  rules, one here). No rule, number of the experiment or result changed.

The analysis ran once. It was written to `results/pilot/stage2a/analysis_part_a_2026-11-25.json` and opened once. A
second script that shares no code with it (`experiments/stage2/posthoc/recount_part_a.py`) gives the same counts, and
its intervals with five seeds agree to within 0.01. In the result file, `run_facts` counts the two kept students' 24
screen runs together with the gate 2 runs.

## The measures fixed before the run

**Label: CATCHES UP, separated from the generic note.**

| | Alone, version 1 of 23 | Units | Note | Function | Generic note |
|---|---|---|---|---|---|
| Lower tier, stage 1 (3 students) | 1, 5, 5 | 108 | 27 (25%) | 87 (81%) | 12 (11%) |
| Part A (2 students) | 13, 13 | 26 | 18 (69%) | 22 (85%) | 5 (19%) |
| Nemotron-3-Super-120B | 13 | 14 | 10 | 12 | 3 |
| Qwen3-235B | 13 | 12 | 8 | 10 | 2 |

- **D_A** = 0.442, interval 0.176 to 0.692. **D_A_net** = 0.361, interval 0.128 to 0.622. No resample was undefined.
  Both lower ends are above 0.
- The lower tier's numbers are exactly the reference written before the run (108, 27, 87, 12).
- **Secondary:** the function's lead over the note fell from 56 points (lower tier) to 15 points (part A). The
  difference is -0.402, interval -0.741 to -0.105. The function's own rate did not move: F_A - F_low = 0.041, interval
  -0.139 to 0.181.
- **Harm**, on test tasks the student passed alone:

  | Student | Tasks passed alone | Note broke | Function broke |
  |---|---|---|---|
  | Nemotron-3-Super-120B | 26 | 0 of the 4 with a note | 2 |
  | Qwen3-235B | 22 | 2 of the 8 with a note | 3 |

- **Note builds:** 10 attempted per student. Nemotron-3-Super built 9 and failed 1 ($1.26). Qwen3-235B built 10 of 10
  ($0.46).
- **Break-even against renting, failed builds priced** (stage 1's definition): the note never pays back in 10 of 13
  student-scenarios, with a median of 4.1 uses for the 3 that do. The function never pays back in 2 of 24, with a median
  of 1.5 uses. A run guided by the note costs the student $0.050 (Nemotron-3-Super) and $0.022 (Qwen3-235B); the
  teacher alone costs $0.022 a run on average.

**Against the predictions written before the run:**

| Prediction | Predicted | Observed |
|---|---|---|
| Note rate for a student at about 55% alone | 45% to 65% | 69%, above the range |
| Function rate | 70% to 85% | 85%, at the top |
| Generic note rate | 15% to 35% | 19% |
| Note beats the lower tier's 25% by 15 points or more | my chance about 60% | yes, by 44 points |
| CATCHES UP and separated from the generic note | my chance about 35% | yes |

Of the Nov 24 predictions: P1 (the function's rate does not depend on the student) and P2 (the note's rate rises with
the student's own rate) fit. P3 (at 50% or more alone the note matches or beats the function, and the function breaks
some passed tasks) holds only in its second half: the note fixed 18 of 26 against the function's 22, and the function
broke 5 of 48 passed tasks.

## Exploratory, not fixed before the run

- **Where the gap comes from.** Part A's 26 units come from 12 scenarios, and every one of them had a built note. Of
  the lower tier's 108 units, 45 had no built note. On units with a built note only, the note fixed 27 of 63 (43%) in
  the lower tier and 18 of 26 (69%) in part A. That difference has an interval of 0.006 to 0.53. Both pieces point the
  same way: weak students more often cannot use a note at all, and when they can, it fixes less.
- **Inside part A,** the function minus the note is 0.154, interval -0.23 to 0.48. With 26 units the two forms cannot
  be told apart on fix rate. That does not show they are equal.
- **By AppWorld difficulty,** part A units:

  | Level | Units | Note | Function |
  |---|---|---|---|
  | 1 | 4 | 3 | 3 |
  | 2 | 10 | 7 | 7 |
  | 3 | 12 | 8 | 12 |

  The function's remaining lead is all on the hardest tasks, as in part B.
- **Cost per run** (alone / note / function / generic note): Nemotron-3-Super $0.048 / $0.050 / $0.006 / $0.082;
  Qwen3-235B $0.030 / $0.022 / $0.004 / $0.024.

## Reading

- **The first half of the thesis holds,** by the rule written before the run. For students of middle strength the note
  fixes far more of their failures than for weak students (25% to 69%), net of what any second try does. The function's
  rate stays where it was (81% to 85%).
- **The cost half does not, in this setup.** At middle strength the function still fixes at least as many failures and
  costs a fraction per run. It pays back in one or two uses, while the note mostly never does against renting this
  teacher. The teacher is cheap: its own run costs about what a note-guided student run costs. "Compile if it builds,
  else rent" is still the better buy for these students. The note is close on accuracy, not on cost.
- **Where the note still trails** is the hardest tasks.

## Limits

- Two students of middle strength, both at 13 of 23 alone, and 26 units from 12 scenarios.
- One teacher, one benchmark, one run per task and arm.
- The part A students differ from the lower tier in family and size, not only in strength.
- The screen that picked them used 12 of the version 1 tasks that also give their strength.
- The break-even reading depends on a teacher that costs about $0.02 a run. A dearer teacher would change it.
