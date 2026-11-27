# Stage 2, part B: the same function, handed over as text

Written Tue Nov 24, 2026, before any run of this arm. Approved by Alfredo the same day. Stage 1 and its protocol
(`experiments/stage1/PROTOCOL.md`) are not changed by anything here. Stage 1 rows are read, never written.

## Why

Stage 1 compared two kinds of help for a student that failed a task:
- a **note**: prose advice, read by the student;
- a **function**: working code, loaded into the student's environment, with instructions to call it and finish.

On the lower tier the function fixed 69% of failed test tasks and the note 27%. But the two differ in two ways at once:
**what is said** (prose, or working code) and **how it arrives** (text the student reads, or a loaded function the
student is told to call). This arm fills the missing cell: working code that arrives as text.

One thing to keep in mind when reading stage 1: the function arm's wrapper tells the student to call the function and
then finish the task. So "the student calls it and stops" is what that arm asks for, not something the student chose.

## The arm (`code_note`)

- For each scenario with a built function, the student gets a note in the **same wrapper as a stage 1 note**
  ("A note from an expert who has done this kind of task before. Follow it unless it clearly does not apply to this
  task:"). The body of the note is fixed text plus the full source of that scenario's function, the same file the
  function arm loads:

  > The expert wrote the Python function below for this kind of task. It is NOT defined in your environment. You can
  > copy it into your code and call it with the right arguments for this task, change it, or use it only as a guide to
  > the steps.

- Nothing is loaded. Whatever the student does with the code, it does itself.
- No teacher call is made. The functions are the 23 built in stage 1.

## What runs

- **Students:** the three lower-tier students of stage 1: gpt-oss-120b, gemma-3-27b, minimax-m3.1-flash.
- **Tasks:** versions 2 and 3 of the 23 scenarios with a built function, 46 tasks per student, 138 runs. This is the same
  task set the function arm ran on.
- **Settings:** `experiments/stage2/config.json`, a copy of the stage 1 config. Every model entry and run setting is
  identical (temperature 0, seed 123, at most 50 steps, same output limits). Only the name and the spending stop differ.
- **Rows** go to `results/pilot/stage2b/`, not into the stage 1 folder.
- **Reruns:** a run is redone only if it ended in an infrastructure error or at a spending stop. The latest run counts.
- The two upper-tier students are **not** part of part B. Running them would cost more than the three lower-tier
  students together, and with 86 tasks passed alone the harm comparison would have little power. If they are run later,
  that is an extension and will be reported as one.

## Budget (budget only)

Stage 1 ended at $43.54 on the ledger. This arm is estimated at $4 to $5, from the per-run cost of the stage 1 note arm
on the same students. The provider stop moves from 49.0 to 52.0 so that a slightly higher cost does not cut the run
short. Per-invocation guards: $2 for Gemma and gpt-oss, $5 for MiniMax, $1 for a redo.

## Measures, fixed now

Units are test tasks a lower-tier student **failed alone** in stage 1, in scenarios with a built function (119 tasks).
Outcomes come from the state-based checker, as in stage 1.

- **Primary set:** the units where that student's checked note was also built (63 tasks). There all three forms exist.
  N = share fixed by the note (stage 1), F = share fixed by the loaded function (stage 1), T = share fixed by the code
  handed over as text (this arm).
- **Primary number:** the share of the function's advantage that survives when the code arrives as text,
  **R = (T - N) / (F - N)**.
- **Interval:** bootstrap over scenarios, 10,000 resamples, seed 123, percentile 2.5 to 97.5. A resample where F - N is
  not above zero, or where the primary set is empty, is undefined: dropped and counted.
- **Label, from the interval of R:**
  - **MOSTLY WHAT IS SAID** if the whole interval is above 0.5;
  - **MOSTLY HOW IT ARRIVES** if the whole interval is below 0.5;
  - **MIXED** otherwise.
- **Secondary:** F - T on all 119 units, same bootstrap. Per student N, F, T.
- **Harm:** on the test tasks a student passed alone, how many the loaded function broke and how many the text broke.
- **Descriptive, from the local raw files:** how often the student wrote the function out in its own code, the pass rate
  when it did, steps taken, and whether the function is short enough to fit the student's output limit. A student cannot
  write out a function longer than its output limit. That is part of what "arrives as text" means, and it is reported,
  not corrected for.
- Nothing is computed until all 138 runs are on file and none ends in an infrastructure error or a spending stop
  (`part_b.py check` prints nothing). The result is written to a file without being printed, then opened once.

## Expectation, written before the run

T lands nearer the note than the function for Gemma and gpt-oss, which rarely carry out a long procedure, and between the
two for MiniMax. That would give MOSTLY HOW IT ARRIVES or MIXED. The opposite result, MOSTLY WHAT IS SAID, would mean a
note should simply contain code. Either is a result.

## What this does not test

- Whether the best form changes with student strength. That needs students between the two tiers (part A, not run).
- Whether the text would break fewer tasks than the loaded function on strong students (not run here).
- One wording of the note. A different sentence around the code could change what students do with it.

---

# Result, Tue Nov 24, 2026

Nothing above this line was changed after the run. The run started 02:45 and ended 04:46 ET on commit 1001794.
All 138 runs are on file, none ended in an infrastructure error or a spending stop, and no run was redone.
Cost: $4.09 (ledger $43.54 to $47.63). The analysis ran once and was opened once:
`results/pilot/stage2b/analysis_part_b_2026-11-24.json`. A second script that shares no code with the first
(`experiments/stage2/posthoc/recount_part_b.py`) gives the same counts.

## The measures fixed before the run

**Label: MIXED.**

On the 63 failed tasks where the student also had a checked note:

| | Note (stage 1) | Code as text (this arm) | Loaded function (stage 1) | R |
|---|---|---|---|---|
| All three students (63) | 27 (43%) | 40 (63%) | 48 (76%) | 0.62 |
| gpt-oss-120b (11) | 2 | 6 | 8 | 0.67 |
| gemma-3-27b (26) | 9 | 13 | 17 | 0.50 |
| minimax-m3.1-flash (26) | 16 | 21 | 23 | 0.71 |

- R = 0.619, interval 0.192 to 1.182, no undefined resample. The interval holds 0.5, so the label is MIXED.
- Secondary, all 119 failed tasks: loaded function 96 (81%), code as text 67 (56%). F - T = 0.244, interval 0.089 to
  0.392. The loaded function beats the same code handed over as text.
- Harm, tasks passed alone (3, 5 and 11 per student): the loaded function broke 1, 1 and 0; the text broke 1, 1 and 1.
  Too few tasks to compare.
- What students did with the code: they almost never wrote the function out (gpt-oss 5 of 46 runs, Gemma 1, MiniMax 0).
  The function was short enough to fit the output limit in 44, 26 and 44 of 46 runs.

**Against the expectation written before the run.** The label is one of the two I expected. The direction is not what I
leaned toward: I expected the text to land nearer the note for Gemma and gpt-oss. It landed nearer the function for
gpt-oss (on 11 tasks), exactly halfway for Gemma, and nearer the function for MiniMax.

## Exploratory, not fixed before the run

These splits were chosen after seeing the result. Difficulty and function length go together, so the two tables are
not two independent findings.

- **Code as text against the note,** same 63 tasks: T - N = 0.206, interval 0.062 to 0.355. Loaded function against
  code as text on those 63: F - T = 0.127, interval -0.045 to 0.311.
- **By AppWorld difficulty, all 119 failed tasks:**

  | Level | Tasks | Loaded function | Code as text |
  |---|---|---|---|
  | 1 | 41 | 34 (83%) | 34 (83%) |
  | 2 | 33 | 26 (79%) | 19 (58%) |
  | 3 | 45 | 36 (80%) | 14 (31%) |

- **By length of the function** (thirds at 3,144 and 8,602 characters): short 34 tasks, function 29, text 28;
  middle 38 tasks, function 31, text 23; long 47 tasks, function 36, text 16.
- **Where no note could be built** (56 tasks): loaded function 48 (86%), code as text 27 (48%). The text arm has no
  check before it is used, so this is not a fair comparison with the checked note.
- **Cost per run on failed tasks** (mean, alone / code as text / loaded function): gpt-oss $0.0127 / $0.0097 /
  $0.0015; Gemma $0.0096 / $0.0078 / $0.0011; MiniMax $0.0906 / $0.0879 / $0.0304. Median steps: 13 / 7 / 2,
  14 / 2 / 1, 32 / 18 / 16.

## Reading

- Both things count. Code helps more than prose even when the student has to carry it out itself, and loading it helps
  again on top. The fixed measure cannot say which counts more.
- The exploratory tables say where loading counts: on easy tasks the code as text does as well as the loaded function,
  and on the hardest tasks it does less than half as well. The loaded function's rate does not move with difficulty.
  That fits the reading that a loaded function replaces the student's own execution, while text has to pass through it.
- Text does not save money. It costs about what the student costs alone. The loaded function costs 3 to 8 times less.

## Limits

One run per student and task. 23 scenarios. Three weak students only. The primary set keeps only tasks where a note
passed its check, which favors students that can follow text. One wording of the text arm. The exploratory splits were
not fixed in advance.
