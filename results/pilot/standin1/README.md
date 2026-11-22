# STAND-IN MODELS. Not a finding.

> **Update, Nov 20, 2026, 18:04 ET: Alfredo confirmed these two models for the pilot** ("Keep these two").
> The run below therefore stands as the pilot's run, and its numbers may be used with their limits stated:
> one run per task, 3 scenarios, the signal readings are proposals the team has not agreed on, and no
> independent reviewer has re-derived the numbers. Bill and Harsh have not been asked. The records keep the
> label `STAND-IN MODELS` because records are never rewritten; this note is what changes its meaning.
> The text below is as written before the run.

This folder holds a run of the pilot on **stand-in models**:

- small model: `Qwen/Qwen3-30B-A3B-Instruct-2507` (Nebius)
- cloud model: `zai-org/GLM-5.3-Flash` (Nebius)

**Neither model was chosen by Alfredo or Bill.** The plan (`CLAUDE.md`) says "an open ~8B model" for the small
model and names no cloud model. The run was started on Nov 20, 2026 as a harness check, on prepaid credit with a hard cap of $5 in code,
before the team had picked models.

**What it is for:** shaking out the harness, and measuring cost and time per task.

**What it is not for:** no number from this folder goes into the report, the presentation, or anything shown
to the team as a finding until Alfredo confirms the models. If he picks other models, the pilot is run again
under a new run name and this folder stays as a harness check.

Every record in `runs.jsonl` and `teach.jsonl` carries `"label": "STAND-IN MODELS"`.
