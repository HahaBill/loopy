# Stage 1: review findings still open (Nov 24, 2026)

An automated code review ran before each push of the stage 1 results. Three rounds of its findings were fixed
(see "After-review changes" in `PROTOCOL.md`). The fourth round's findings below are **not fixed yet**. This push
went out with them open, on purpose, so the team can see the result.

What was checked against the stage 1 files for each one is stated. None of them changes a stage 1 number, except
item 1, which is a choice about one descriptive number.

| # | Where | Finding | Effect on stage 1 |
|---|---|---|---|
| 1 | `analyze_stage1.py`, first break-even measure | A scenario is left out of the measure when the teacher failed any of its test versions, even if the skill and the teacher both solved another version. Counting per task would bring back 2 note and 4 function comparisons and move the function's median from 1.73 to 1.51 uses. | A choice, not an error in the rows. The measure is reported as it was defined before the run. The alternative number is given here. |
| 2 | `sweep.py`, completeness check | A rerun is accepted as the latest result without checking that the run it replaces ended in an infrastructure error or a spend stop. | Checked: all 6 reruns on file replace a run that ended in `model_error` or `cost_cap`. |
| 3 | `sweep.py`, build check | The check does not look at which teacher built a skill or which task it learned from. | Checked: every build on file used the same teacher and learned from version 1 only. |
| 4 | `build_coach_checked.py`, `build_skills.py`, pending builds | A build interrupted during validation keeps its earlier spend only in a log file, and a restart gives it a fresh set of attempts. | No build on file was interrupted this way. The code path was added on Nov 24, after the run. |
| 5 | `build_coach_checked.py`, stale skip check | With `--source-run`, an older run can override a newer local one. | Stage 1 did not use `--source-run`. |
| 6 | `ledger_vs_rows.py` | The cost audit can skip older ledger rows after a change in how the ledger is written. | The audit matched all 993 runs on the stage 1 files. |
| 7 | `build_coach_checked.py`, ledger rows | New note-build ledger rows lack the scenario id the audit needs. | Affects future builds only. |
| 8 | `ledger_vs_rows.py` | Control runs that share a boundary second are compared as group sums, so opposite errors inside a group would not show. | `PROTOCOL.md` now says this in those words. 121 of the 131 control runs are checked as sums. |

To do before any new note or function build is run with this code: items 4, 5 and 7.

## Fixed Nov 25, 2026, before stage 2 part A builds any note

- **Item 4:** fixed in `build_coach_checked.py` (an interrupted build resumes with its attempts and spend). Not changed
  in `build_skills.py`, because no function is built again; it stays open there.
- **Item 5:** fixed (`load_records`: the run's own rows win; trajectories are read from the folder of the row used).
- **Item 7:** fixed (`ledger_note`: every request of a note build carries the student and the scenario).

Tests: `tests/test_note_build_fixes.py`. Items 1, 2, 3, 6 and 8 are unchanged.
