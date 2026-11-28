# Stage 3: an OpenAI teacher, the same students

**Designed by Alfredo Frontera, Fri Nov 27, 2026, before any stage 3 run. To be run by Bill (Ton Hoang Nguyen) on
his own OpenAI and Nebius accounts.** Stage 1, part A, part B and their protocols are not changed by anything here. Their rows
are read, never written.

## Design decisions (Alfredo, Nov 27)

- **The teacher changes, nothing else does.** Same 23 scenarios as part A, same students, same settings (AppWorld's
  minimal prompt, temperature 0, seed 123, at most 50 steps, the same output limits), same arms, same rules for counting.
- **An OpenAI frontier model is the teacher:** GPT-6.2 Sol, Bill's pick. Frontier models are the expensive teachers
  people actually pay to rent, so this tests whether what we found with a cheap teacher (GLM-5.3-Flash, about 2 cents a
  task) still holds when renting costs much more.
- **The students' solo runs are reused, not run again.** A solo run does not depend on the teacher, so every failure
  the help is scored on is the exact failure from stage 1 and part A. Everything that depends on the teacher is new:
  its own runs on the 69 tasks, the functions, the notes, and the students' runs with that help.
- **The open-source students run on Nebius, the provider of the solo runs,** so a different serving stack cannot
  change their behavior.
- **OpenAI teacher with the open-source students comes first.** An all-OpenAI version (OpenAI students, screened on 12
  tasks first) comes after, with its own protocol.

## What runs (`experiments/stage3/run_stage3.sh`)

- **Scenarios:** the 23 of part A (`experiments/stage2/scenarios_part_a.json`): version 1 is where help is built,
  versions 2 and 3 are the test tasks.
- **Teacher:** GPT-6.2 Sol through OpenAI's API. It runs all 69 tasks alone (renting), then writes one function per
  scenario it passed on version 1, checked on version 1 with up to 2 repairs, exactly as in stage 1.
- **Students:** gpt-oss-120b, Gemma-3-27B and MiniMax-M3.1-Flash (the weak tier of stage 1), and Nemotron-3-Super-120B
  (middle strength, from part A). Qwen3-235B, part A's other middle student, is no longer offered by Nebius (a request
  was refused on Nov 27), so it cannot take part.
- **Per student:** a checked note built from version 1 where the student failed it alone and the teacher passed it,
  kept only if the student then passes version 1 with it (up to 2 revisions), tested on versions 2 and 3; the
  teacher's function on versions 2 and 3; the generic note on the units below. Solo runs come from stage 1 (weak) and
  part A (Nemotron).
- **Reruns:** a run is redone only if it ended in an infrastructure error or at a spending stop, at most twice. The
  latest run counts.
- **Money, at list prices:** hard stops of $90 on OpenAI (the teacher) and $25 more on Nebius (the students). New
  requests stop $5 (OpenAI) and $0.50 (Nebius) before each stop, so that four jobs with a request in flight cannot pass
  it. Estimate about $35 to $60 on OpenAI and $15 on Nebius, from our own token counts; a model that reasons on every
  step may use more. OpenAI bills repeated prompt text at a lower rate, so its real bill should be lower than the list
  price.
- **A stop after the teacher's first 3 runs.** They are fixed now: the first 3 tasks in sorted order (042a9fc_1 to _3).
  Only a run with a result counts; an infrastructure error is redone first. A passed check is kept, so a restart does not
  repeat it, and a build stopped by a spending limit stays pending and resumes. If the stage then projects past what
  is left under the OpenAI stop, or more than 20% of the teacher's replies were cut by the output limit, the run stops
  before spending more. The projection is 182 teacher solo runs' worth of spend: 69 solo runs, 2.6 per function build
  and 0.78 per note build, the ratios of GLM-5.3-Flash's own costs in stage 1. Those first runs count as solo runs.

## Two deviations, known before any run

- **The teacher runs at OpenAI's default temperature, not 0.** GPT-6.2 Sol always reasons, and OpenAI accepts no
  sampling settings for a reasoning model. The model library drops temperature for it without an error. A request to a
  stand-in server on Nov 27 carried no temperature for GPT-6.2 Sol and temperature 0 for every student. So the
  config sets the teacher's temperature to null, its rows record null, and the preflight refuses any model whose
  configured temperature would not be sent. The students are unchanged: temperature 0, seed 123.
- **The teacher's output limit is 16,000 tokens per reply, not 4,000.** Its reasoning tokens count against the limit,
  and the rule since the pilots is that the limit must not cut off a model that thinks before it answers. Reasoning
  effort is OpenAI's default.

Nothing else may change.

## Measures, fixed now

Same unit as part A: a test task the student failed alone, in a scenario where it also failed version 1 alone and the
teacher passed version 1. Scenarios are the clusters. Bootstrap over the 23 scenarios, 10,000 resamples, seed 123,
percentile 2.5 to 97.5.

**Primary, the cost question.** The rows are stage 1's break-even with failures priced: one per student and
note-eligible scenario where both a note and a function build were attempted and the student has at least one failed
test task that the teacher passed. Renting is only defined where renting works, so tasks the teacher failed are left
out. For each row, the cost of serving 10 uses of the task: build cost (all attempts, failed builds included) plus 10
times the cost of one use. One use is a run with the skill plus, when the skill does not fix the task, renting the
teacher for it. A failed build rents every use. A function's build is charged in full to each student. The primary
number is the share of rows, all four students pooled, where the note's 10-use cost is below the function's.
- **NOTE IS THE BETTER BUY** if the whole interval is above 0.5;
- **FUNCTION IS THE BETTER BUY** if the whole interval is below 0.5;
- **UNDECIDED** otherwise.
Costs are at list prices, the same basis as every earlier stage. The same measure at OpenAI's billed prices (cached
input cheaper) is reported next to it.

**Secondary, the accuracy replication.** Part A's contrast and label with Nemotron as the middle group: D = note fix
rate of Nemotron minus that of the weak students, and D_net net of the generic note. CATCHES UP if D's interval is
above 0, quoted as the thesis only if D_net's is too; DOES NOT if D is below 0.15 and its interval holds 0; UNDECIDED
otherwise. With one middle student this interval will be wide.

**Also reported:** the same measures by tier; the share of renting cost each form saves at 1, 3, 10 and 30 uses;
whether each form beats renting at all; per student fix rates and harm; the teacher's own pass rate and cost per task;
function and note build outcomes; cost and steps per arm.

**Reference, computed before any stage 3 run** (`experiments/stage3/reference_before_run.json`): the same measures on
the GLM-5.3-Flash runs of the same four students on the same 23 scenarios. It has 61 rows: 66 student-scenarios are
note-eligible, and in 5 of them the teacher failed every test task the student failed. The weak students' units are 108 (note 27,
function 87, generic note 12) and Nemotron's 14 (note 10, function 12, generic note 3), the numbers of part A. The note
is cheaper than the function over 10 uses in 9.8% of 61 student-scenarios (interval 3.4% to 17.2%): FUNCTION IS THE
BETTER BUY. Over 10 uses a function saves 21% of what renting every use would cost, and a note costs about twice as
much as renting.

Nothing is computed until every run is on file and none ends in an infrastructure error or a spending stop. The runner
then writes the result to `results/pilot/stage3/analysis_stage3.json` without printing it.

## Predictions, written now

- GPT-6.2 Sol passes 60 to 69 of the 69 tasks alone and builds a function in 20 to 23 scenarios.
- **Primary: FUNCTION IS THE BETTER BUY again, with the note cheaper in under 20% of student-scenarios** (chance about
  75%). The reason: when renting is expensive, every failure the skill does not fix costs a lot, and the function
  fixes more failures than the note. UNDECIDED about 20%, NOTE IS THE BETTER BUY about 5%.
- Both forms save a much larger share of the renting cost than with GLM-5.3-Flash: the function more than half of it
  over 10 uses, and the note at least breaks even against renting in most scenarios where it was built.
- Accuracy: CATCHES UP again (chance about 55%). A stronger teacher may write better notes for the weak students too,
  which would shrink D.

## What each result means

- **FUNCTION IS THE BETTER BUY with an expensive teacher too:** "compile first" holds whether renting costs 2 cents or
  much more per task. A note is the fallback when a function cannot be built.
- **NOTE IS THE BETTER BUY:** the teacher's price changes the best buy, which is the full thesis.
- **UNDECIDED:** report the direction only.
- **CATCHES UP again:** the note's dependence on student strength holds with a second teacher from another model family.
  DOES NOT: the part A result may belong to GLM-5.3-Flash.

## Limits

One run per task and arm. One middle student. Two teacher families in all. The solo runs are reused from a different
day; temperature 0 makes that close to a rerun, not the same as one.
