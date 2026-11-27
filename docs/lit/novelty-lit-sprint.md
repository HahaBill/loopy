---
type: output
project: coms-e6998-final-project
created: 2026-10-26
tags: [loopy, lit-sprint, novelty, e6998]
---

# Loopy novelty lit sprint (Oct 26, 2026)

Source project: [[projects/coms-e6998-final-project]]. 14 papers read in full (every line, every figure), 26 citations verified OK with `lit.py verify-file` (plus 1 DOI verified separately). PDFs for NotebookLM: `raw/loopy-notebooklm-stack/` (23 files, numbered in importance order).

## Verdict

**The plain "rent vs compile, per task, as an online rent-or-buy problem" framing is already taken.** PACE (arXiv 2610.02932, Oct 2026) treats compiling a computer-use agent's procedure into a program as rent-or-buy with a compile that can fail, unknown future reuse and a drift hazard. It cites Karlin and Purohit, guarantees cost at most (1+ε) of always-agent, and reports 17.3% savings. Loopy cannot claim the ski-rental framing as its contribution.

**What stays open in what we searched (arXiv 6-month pass plus OpenAlex and Semantic Scholar all-years, 18 phrasings, citation trails from 3 seeds) is narrower and sharper:**
1. A **three-way** choice that includes a cheap text **coach** option, not just rent vs compile.
2. A discount that is **uncertain in sign**: a bought skill can help, do nothing, or hurt. PFSUM assumes β is known and fixed; PACE models only "compile fails" plus drift, never "skill succeeds but hurts".
3. The **agent's own forecast used as the advice** in a learning-augmented rule with consistency and robustness. No paper we read does this. PACE uses arrival counts and a Laplace success rate. The self-prediction papers (2608.14927, StepGate) never amortize anything.
4. A **teachability test before paying**: predict from the step where the small model diverged whether a coach note will work (procedural failure) or whether only rent or compile will (capability failure). No paper we read predicts this per task.

Confidence: medium-high for 1 to 3, medium for 4 (token-level teachability exists for weight distillation, 2605.26844, so the idea has a neighbor). Not searched: paywalled venues (ACM SIGMETRICS/EC full texts), patents, non-English work, industry blogs. One ACM paper found only by abstract ("Confidence-Aware Learning-Augmented Algorithms for the Bahncard Problem", DOI 10.1145/3848038.3848063) adapts trust in predictions but, from its abstract, uses external predictions with a known discount.

## Closest prior work

| Paper | What it does | What it does not do (vs Loopy) | Pointer |
|---|---|---|---|
| **PACE**, When to Compile a Computer-Use Agent? (2610.02932) | Online rent-or-buy between agent and compiled program per task family. Savings test Ĥ·s > B̂, failed-compile cost modeled (6.57x more tokens than successes), drift hazard h, (1+ε) budget guarantee. 7 families, 3 models, same model serves and compiles. | No coach option. No local vs cloud. No self-prediction (advice = arrival counts + Laplace p̂). No teachability explanation (OsmAnd never compiles, unexplained). No consistency/robustness analysis. Savings partly synthetic (measured costs shuffled onto log families). | Sec 2, Eq 5, Thm 4.1, Tables 1, 3, 4, 7 |
| **LearnSched**, Serve Now or Improve Later? (2610.06212) | Build-a-reusable-artifact (tool, guidance, LoRA) as an investment; break-even rule Eq 3-4; uses-to-break-even 2-3 under token pricing vs 5-80 under GPU pricing. | Timing, not choice among artifacts. No small vs large model. Artifact value never negative. Only 43-51% of times guidance was ready did a request use it. | Eq 3-4, Fig 12a, Fig 13 |
| **StepGate**, Do I Need the Cloud? (2610.07816) | Calibrated per-step "will my local action fail" gate; 69.0% vs 48.0% local-only at 30% cloud. | Rent only, no repeats so nothing amortized. Gain over random escalation not significant (p=0.108). Fig 9: fixability depends on failure type. | Table 3, Fig 9 |
| **Failure risk vs protocol value** (2608.14927) | Self-confidence predicts own failure (AUROC 0.885 post-answer, 0.859 pre-answer) but not which remedy pays off (AUPRC 0.10-0.17). | One-shot math, no agents, no lasting interventions. | Table 2, Fig S2b |
| **ASSAY**, Not All Skills Help (2606.15390) | Per-task skill effects flip sign; per-task picking lifts DeepSeek-V3 on AppWorld challenge 47.0 to 69.3. GPT-5.1's own uncurated library hurt (52.5 to 49.9). | Same model writes and reads. No cost (180 measuring runs uncosted). No rent or compile. Power 38.5% per cell. | Table 1, 3, 7, 9, Fig 4 |

Also close: RSI-Router (2609.34712, joint routing + skills, build cost hidden), AgentBrew (2607.16851, teacher notes for weak student, $116 brew cost, no break-even computed), MERA (2608.10333, adaptation break-even in days, no per-task choice).

## Coverage grid

Components: **C1** three-way rent/coach/compile choice · **C2** break-even over repeats counting teaching cost · **C3** teachability split (procedural vs capability) · **C4** online per-task picker · **C5** self-prediction as advice with guarantees · **C6** uncertain discount (harmful skills, staleness).

| Paper | C1 | C2 | C3 | C4 | C5 | C6 |
|---|---|---|---|---|---|---|
| PACE 2610.02932 | ~ (rent/compile) | ✓ | ✗ | ✓ (binary, per family) | ✗ | ~ (fail + drift, not harm) |
| LearnSched 2610.06212 | ~ (timing) | ✓ | ✗ | ✗ | ✗ | ~ (future work) |
| StepGate 2610.07816 | ✗ (rent per step) | ✗ | ~ (Fig 9) | ~ (per step) | ~ (calibrated, no guarantee) | ✗ |
| Failure risk 2608.14927 | ~ (remedy choice) | ✗ | ✗ | ~ | ~ (advice quality measured) | ✗ |
| ASSAY 2606.15390 | ✗ (coach only) | ✗ | ~ | ✓ (picks skills) | ✗ (rejects LLM judging) | ✓ (harm measured) |
| Model-gen skills 2605.23899 | ✗ | ✗ | ~ (App D) | ✗ | ✗ (judge 46%) | ✓ (25% cells negative) |
| AgentBrew 2607.16851 | ✗ (coach only) | ~ ($116, no break-even) | ✗ | ✗ | ✗ | ✗ |
| RSI-Router 2609.34712 | ~ (rent+coach) | ✗ (build cost hidden) | ✗ | ~ (per subtask type, offline) | ✗ (self-judging < random) | ~ (skills hurt on SWE/TB) |
| TACIT-Switch 2608.27911 | ✗ (rent) | ✗ | ~ (rescue window) | ~ (per episode) | ~ (risk signals) | ✗ |
| MERA 2608.10333 | ~ (rent vs fine-tune) | ~ (days, fixed haircut) | ✗ | ~ (weak router) | ✗ | ✗ |
| PFSUM 2410.15257 | ✗ (one card) | ✓ (γ = C/(1-β)) | ✗ | ✓ (threshold) | ~ (external forecast, guarantees) | ✗ (β known) |
| Token teachability 2605.26844 | ✗ | ✗ | ✓ (token level, weights) | ✗ | ~ (student's own dist.) | ✗ |
| Repo2Skill-Evo 2608.21964 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ (staleness) |
| FlashScript 2610.33876 | ~ (skill vs program) | ✗ | ~ (anecdotal) | ✗ | ✗ | ~ (skill inherits bad shortcut) |

No column has ✓ on C1 and C5 together, and nobody covers C3 at the task level for in-context teaching. That is the gap.

## Cross-paper map

### Agreements
- **Compiled programs are near-free per run once they exist.** PACE saving share 0.936 to 0.999; FlashScript 70x fewer input tokens and 100% vs 97% (skill) vs 89% (agent). The cost is all up front and in failures.
- **Failed teaching is the expensive tail.** PACE: failed compiles median 1701K vs 259K tokens; removing the failed-vs-success cost distinction adds 23.3% cost. LearnSched: 9 to 13 builds never paid back.
- **Weaker readers gain more from good skills, but not reliably.** ASSAY (DeepSeek-V3 +22.3 vs GPT-5.4 +4.3) vs Huang et al. (Qwen3.5-9B averages -1.69 on ALFWorld).

### Contradictions (and what resolves them)
1. **Do self-written skills help?** SkillsBench says little or no benefit. ASSAY says an uncurated self-written library hurt GPT-5.1 (52.5 to 49.9) but per-task curated helps a lot. Huang et al. say self-written skills are often the weakest in their row (GPT-5.4 +1.49 vs others' +7.46 on ALFWorld) while strong-model-sourced skills help all six readers. RSI-Router: removing skills raised SWE-bench and Terminal-Bench by 9.7 and 10.5 points. **Likely resolution:** the sign depends on (a) writer different from reader, (b) whether the source run succeeded (failure-only pools are worst, Huang Fig 2), and (c) the task, not the average. Loopy's coach is exactly the case the papers disagree on: a cloud writer, a small reader, built from a failure step. Loopy can test the resolution directly with per-task signed effects.
2. **Is self-prediction useful advice?** 2608.14927: yes for "will I fail" (AUROC up to 0.885), no for "which fix". RSI-Router: a 9B model judging step difficulty is worse than random on all 5 benchmarks. StepGate: a trained gate on the small model's own signals reaches AUROC 0.73 to 0.90, raw token uncertainty alone only 0.565. **Resolution:** verbalized or raw signals predict failure demand; they do not pick the remedy. So the advice should be two channels: self-forecast for "will this task keep failing" and observed outcomes on earlier repeats for "which option works". This is also why a robust learning-augmented rule is needed, not trust in the model.
3. **What is the break-even?** PACE 1.4 to 15.5 uses; LearnSched 2-3 uses (tokens) vs 5-80 (GPU time); AgentBrew about 5,800 tasks to recover $116 against the teacher (our arithmetic); MERA 8.7 to 32 days. The unit flips the ranking (LearnSched Fig 13). Loopy must report both dollars and wall-clock, because local inference is near-free in dollars but not in time.

### Shared assumptions nobody tests
- The discount, once bought, is non-negative and fixed (PFSUM β known; PACE program either works or drifts; MERA, LearnSched constant value).
- One model writes and reads (ASSAY, PACE, LearnSched), or teacher is always called on every failure (AgentBrew, no gate).
- Tasks do not repeat with variation (StepGate, TACIT, 2608.14927, RSI-Router).
- Drift is detected by an oracle (PACE App B.2) or needs a changelog (Repo2Skill-Evo).

### Mechanism chains (candidate contributions)
- **A. PACE Eq 5 + 2608.14927 pre-answer probe (AUROC 0.859) + PFSUM Thm 4.11 → untested:** replace PACE's Laplace compile-success estimate with the agent's own pre-attempt forecast and wrap it in a PFSUM-style rule that is near-optimal when the forecast is good and bounded when it is bad.
- **B. Token teachability (teacher's correction lands in the student's top-k, 2605.26844 Sec 3) + TACIT recoverable divergence window + StepGate Fig 9 (value errors ~100% fixable, "should abstain" 20-40%) → untested:** a black-box teachability probe at the divergence step. If the cloud's action is among the small model's top-k sampled actions, a coach note should work (procedural); if not, only rent or compile (capability). The token paper itself never tests in-context teaching.
- **C. PFSUM (β known) + ASSAY Fig 4 and Huang Table 1 (effects flip sign) + FlashScript (skill inherits a bad shortcut, 0.67 vs 0.87) → untested:** a Bahncard problem where β is a random, task-dependent variable that can exceed 1, learned from repeats.
- **D. Repo2Skill-Evo (frontier agents fix only 30-70% of stale lines) + PACE drift hazard h + LearnSched future work → untested:** card validity T is random, and coach notes and compiled code age differently. AppWorld APIs never change, so this needs injected API changes (Repo2Skill's 5 change types are a ready list).
- **E. Huang Fig 2 (failure-only pools worst) + AgentBrew Ralph loop (keep a note only if the student's re-run passes) → design implication:** Loopy's coach should be built from the contrast between the small model's failed step and the cloud's passing run, and validated by a re-run before it counts as bought.

### Metric drift
- "Skill helps" = success with minus without, per task (ASSAY), per domain cell (Huang), or ablation of the whole library (RSI-Router). Loopy should use ASSAY's per-task signed definition.
- "Cost" = weighted tokens (PACE), parameter-count units (TACIT), dollars at 1:30 (RSI-Router), GPU-seconds (LearnSched). Loopy: dollars for cloud calls plus measured wall-clock for local.
- "Teachability" = token-level D×C (2605.26844) vs Loopy's task-level "a coach note fixes the next variant".

## Gap and falsifier

**Gap:** an online per-task rule choosing among rent, coach and compile, where (i) the value of coach or compile is uncertain and can be negative, (ii) the advice is the small agent's own forecast plus a divergence-step teachability probe, and (iii) the rule has a robustness guarantee against bad advice. Measured on repeated, varied AppWorld tasks with dollars per solved task.

**Falsifiers (what would show it is not new or does not work):**
- A paper we missed that adds a coach/text-skill arm to PACE-style rent-or-buy with predicted skill value. Check: PACE's citing papers in a month, and the LATA 2026 special issue.
- On AppWorld, the small model's self-forecast has AUROC under about 0.65 for "will keep failing on the next variant". Then the advice is noise and the rule collapses to PACE.
- The best fixed arm (likely always-compile on API tasks) is within the confidence interval of the picker. Then RQ3 is null; still publishable as a measured break-even, but not as a method.

## Top 3 candidate paper directions (ranked)

### 1. "Teach, compile or rent: ski rental where the agent predicts its own discount"
- **Claim:** A three-option learning-augmented rule that uses the small agent's own forecasts reaches a lower cost per solved task than any fixed option and than PACE's binary rule, while staying within (1+ε) of always-rent when the forecasts are wrong.
- **Experiment:** On about 30 AppWorld scenarios × 3 variants, run every arm once per variant: small alone, rent, coach (cloud note from the divergence step, validated by one re-run), compile. That gives a counterfactual cost-and-success table. Then replay thousands of arrival sequences (different repeat counts and orders, as PACE does with logs) through: each fixed arm, PACE's rule, an oracle, and our rule with the real self-forecasts and with noise injected into them. Report regret vs oracle and the robustness curve as forecast quality degrades.
- **What kills it:** self-forecast AUROC under ~0.65 on AppWorld, or the picker not beating the best fixed arm outside the bootstrap CI.
- **Fit:** strong. No GPU beyond the local small model. The replay is free once the table exists, so the API spend is one pass per arm per variant (fits ~$150 if the cloud model is a mid-tier one for rent/coach/compile and the subset is held at ~30 scenarios). Directly answers RQ1 and RQ3.

### 2. "Is this failure teachable? A divergence-step probe"
- **Claim:** Whether the cloud model's correct action at the divergence step is among the small model's top-k sampled actions predicts whether a coach note will fix the next variant, better than self-confidence or task difficulty.
- **Experiment:** For each failed task, locate the divergence step (first step where the small model's action differs from the cloud's passing trace), sample k=8 small-model actions there, compute the hit rate, then measure coach success on variants 2 and 3. AUROC vs baselines (verbalized confidence, AppWorld difficulty level, trace length). Label failures procedural vs capability by hand on a subset to check the probe agrees.
- **What kills it:** probe AUROC not above the difficulty-level baseline, or coach success uncorrelated with anything.
- **Fit:** strong, and it is RQ2 made measurable. Sampling is local and free. Feeds direction 1 as a feature, so do both: 2 is the mechanism, 1 is the system.

### 3. "Skills that expire: harmful and stale discounts"
- **Claim:** Compiled workflows have higher mean savings but a fat failure tail under app changes, while coach notes degrade gracefully, so the best choice flips with change rate.
- **Experiment:** Mutate a few AppWorld APIs (rename, signature change, default change, following Repo2Skill-Evo's change types) between variants and measure per-arm success and repair cost. Also report the distribution of per-task signed coach effects (how often coach hurts).
- **What kills it:** compiled code survives the mutations, or coach never hurts.
- **Fit:** medium. Needs engineering on AppWorld's API layer; good as a section or ablation of direction 1, weak as a standalone class project.

## Reading notes (summaries; full notes in papers/)

Each full note ends with its coverage line. All 14 are `checked: full-text`.

- **PACE** [[papers/pace-when-to-compile-computer-use-agent]]. Rent-or-buy compile decision with failed-compile cost and drift; (1+ε) guarantee; 17.3% savings; 3 of 12 log conditions cost more than ReAct; budget is insurance not savings. `read: lines 1-5144 of 5144 · figures 3/3 · tables 19/19 · appendix yes`
- **FlashScript** [[papers/flashscript-neuro-symbolic-programs]]. Compiled programs 100% vs skill 97% on WorkBench, 70x fewer tokens; skill copies a bad shortcut (0.67 vs 0.87); authoring cost not reported. `read: lines 1-886 of 886 · figures 2/2 · tables 2/2 · appendix none exists`
- **LearnSched** [[papers/learnsched-serve-now-or-improve-later]]. Artifact building as investment; +1.10% value; break-even flips with pricing unit. `read: lines 1-1546 of 1546 · figures 17/17 · tables 4/4 · appendix yes`
- **StepGate** [[papers/stepgate-step-level-slm-handoff]]. Calibrated self-failure gate, 69.0% at 30% cloud; fixability by failure type (Fig 9). `read: lines 1-1077 of 1077 · figures 9/9 · tables 9/9 · appendix yes`
- **Failure risk vs protocol value** [[papers/llms-predict-failure-risk-not-protocol-value]]. Self-forecast AUROC 0.58 to 0.885; cannot pick the remedy. `read: lines 1-3175 of 3175 · figures 6/6 · tables 28/28 · appendix yes`
- **ASSAY** [[papers/not-all-skills-help-assay]]. Per-task skill effects flip sign; per-task picking +22.3 on AppWorld challenge for DeepSeek-V3; templates ~40% of gain. `read: lines 1-1685 of 1685 · figures 5/5 · tables 12/12 · appendix yes`
- **Model-generated skills** [[papers/model-generated-agent-skills-lifecycle]]. 25% of writer × reader cells negative; strong-source skills help all readers; LLM judge picks the better skill 46.4%. `read: lines 1-1695 of 1695 · figures 5/5 · tables 15/15 · appendix yes`
- **MERA** [[papers/mera-model-evolution-routing-skill-adaptation]]. Small model fine-tuned from teacher demos + verifier fallback: 88.3% at 60.8% cost; break-even 8.7 to 32 days. `read: lines 1-798 of 798 · figures 2/2 · tables 4/4 · appendix yes`
- **Token teachability** [[papers/token-teachability-on-policy-distillation]]. Learnable disagreement D×C predicts gain 2x incompatible; effects small; raw KL nearly as good. `read: lines 1-2352 of 2352 · figures 5/5 · tables 13/13 · appendix yes`
- **Repo2Skill-Evo** [[papers/repo2skill-evo-skills-go-stale]]. Frontier agents remove only 29.9 to 69.7% of stale skill content; prevalence unknown by design. `read: lines 1-1815 of 1815 · figures 4/4 · tables 13/13 · appendix yes`
- **TACIT-Switch** [[papers/tacit-switch-cost-aware-escalation]]. One-way learned handoff; gains mostly from later handoff; recoverable divergence window labels. `read: lines 1-1601 of 1601 · figures 6/6 · tables 3/3 · appendix yes`
- **RSI-Router** [[papers/rsi-router]]. Offline joint routing + skills, ~50% cost cut excluding build cost; skills hurt on SWE/Terminal; self-judged difficulty worse than random. `read: lines 1-1950 of 1950 · figures 11/11 · tables 2/2 · appendix yes`
- **AgentBrew** [[papers/agentbrew]]. Teacher notes validated by student re-run; AppWorld TGC 22.00 to 31.55 (normal); Reflexion k=3 beats it; $116 brew cost. `read: lines 1-1147 of 1147 · figures 5/5 · tables 4/4 · appendix yes`
- **PFSUM** [[papers/learning-augmented-bahncard-pfsum]]. 2/(1+β)-consistent, 1/β-robust; β known and fixed; synthetic experiments only. `read: lines 1-2686 of 2686 · figures 30/30 · tables 0/0 · appendix yes`

Not read in full (search summary or abstract only): PreAct 2606.17929 (compiles a successful run into a state machine and replays it), TraceCompiler 2608.02680, Ski Rental with Uniform Stochastic Signals 2610.26214, Confidence-Aware Bahncard (DOI 10.1145/3848038.3848063). Earlier vault notes for AWM, Agentic Plan Caching, SkillsBench, FrugalGPT, RouteLLM are abstract or search-summary level; ACE and Better Harnesses were read in full on Oct 14.

## NotebookLM paper stack (in importance order)

PDFs are saved as `raw/loopy-notebooklm-stack/NN_<id>.pdf` with the same numbers.

| # | Paper | Year | Abstract | PDF |
|---|---|---|---|---|
| 1 | When to Compile a Computer-Use Agent? Measuring Payback and Making Compilation Decisions for Token Efficiency (Ming et al.) | 2026 | https://arxiv.org/abs/2610.02932 | https://arxiv.org/pdf/2610.02932 |
| 2 | Learning-Augmented Algorithms for the Bahncard Problem (Zhao et al.) | 2024 | https://arxiv.org/abs/2410.15257 | https://arxiv.org/pdf/2410.15257 |
| 3 | Do I Need the Cloud? Uncertainty-Aware Step-Level Handoff for Small Language Model Agents (Younesi) | 2026 | https://arxiv.org/abs/2610.07816 | https://arxiv.org/pdf/2610.07816 |
| 4 | LLMs Can Predict Failure Risk, But Struggle to Predict Which Collaboration Protocol Pays Off (Yang et al.) | 2026 | https://arxiv.org/abs/2608.14927 | https://arxiv.org/pdf/2608.14927 |
| 5 | Not All Skills Help: Measuring and Repairing Agent Knowledge (Wang et al.) | 2026 | https://arxiv.org/abs/2606.15390 | https://arxiv.org/pdf/2606.15390 |
| 6 | From Raw Experience to Skill Consumption: A Systematic Study of Model-Generated Agent Skills (Huang et al.) | 2026 | https://arxiv.org/abs/2605.23899 | https://arxiv.org/pdf/2605.23899 |
| 7 | Serve Now or Improve Later? Scheduling Self-Evolution in Online Agent Systems (Wei et al.) | 2026 | https://arxiv.org/abs/2610.06212 | https://arxiv.org/pdf/2610.06212 |
| 8 | AgentBrew: Lifelong Knowledge Brewing from Strong Teachers to Weak LLM Agents (Jiang and Huang) | 2026 | https://arxiv.org/abs/2607.16851 | https://arxiv.org/pdf/2607.16851 |
| 9 | RSI-Router: Evolving Subtask-Level LLM Routing and Skills for Cost-Efficient Agents (Li et al.) | 2026 | https://arxiv.org/abs/2609.34712 | https://arxiv.org/pdf/2609.34712 |
| 10 | TACIT-Switch: Cost-Aware Model Escalation for LLM Agents from Censored Supervision (Lei et al.) | 2026 | https://arxiv.org/abs/2608.27911 | https://arxiv.org/pdf/2608.27911 |
| 11 | Better Harnesses, Smaller Models: Building 90% Cheaper Agents via Automated Harness Adaptation (Yang et al.) | 2026 | https://arxiv.org/abs/2607.08938 | https://arxiv.org/pdf/2607.08938 |
| 12 | Agentic Context Engineering: Evolving Contexts for Self-Improving Language Models (Zhang et al.) | 2025 | https://arxiv.org/abs/2510.04618 | https://arxiv.org/pdf/2510.04618 |
| 13 | AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents (Trivedi et al.) | 2024 | https://arxiv.org/abs/2407.18901 | https://arxiv.org/pdf/2407.18901 |
| 14 | Repo2Skill-Evo: Repository Skills Go Stale in Silence (Duan et al.) | 2026 | https://arxiv.org/abs/2608.21964 | https://arxiv.org/pdf/2608.21964 |
| 15 | Not All Disagreement Is Learnable: Token Teachability in On-Policy Distillation (Wang et al.) | 2026 | https://arxiv.org/abs/2605.26844 | https://arxiv.org/pdf/2605.26844 |
| 16 | FlashScript: Compiling Recurring Agent Workflows into Reusable Neuro-Symbolic Programs (Sabouri et al.) | 2026 | https://arxiv.org/abs/2610.33876 | https://arxiv.org/pdf/2610.33876 |
| 17 | MERA: Model Evolution and Routing with Skill Adaptation for Agentic Systems at Scale (Yao et al.) | 2026 | https://arxiv.org/abs/2608.10333 | https://arxiv.org/pdf/2608.10333 |
| 18 | Agent Workflow Memory (Wang et al.) | 2024 | https://arxiv.org/abs/2409.07429 | https://arxiv.org/pdf/2409.07429 |
| 19 | SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks (Li et al.) | 2026 | https://arxiv.org/abs/2602.12670 | https://arxiv.org/pdf/2602.12670 |
| 20 | Agentic Plan Caching: Test-Time Memory for Fast and Cost-Efficient LLM Agents (Zhang et al.) | 2025 | https://arxiv.org/abs/2506.14852 | https://arxiv.org/pdf/2506.14852 |
| 21 | PreAct: Computer-Using Agents that Get Faster on Repeated Tasks (Li) | 2026 | https://arxiv.org/abs/2606.17929 | https://arxiv.org/pdf/2606.17929 |
| 22 | Improving Online Algorithms via ML Predictions (Purohit, Svitkina, Kumar; NeurIPS 2018) | 2018 | https://arxiv.org/abs/2407.17712 | https://arxiv.org/pdf/2407.17712 |
| 23 | FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance (Chen et al.) | 2023 | https://arxiv.org/abs/2305.05176 | https://arxiv.org/pdf/2305.05176 |

### Suggested NotebookLM questions
1. "PACE treats compiling as rent-or-buy with a compile that can fail. PFSUM treats the Bahncard discount β as known. ASSAY and Huang et al. show skills can make an agent worse. Write down what a Bahncard problem looks like when β is random and can exceed 1, and which of PACE's or PFSUM's guarantees survive."
2. "Compare how StepGate, the failure-risk paper (2608.14927) and RSI-Router use a model's own signals to decide escalation. When does self-prediction work and when is it worse than random? What would a learning-augmented algorithm need from that advice to be both consistent and robust?"
3. "Across ASSAY, Huang et al., SkillsBench, RSI-Router, FlashScript and AgentBrew, list every case where a skill or note made the agent worse. What do the harmful cases share: who wrote it, from what run, for which reader, on what kind of task?"
4. "Token teachability says a correction is learnable when it lands in the student's top choices. TACIT labels a recoverable divergence window. StepGate Fig 9 shows which failure types the cloud can fix. Could these combine into a test, before paying, of whether an in-context guide will fix a small model's failure?"
5. "Collect every break-even number across PACE, LearnSched, MERA, AgentBrew and Better Harnesses. Put them in the same unit where possible. How much does the choice of unit (tokens, dollars, GPU time) change which option wins, and what should a local-vs-cloud agent report?"

## Verified references

`lit.py verify-file raw/loopy-lit/refs.json` → **26/26 OK** (Oct 26, 2026). Includes every paper in the stack plus RouteLLM 2406.18665, Ski Rental with Uniform Stochastic Signals 2610.26214 and TraceCompiler 2608.02680. Separately verified: DOI 10.1145/3848038.3848063 (Confidence-Aware Learning-Augmented Algorithms for the Bahncard Problem) OK.

## Search log summary (Oct 26, 2026)

| Query | Window | Sources | Hits |
|---|---|---|---|
| route or teach small model | 6 mo | arXiv + OpenAlex + S2 | 15 |
| skill distillation small agent cost | 6 mo | same | 19 |
| learning-augmented ski rental LLM | 6 mo | same | 12 |
| online algorithm predictions LLM | 6 mo | same | 22 |
| LLM self-prediction routing | 6 mo | same | 24 |
| agent skill library staleness | 6 mo | same | 24 |
| workflow caching agent cost | 6 mo | same | 29 |
| learnability gap distillation | 6 mo | same | 24 |
| teachability weak student strong teacher | 6 mo | same | 12 |
| self-generated skills agents | 6 mo | same | 22 |
| Bahncard problem predictions | 6 mo | same | 11 |
| agent skill reuse break-even | 6 mo | same | 12 |
| LLM advice learning-augmented algorithm | 6 mo + all | same | 23 + 10 |
| rent or buy LLM agent | 6 mo + all | same | 12 + 10 |
| when to distill versus route | 6 mo + all | same | 12 + 10 |
| skill transfer strong to weak agent | 6 mo + all | same | 12 + 11 |
| compile agent trajectory program reuse | 6 mo + all | same | 15 + 21 |
| procedural knowledge transfer capability limit small model | 6 mo + all | same | 35 + 30 |

Citation trails (refs, citing papers, recommendations): PACE 2610.02932 (found LearnSched, TraceCompiler, PreAct, HEXIS, Purohit, rent-or-buy with expert advice), FlashScript 2610.33876 (no results returned), TACIT-Switch 2608.27911 (found StepGate, LEASH 2610.22280, Handoff Curves 2610.15993, Signed Rescue Routing 2609.07786). Raw search output: `raw/loopy-lit/search6.txt`; full log: `lit_search_log.jsonl`.

**Next step to close the falsifier risk:** in mid-November, rerun the PACE citing-paper trail and the "learning-augmented" plus "skill" queries; anything citing both PACE and PFSUM is the paper to beat.
