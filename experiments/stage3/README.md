# Stage 3: how to run it (for Bill)

I set this up so you can run it on your own machine with one command. The design and the rules are in `PROTOCOL.md`
next to this file. Please read that first, because nothing in it should change once you start.

What it does: your OpenAI teacher (GPT-6.2 Sol) runs the 23 part A scenarios alone, writes the functions and the
notes, and our four open-source students run again with that help. Their solo runs are reused from stage 1 and part A,
so they don't run again. The cost is about $35 to $60 on OpenAI and about $15 on Nebius by my estimate, with hard stops
at $90 and $25. Expect a few hours unattended.

## Once, before the first run

1. **Setup.** Follow "Experiments on AppWorld" in the main `README.md`: the `.venv` for the app, `.venv-appworld` for
   AppWorld, `appworld download data --root .`, then `.venv-appworld/bin/python experiments/appworld_env_check.py`. It
   must end with `ENV GATE PASSED`.
2. **Keys.** Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `NEBIUS_API_KEY`. The students have to run
   on Nebius because that's where their solo runs were made. A different provider can serve the same model
   differently.
3. **The students' solo runs.** I'll send you a zip separately. Unzip it at the repository root and it fills
   `results/pilot/stage1/raw_large/` and `results/pilot/stage2a/raw_large/`. Those folders are gitignored, and they
   have to stay out of git because AppWorld's license doesn't let us republish its tasks.
4. **The teacher's model id and prices.** In `experiments/stage3/config.json` the teacher is `gpt-6.2-sol` at $2 / $10
   per million input / output tokens, $0.10 cached. I took those from third-party price lists. Check them on OpenAI's
   pricing page, fix them if they're wrong, then set `teacher_prices_checked_on` to the date you checked.

## Run

```
.venv/bin/python experiments/stage3/stage3.py preflight --ping
bash experiments/stage3/run_stage3.sh
```

(On Windows the Python is `.venv/Scripts/python.exe`.) The preflight sends one tiny request to the teacher and to each
student, shows exactly which settings each one receives, and checks everything above. The teacher's temperature is
already null in the config: GPT-6.2 Sol always reasons, so OpenAI takes no temperature for it. That and its larger
output limit are the two deviations written in the protocol. Don't change anything else.

After the teacher's first 3 runs, the runner checks that the whole stage fits under the OpenAI stop and that the
output limit isn't cutting the teacher off. If either fails, it stops before spending more. Tell me if that happens.

The runner is resumable. If it stops for any reason (your laptop sleeps, a provider has a bad hour), run the same
command again and it continues where it stopped. Don't edit the config or the scripts in the middle. If something
looks wrong, stop and message me.

## When it finishes

It writes `results/pilot/stage3/analysis_stage3.json` without printing the result, and adds a row to `LOG.md` with your
name. Then:

```
.venv/bin/python experiments/stage3/stage3.py privacy     # must print nothing
git checkout -b bill/stage3-results
git add results/pilot/stage3 results/spend_ledger.jsonl LOG.md experiments/stage3/config.json
git commit -m "Stage 3 run: OpenAI teacher, same students"
git push -u origin bill/stage3-results
```

`raw_large` stays on your machine. Then tell me, and we open the result together.
