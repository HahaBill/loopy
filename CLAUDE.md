# Loopy: team workspace (COMS E6998-007, Fall 2026)

Team: Ton Hoang Nguyen (Bill), Alfredo F. Frontera Del Valle, Harsh Kumar. Equal contribution.
Final proposal (Oct 26): `docs/proposal-2026-10-26.pdf`. The final project must stay relevant to it.
Literature review and verified references: `docs/lit/novelty-lit-sprint.md`, `docs/lit/refs.json`.

## The question
When a small local model fails a task that keeps coming back, Loopy can **rent** (cloud model every time),
**coach** (cloud model writes a short guide once, from the step where the small model went wrong), or
**compile** (save the cloud model's working code as a function the small model fills in).
- RQ1: how many repeats before coach or compile is cheaper than renting (dollars, cloud calls)?
- RQ2: which tasks and failures can coach or compile fix, and which can't they?
- RQ3: can a per-task picker beat every fixed option?
- Closest prior work: PACE (arXiv 2610.02932), rent vs compile as rent-or-buy. No coach, no local vs cloud, no
  self-forecast. Cite it; never claim that piece as new.
- Paper angle (hypothesis, not a claim): the agent's own "will I fail" forecast drives a three-way choice, with a
  bounded loss if the forecast is wrong.

## Step 1: the pilot (do this first, before building anything else)
3 AppWorld scenarios x 3 versions each (pick across difficulty levels, from the dev split).
1. Small model alone on all 9 tasks. Before each run, ask it "will you fail? (probability)" and log it.
2. Cloud model on the tasks the small model failed.
3. Coach and compile built from version 1, tested on versions 2 and 3.
4. Log per run: task id, version, condition, model ids, success (AppWorld checker), tokens in/out, dollars,
   cloud calls, wall time, forecast, failure type (bug-level = run breaks; quality-level = finishes wrong).
Read it: 3-4 of {small model fails often, coach/compile fixes new versions, no option always wins, forecast
tracks outcomes} = scale to ~30 scenarios. 2 = class project, swap forecast source. 0-1 = change model or tasks.

## Rules
- Never invent a number. Every result comes from a file in `results/` made by a committed script with model ids and
  seeds recorded. Keep a `LOG.md` (append-only): date, time ET, who, command, result file, why.
- Tune prompts on AppWorld's dev split only. Never look at test tasks while tuning.
- Cite only references in `docs/lit/refs.json` or new ones checked with the lit-sprint skill (`lit.py verify`).
- No keys in the repo: use `.env` (gitignored). Budget about $150 total; check spend after the pilot.
- Python backend (AppWorld needs Python 3.11+). One branch per person, small PRs into `main`.
- Commits are authored by the human. No AI co-author trailers.
- Plain English, short sentences, lead with the result.
