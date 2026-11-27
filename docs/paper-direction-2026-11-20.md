# Paper direction after pilot 1, and the design of pilot 2

Written Nov 20, 2026, about 7 PM ET, **before any pilot 2 run**. It is a proposal by Alfredo's side of the
team (the research side). Bill and Harsh have not seen it. Nothing here is frozen.

## 1. What pilot 1 showed (run `standin1`, 9 dev tasks, one run each)

| Arm | Passed | Cost per task | Time per task |
|---|---|---|---|
| Small model alone (Qwen3-30B-A3B) | 0 of 9 | $0.050 | 129 s |
| Cloud model (GLM-5.3-Flash), rent | 9 of 9 | $0.016 | 34 s |
| Small + one-shot coach note, versions 2 and 3 | 1 of 6 | $0.022 | 42 s |
| Small + compiled function, versions 2 and 3 | 5 of 6 | $0.003 | 8 s |

Three flaws make it a harness check, not evidence about coaching: the small model sat at the floor, the coach
note was never checked while the function was checked and repaired, and there is one run per task.

## 2. What is already published (14 papers read in full on Nov 20; notes in `docs/lit/notes-2026-11-20/`)

We can no longer claim any of these as ours:

| Claim | Who has it |
|---|---|
| A weak agent given the right procedure still fails to carry it out | Skill adaptation 2610.33024 ("86% of weak-model runs that still fail with the skill violate a requirement already stated", Sec 3.1); Skill-Use 2608.04828 |
| A text note built from the step where the student went wrong | SkillPivot 2609.29154; D-Skill 2610.28914 (paired traces close 75 to 95% of the gap) |
| A note checked by re-running the weak student, with a repair loop | Skill Transfer 2611.18624 (up to 6 rounds); Teaching the Harness 2611.13144 (admit only after a re-run) |
| Text help has a ceiling for the weakest students | Skill Transfer (Qwen3.5-2B 19.3 to 22.0 against a strong agent at 74.0); Teaching the Harness (Qwen3-1.7B 11.7 in all three arms); Skill adaptation ("what the meta-skill cannot repair is the executor") |
| Compiling pays back within a few uses | PACE 2610.02932; PreAct 2606.17929; FlashScript 2610.33876 |
| A strong model's program lifts a small frozen model | PLVR 2610.19148 (43.0 to 91.2 on tau2 Telecom), though its program raises inference cost and it has no rent arm |
| Predicting whether a skill will help, from history | SkillDelta 2609.32274 (use or skip); SkillApt 2609.26863 (load or abstain) |
| An agent's own forecast is uninformative | SkillDelta (says "use" on over 91% of tasks); SkillApt (17.8% policy accuracy zero-shot); AgentTime 2610.09944 |
| Skills can hurt | Co-evolution trap 2610.20845; Skill Transfer; SkillDelta; ASSAY |

## 3. What is still open in what we read

Four things, and they belong together:

- **C1. Form.** No paper gives the same weak student, for the same failure and from the same teacher, a text
  note in one arm and an executable function in the other. Several say so themselves: Skill adaptation leaves
  "script-based, tool-based, and hard-constraint Skills" to future work, SkillApt does not test executable
  skills, Teaching the Harness leaves enforced plans to future work, and D-Skill asserts the boundary between
  what text can and cannot fix without measuring it.
- **C3. Prediction.** Nobody predicts, before paying, which form of help will work. The teacher predicts
  student failure well in Teaching the Harness (Brier 0.041) but is at coin level on whether its own skill will
  be admitted (0.250).
- **C4. Measured break-even against renting**, on tasks that truly repeat, with failed builds priced.
  Teaching the Harness gives the formula and never fills it in; D-Skill reports cost and no break-even.
- **C5. A per-task choice** among rent, note and function.

NotebookLM, given the same 37 papers and our pilot numbers, answered the same way: no source compares a note
against a program for the same failure, teacher and weak student across students of different strength
(notebook `00282465-3304-4770-9113-4bc39cfe1cf4`, question asked Nov 20, about 6:50 PM).

## 4. The thesis worth testing

> **Advice has a ceiling that depends on the student; a program does not, or much less.** For a weak agent,
> the same teacher's help works as a function it can call long before it works as a note it must follow. As
> the student gets stronger the note catches up, and the function's extra build cost stops being worth it.
> Which form to buy is predictable from the student's strength on the task family, and the choice has a
> measurable break-even against renting.

Why this could be a paper and not a re-run of known results: the ceiling of text (published) and the payoff
of programs (published) have never been put on the same axis, with the same failure, teacher and student.
The interaction between form and student strength is the new measurement; C3, C4 and C5 follow from it.

**What a reviewer will say first, and the answer we need data for:**
1. "Of course the function works, the teacher is doing the task." Answer needed: where the function fails
   (versions that differ in structure), what filling its arguments still demands of the student, and what it
   costs to build including failures.
2. "Your small model is a strawman." Answer needed: several students, at least one that passes a real share
   of tasks alone.
3. "Your coach is a strawman." Answer needed: a coach arm as careful as the best published one (checked by
   re-running the student, repaired).
4. "Nine tasks." Answer needed: the full study, not the pilot.

**What kills it:**
- The function beats the checked note by a wide margin for every student, including the strongest one that
  still has room to improve. Then there is no interaction, "compile if it builds, else rent" is the whole
  policy, and that is PACE with a weaker executor.
- Or the checked note matches the function everywhere. Then form does not matter and the cheaper one wins.

## 5. Pilot 2: is there an interaction at all? (inside the $5 cap; $0.85 spent so far)

Same 9 dev tasks, same teacher (GLM-5.3-Flash), same loop and settings as pilot 1. Run name `pilot2`.

**Students, weakest first.** Qwen3-30B-A3B (pilot 1: 0 of 9). Two candidates screened alone on the 9 tasks:
`google/gemma-3-27b-it` and `openai/gpt-oss-120b`. If both pass 8 or 9, or both pass 0 or 1, one more is
screened (`Qwen/Qwen3.8-27B`). Screening results are reported whatever they are.

**Arms per student**
- alone (9 tasks);
- **checked note** (`coach_checked`): built from version 1, counts only if the student passes version 1 with
  it; up to 2 revisions by the teacher from the new failed run; tested on versions 2 and 3;
- **function** (`compile`): the three functions already built and checked in pilot 1, the same for every
  student, tested on versions 2 and 3;
- rent is the teacher's pilot 1 run (9 of 9).

Skills are built only where the student failed version 1 alone (as in the plan). Where a build fails, the
student has no skill and the task counts as not fixed.

**Readings, fixed now**
- **R1, a usable student:** passes 2 to 7 of the 9 tasks alone.
- **R2, the checked note works for a student:** it fixes at least half of the version 2 and 3 tasks that
  student failed alone.
- **R3, the interaction (the thesis):** supported at pilot scale if the checked note works (R2) for some
  student while, for a weaker student, it does not and the function fixes at least half. Not supported if
  the function fixes at least 2 more tasks than the checked note for every student with at least 2 failed
  test tasks. Unreadable if no student is usable (R1).
- **R4, harm:** any version 2 or 3 task a student passed alone and failed with a skill is listed, by form.
- **R5, cost:** build cost by form including failed builds, and cost and seconds per task by arm.

**What each outcome means**
- R3 supported: write the full-study design around the thesis (more scenarios, three runs per task, test
  split, the predictor).
- Function wins everywhere: no paper from this angle. Keep the class project; the honest finding is that
  compile dominates on AppWorld at these prices.
- No usable student: the ladder needs other models (for example the plan's qwen3:8b on the laptop), not
  another design.

**Limits that stay:** 3 scenarios, one run per task, one teacher, dev split, AppWorld's bare prompt for every
student. A pilot can point; it cannot conclude.
