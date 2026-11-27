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

## Infrastructure fix, Nov 23, 2026, 1:27 AM ET (after 29 of 30 function builds had a result, before any student run)
Alfredo approved this fix ("Yes, fix it"). The design, the arms, the analysis and the decision labels are unchanged.
No student had run. The fix makes the code do what fix 1 above already says: a reply cut off by the output limit is
not an attempt.

1. **Two kinds of cut-off were still counted as attempts.** A reply still empty at the 64,000-token ceiling, and a
   reply stopped partway through its text (finish reason "length" with some text). Of the 4 rebuilt functions that had
   failed by then, 3 lost tries this way (986aa4e all 3, ffe6d5e and f861c32 one each). 270f1ff failed on three real
   tries and stays failed.
2. **Now:** any reply with finish reason "length" is sent again with twice the limit, up to 64,000, and once more at
   64,000. If it is still cut off, the build ends with status `cut_off`. It does not use up an attempt.
3. **In the analysis:** a `cut_off` build has no skill, so its test tasks count as not fixed, as with any failed build.
   `cut_off` builds are reported separately from builds that failed on real attempts, by form and by student.
4. **Redone from the start:** 986aa4e, f861c32 and ffe6d5e, plus d18139b, whose rebuild was stopped by the pause.
   Their earlier rows stay in `teach.jsonl` and their cost counts. Builds that passed are kept.

## Second infrastructure fix, Nov 23, 2026, 1:48 AM ET (before any student run)
The first rebuild after the fix above (ffe6d5e) was cut off four times and ended with no real attempt, although the
same request had produced a whole reply earlier. So the limit of two requests at 64,000 was too low. The run was
paused again. The design, the arms, the analysis and the decision labels are unchanged.

1. A request is now sent up to three times at 64,000 before the build ends as `cut_off`. This replaces "once more at
   64,000" above. ffe6d5e is redone with the other three builds.
2. A cost-cap stop in the middle of a request no longer loses the paid usage. The build is recorded as `cost_cap` and
   resumes on the next run.
3. The note-build limit is now $4 for every student (it was $2 to $3). A weak student fails more tasks, so it has more
   notes to build. A low limit would stop those students first and count their unbuilt notes as not fixed, which would
   inflate D. The $25 total cap is unchanged.
4. If any build ends as `cost_cap`, or the $25 cap stops a student before its arms finish, stage 1 is reported as
   incomplete and goes to Alfredo before any decision label is read.
5. `experiments/pilot/analyze.py` now reads outcomes from the latest repeat of a task and keeps every row in the spend.
   The two pilots have no reruns, so their numbers do not change.

## Third infrastructure fix, Nov 23, 2026, 2:00 AM ET (before any student run)
These changes only affect what happens if the money runs out and how completion is reported. The design, the arms, the
analysis and the decision labels are unchanged.

1. Parallel jobs now stop at $24.00 on the ledger, so requests already in flight stay under the $25 cap.
2. A build stopped by the cost cap is recorded as `cost_cap` with what it paid, including a note check the cap
   interrupted. It is not resumed, which replaces "resumes on the next run" above: restarting it could give it more
   than three attempts. Stage 1 is then incomplete and goes to Alfredo.
3. The runner writes `STAGE1 DONE` only if every required run and build is on file. Otherwise it writes
   `STAGE1 INCOMPLETE` with the reasons (`sweep.py check`).
4. `analyze.py` reads success from the latest repeat and counts the dollars and calls of every repeat.

## Analysis implementation, Nov 23, 2026, 03:22 ET (written before any student run)
Stage 1 keeps running on commit faf6f24. Nothing here changes what it runs. `analyze_stage1.py` implements the analysis
above. These are the choices the text left open.

1. A tier's fix rate is pooled over its test tasks. Bootstrap intervals are percentile intervals, with tiers held at
   their observed assignment and the same resamples for every estimate. Resamples where a rate is undefined are dropped
   and counted. A test task with no built function counts as not fixed, as with notes.
2. The script computes nothing until every required run and build is on file and `runs.jsonl` matches the raw files.
3. **Two checks declared now, before any student result.** Neither replaces the primary analysis above.
   - *Note-eligible scenarios:* only scenarios where the student failed version 1 and the teacher passed it. The protocol
     builds a note only in those scenarios, so the written rule counts a test task as "not fixed by a note" in scenarios
     where no note was ever attempted. This falls mostly on stronger students, who pass more of version 1, so it pushes D
     and H2 down. On made-up data the two readings gave D = 0.09 and D = 0.71. **Which one is primary is Alfredo's call,
     and it must be made before anyone reads a student result.**
   - *Equal weight per student:* each student's rate counts once, instead of pooling tasks.
4. **Correction to the third fix, item 1:** "stay under the $25 cap" is too strong for the code stage 1 is running. If
   spend got close to $24, parallel jobs could pass $25 (an offline replay reached $25.11). Code after faf6f24 writes
   every request to the ledger as it returns, so the overshoot is at most one request in flight per job.

## Primary analysis settled, Nov 23, 2026, 11:06 ET (no student run on file)
Alfredo left this call to scientific judgment ("only data change if you feel you should and helps us, be scientist
about this"). No student had run, so no result could inform it. This replaces item 3 of the section above on which
reading is primary. The tiers, thresholds, bootstrap and label rules are unchanged.

1. **Primary H1 and H2 use the note-eligible scenarios:** the student failed version 1 and the teacher passed it. Those
   are the only scenarios where the protocol tries to build a note, so note and function are compared on the same tasks
   and the same pre-treatment selection. The reading first written is still computed and reported as secondary.
2. **The change raises the upper tier's note rate, so it could flatter the thesis.** A stronger student can also flip a
   failure to a pass from any change to its prompt. So the generic-note control from the design, dropped when stage 1
   was set up, comes back: a fixed general note (`GENERIC_NOTE` in `src/loopy/skills/coach.py`, written without looking
   at any task or failure), in the same wrapper as a real note, on exactly the primary test tasks, run once per task
   after stage 1 (`run_control.sh`), inside the same $25 cap.
3. **What may be quoted as the thesis.** D_net = D minus the same difference for the generic note, with the same
   bootstrap. A SUPPORTED label counts as the thesis only if D_net's interval has its lower end above 0. Otherwise it is
   reported as "not separated from a generic note". If the control cannot finish, the result is not quoted.
4. **Known limits, stated now.** Stronger students' failed scenarios are probably harder, which works against the
   thesis. The upper tier will have few primary tasks, so INCONCLUSIVE is a realistic outcome.

## Budget change, Nov 23, 2026, 15:44 ET (budget only)
Stage 1 stopped at the $24 ledger stop at 13:14 with $24.45 spent. Missing at the stop: 95 of 450 alone runs, 86 of
150 note decisions, the function tests of three students, and the control. No analysis was run (the analyzer refuses
incomplete data) and no student result was read; only row counts and costs were looked at.

1. **The total cap goes from $25 to $50; the ledger stop goes from $24.00 to $49.00** (`config.json`, commit eff4b1c on
   the run checkout). Alfredo approved it at 15:40. The control now runs inside the $50 cap.
2. **Why the first budget was wrong:** it was projected from the first student runs. Later tasks cost about twice as
   much (Qwen3.8 $0.111 a run against $0.059; MiniMax $0.057 against $0.027).
3. **Nothing else changes:** models, tasks, prompts, seeds, per-step limits, scoring and the label rules are the same.
   Finished runs are kept; the runner skips them and continues. Runs that ended as `cost_cap` are not results and are
   redone.
4. Rows written after the restart carry commit eff4b1c instead of faf6f24. The only difference between the two is the
   cap number.
5. **The three runs the cap cut short are redone as repeat 2** (small_alone: qwen3.8-27b 3b8fb7a_3, deepseek-v4.1-flash
   522e5e5_2, minimax-m3.1-flash 83a7951_2). The runner treats any row on file as finished and only redoes
   `model_error` rows, so these would never have been redone. They are rerun by hand with the same command the runner
   uses for infrastructure errors (`--repeat 2 --max-usd 1`); repeat 1 stays on file and the analysis reads the latest
   repeat. All three are test tasks, so no note decision depends on them. Started 15:46, log
   `raw_large/console_capredo.log`.
6. **Pause and second stop, same day.** The run was paused at 16:10 at Alfredo's request (laptop closed; 3 jobs in
   flight stopped, ledger row of $0.65 as an upper estimate) and resumed at 19:46. At 22:45 it ended as
   `STAGE1 INCOMPLETE`: MiniMax reached the per-step limits of its note tests ($2) and function tests ($1), which left
   two runs as `cost_cap` (coach_checked 90adc3f_3, compile 0de03ea_2) and 7 function test runs not started. The two
   are redone by hand as repeat 2 with the runner's rerun command, and the runner is started again for the 7 missing
   runs (each start gets the same per-step limits). The limits themselves are unchanged. Ledger at the stop $39.07.
7. **Control: per-student spend guard raised from $2 to $4 before any control run** (22:55). MiniMax has 40 control
   tasks at about $0.06 to $0.07 a run, so the $2 guard would have cut its last runs short, as it did in stage 1. The
   guard is a safety limit, not part of the design; the $50 total cap still applies. Stage 1 reported `STAGE1 DONE` at
   22:51:35 with $39.29 on the ledger. Control tasks per student: gemma 39, gpt-oss 47, minimax 40, deepseek 1, qwen 4.

## After-review changes, Nov 24, 2026, 01:30 ET (after the result; no stage 1 number changes)

The stage 1 result was computed once, on Nov 23 (`results/pilot/stage1/analysis_stage1_2026-11-23.json`). A code review
before the push then found six faults. They are fixed in commit bc2f5ac. No model was run and no row was edited.

1. **Break-even (a secondary reported number).** The first measure reads only the failed test tasks a skill fixed. So it
   leaves out failed skill runs, failed builds and builds that fixed nothing. It is kept as it was and its numbers are
   unchanged (note: 22 student-scenarios, 10 never pay back, median 4.685 uses; function: 54, 11, 1.73). A second
   measure, `break_even_including_failures`, is added next to it. **It is post hoc:** it was written after the result
   was read, so it is not part of the analysis fixed before the students ran. It has one row per student, form and
   scenario where a build was attempted and the student has a failed test task that the teacher passed. Cost per use =
   mean skill run cost, failed runs included, plus the share of those tasks the skill did not fix times the mean rent
   cost. Uses to break even = build cost, all attempts, over (mean rent cost minus cost per use). A failed build never
   pays back. Result: note, 65 student-scenarios, 55 never pay back (28 failed builds, 13 built notes that fixed
   nothing), median 11.935 uses over the other 10. Function, 75 student-scenarios, 30 never pay back (11 failed builds,
   6 built functions that fixed nothing), median 1.73 uses over the other 45. On the note-eligible scenarios only, the
   function has 65, 27 and 1.765. *These were the first version's numbers. The fallback cost was changed the same
   night: see the second review round below, item 1.*
2. **Builders.** A build that the spend limit stopped before its first request was written down as `cost_cap`, and a
   restart skipped it. Now it leaves no record and the next start builds it. Latent: `teach.jsonl` has no `cost_cap`
   row.
3. **Control runner.** `run_control.sh` wrote `CONTROL FINISHED` without looking at what its workers did. Now it
   collects their exit statuses, and it writes the marker only when every control task of every student has a run that
   is not `model_error` or `cost_cap` (`sweep.py control-check`). Otherwise it writes `CONTROL INCOMPLETE` with the
   reason and exits 1. Latent: all 131 control runs are on file and none was cut short.
4. **Analyzer.** It would compute a result marked COMPLETE with control runs missing. Now it refuses, as it does for
   any other missing run. This is the rule of Nov 23, 11:06: if the control cannot finish, the result is not quoted.
   The Nov 23 run had the full control.
5. **Completeness check.** `sweep.py check` compared counts. Now it compares task and scenario ids with
   `scenarios.json` and names what is missing or outside it. Latent: the stage 1 files pass the stricter check.
6. **Arm runner.** `--skills-dir` together with `generic_note` would have replaced the fixed note with nothing, and
   the run would have been recorded as a control. Now `run_arm.py` refuses `--skills-dir` for `generic_note`,
   `small_alone` and `cloud_alone` before any request. Latent: the recorded control commands have no `--skills-dir`,
   and the analyzer's recount found the note in every control run.

**The Nov 23 file stays the result of record.** The analyzer was run again after the fixes, on commit bc2f5ac, to
`results/pilot/stage1/analysis_stage1_2026-11-24_postreview.json`. All 968 values of the Nov 23 file were in it,
unchanged. The only addition was the second break-even block. Tests: 88 passed. That file was replaced at 01:47 by the
run described next.

### Second review round, Nov 24, 2026, 01:47 ET (commit 52996e9)

The review ran again on the fixed tree and found seven more faults. Item 2 is the correction in the next section. The
other six are below. No model was run and no row was edited. Tests: 94 passed.

1. **Post hoc break-even, changed.** The first version charged the mean rent of a scenario's tasks for each task the
   skill did not fix. Now each such task is charged its own rent: what the teacher's run of that task cost. Cost per
   use = mean over the tasks of (skill run cost, plus that task's rent if the skill did not fix it). New result: note,
   65 student-scenarios, 55 never pay back, median 14.015 uses over the other 10 (first version 11.935). Function, 75
   student-scenarios, 30 never pay back, median 1.76 uses over the other 45 (first version 1.73). On the note-eligible
   scenarios only, the function has 65, 27 and 1.805. The measure is still post hoc. The first, preset measure is
   unchanged.
3. **Skipped builds.** A build marked `skipped_cloud_failed` passed the completeness check even if the teacher's latest
   version 1 run of that scenario was a pass. Now `sweep.py check` reports it, and the same for `skipped_small_passed`
   against the student's latest version 1 run. Latent: the four skipped function builds (d6ac34d, 634f342, 652485c,
   1150ed6) each have one teacher version 1 run, a failure, and every skipped note agrees with its runs.
4. **Rebuilds after the output-limit fix.** `sweep.py voided` listed only the four builds audited by hand. Resuming an
   early checkpoint would have kept other early failures whose rows do not say how many replies were cut off. Now a
   failed function build whose latest row has no `cut_off_requests` count is rebuilt too. The hand audit list is
   unchanged. Latent: on the finished files this selects nothing. All nine early failures have later rows with the
   count, and 270f1ff stays failed.
5. **Control retries.** A control run that ended at a spend limit could never be rerun. The first pass skips recorded
   tasks, and the retry took only `model_error` rows at repeat 1. Now `sweep.py control-retry` lists the control tasks
   whose latest run did not count, and `run_control.sh` reruns them once per start at the latest repeat plus one, with
   the $1 retry guard. The stage 1 runner's own retry rule (`infra`) is unchanged. Latent: no control row is `cost_cap`
   or `model_error`.
6. **Runs outside the scenario file.** The checks now flag note, function and control runs on tasks that are not
   version 2 or 3 of a chosen scenario. Latent: there are none.
7. **Start of the control.** `run_control.sh` trusted the `STAGE1 DONE` line in the log. Now it also requires
   `sweep.py check` to pass on the rows on file, and refuses to start otherwise. Latent.

### Third review round, Nov 24, 2026, 02:16 ET (commit ef667e9)

The review ran a third time and found six more faults. No model was run and no row was edited. Tests: 105 passed.

1. **A run's row could miss a paid request. Measured on stage 1: 1 run, $0.001093.** A model reply is charged to the
   budget, and so to the ledger, as soon as it returns. If AppWorld then raised while running that reply's code, the
   step was never stored, and the run's row summed only stored steps. So the row was one request short, in requests,
   tokens and dollars. Now the reply is counted from the moment it is charged, and the raw file keeps it too. A run
   whose grading breaks now also gets a row (`model_error`, redone like any other) instead of none.
   **Known under-count.** `experiments/stage1/ledger_vs_rows.py` compares every run's row with the ledger
   (`results/pilot/stage1/ledger_vs_rows_2026-11-24.json`). All 993 runs were matched. For the teacher, alone,
   note-test and function-test arms (862 runs) the ledger has one row per run, with the task in its note. For the
   control (131 runs) it has one row per request, matched by time; runs that share a boundary second are compared as
   one sum. **One run differs:** the teacher's first try at 0d01c76_3 (repeat 1, ended in a bridge error, redone as
   repeat 2). Its row says $0.007211 and the ledger $0.008304, so the row is one request, $0.001093, short. Among the
   862 runs with one ledger row each, no other run differs by more than rounding. For the control, runs that share a
   boundary second (121 of the 131) are checked as group sums only, so two opposite errors inside one group would not
   show; their sums agree. All runs together: rows $32.837323, ledger $32.838424. The 72 note builds match their
   ledger rows too. So the teacher's total cost in the report is $0.001093 low. The row is not edited. **The ledger is
   the spend of record.**
2. **The control's start gate from round 2 was too wide.** `sweep.py check` also counted control runs that ended in an
   infrastructure error or at a spend limit. So a control with such a run could not start again to repair it. Now the
   stage check does not read the control's runs; `control-check` and `control-retry` do. A sandbox test runs the real
   `run_control.sh` and `sweep.py` on made-up rows, with a stand-in for `run_arm.py`: a control run that ended at a
   spend limit at repeat 2 is run again as repeat 3. Latent: no control row is `cost_cap` or `model_error`.
3. **Validation runs that the infrastructure ended.** In the note builder, a validation run that ended in a provider
   or bridge error counted as a failed attempt of the note. It used up a revision and could end the build as
   `failed_validation`. Now such a run is not an attempt. It is started again, three starts at most. If it still
   cannot run, or a spend limit stopped it, the build stays pending: no row is written and the next start builds it.
   What was paid is in the ledger and in a log file beside the skill. The function builder treats a bridge failure
   during its validation the same way. Latent: all 160 validation attempts in the note build logs ended as
   `completed` or `max_steps`, with steps. The note results stand.
4. **Stale skips.** Round 2 made the check report a skipped build that the latest version 1 runs no longer support.
   The builders still treated it as done. Now both builders decide such a build again. Latent: every skip agrees
   with its runs.
5. **Recount.** The analyzer's recount opened the raw file of the latest repeat only, and compared the outcome only.
   Now it opens every repeat, because earlier tries are summed into costs and tokens, and it also compares requests,
   tokens, dollars and model seconds with the raw file. On the stage 1 files: 993 raw files, no difference. The
   recount cannot see the lost request of item 1. That reply is not in the raw file either, which is why the ledger
   comparison exists.
6. **Runs that should not exist.** The checks now flag a control run on a task that is not a control task of that
   student, note or function test runs with no built note or function behind them, and runs of a model or arm that
   is not part of stage 1. Latent: there are none.

The post-review file was run again on commit ef667e9. Its comparison with the Nov 23 file is the same as after round
2: the six corrected values of the equal-weight check and nothing else. Its recount block has two new entries.

## Correction, Nov 24, 2026, 01:47 ET: undefined resamples in the equal-weight check

**What the protocol says.** "Analysis implementation, Nov 23, 03:22", item 1: "Resamples where a rate is undefined are
dropped and counted."

**What the code did.** The equal-weight check (item 3 of that section) counts each student's rate once. A resample can
leave a student with no eligible task. The code then averaged over the students who were left in the tier and kept
the resample, so the tier stood for different students from one resample to the next. This happened in 3,992 of the
10,000 resamples: the draws that left one of DeepSeek (1 eligible task) and Qwen3.8 (4) with none. The 431 draws that
left both with none were already dropped. No draw leaves a lower-tier student with none. Now a resample that leaves
any student of a tier with no eligible task is undefined, so it is dropped and counted (commit 52996e9).

**What changes.** Only the bootstrap intervals of the equal-weight check (`sensitivity_equal_weight_per_student`):

| Value | Nov 23 file | Corrected |
|---|---|---|
| Undefined resamples (D and H2) | 431 of 10,000 | 4,423 of 10,000 |
| D, 95% interval | 0.608 to 0.814 | 0.607 to 0.811 |
| H2, 95% interval | 0.295 to 1.439 | 0.309 to 1.016 |

**What does not change.** The point estimates of this check (D = 0.717, H2 = 0.656; in the observed data every student
has tasks) and its label, INCONCLUSIVE. Nothing else changes either: the primary reading, the reading as first
written, the generic-note control, every label and the claim are the same. The pooled readings never had this fault,
because a pooled tier rate is defined as long as any student of the tier has a task.

**Files.** The Nov 23 file is not edited. `analysis_stage1_2026-11-24_postreview.json` is run with `--corrects` (first
on commit 52996e9, last on ef667e9). It reproduces 962 of the 968 values of the Nov 23 file exactly, and it lists the other six with
their old and new values under `corrections_to_analysis_stage1_2026-11-23`. The only added block is the post hoc
break-even.
