# Loopy

**An open-source, local-first desktop agent that learns the tasks you repeat, and gets cheaper and more private the more you use it.**

> **Status: draft / early development.** This README describes the planned design for our COMS E6998-007 final project (Columbia University, Fall 2026). Nothing below is a measured result yet.

## Why

Many people want to automate routine digital work: turning emails into to-dos, splitting bills, organizing notes. Building automations by hand takes skill. Always-on AI agents exist, but they are closed, run in the cloud, and pay for a large model on every task, which costs money and sends your data off your machine. Cheap local models are private and fast, but they fail in ways that repeat.

Loopy is for people who are not yet comfortable building agents. It notices when the same kind of task comes up again and helps automate it, using a small model locally whenever it can.

## The research question: rent, coach or compile?

When the cheap model fails a task that keeps coming back, Loopy has three options:

| Option | What happens | Upfront cost | Cost per future run |
|---|---|---|---|
| **Rent** | Send the task to a cloud frontier model every time | none | high (and the data leaves the device) |
| **Coach** | The frontier model writes a short skill once; the cheap model follows it | medium | low (plus extra prompt tokens) |
| **Compile** | Turn a successful run into a parameterized workflow; the cheap model only fills in the arguments | higher | near zero |

Choosing between these is a multislope rent-or-buy problem from online algorithms (Lotker et al., 2012), with a twist the classic theory ignores: a coached or compiled skill can fail, and can even make things worse. We study:

1. **Break-even:** after how many repeats does coaching or compiling beat renting, in dollars and in cloud calls?
2. **Teachability:** which failures can be coached or compiled, and which need the frontier model every time?
3. **Control:** does a controller that predicts teachability and recurrence beat always-rent, always-coach and always-compile, while keeping its worst-case cost bounded (in the spirit of learning-augmented algorithms; Purohit et al., 2018)?

## Planned design

- **Our own agent loop** in Python, with no LangGraph or n8n, so we control exactly when the expensive model is called and what each call costs.
- **Skills from the failure point:** coach skills are written from the step where the cheap model's run diverged from a successful one, kept short, and tested on a held-out task before use.
- **Compiled workflows:** a successful run's code is saved as a parameterized function the cheap model calls.
- **Controller:** decides rent, coach or compile per recurring task, and falls back to renting when a skill fails.
- **Desktop app + MCP server:** exposes learned automations and shows money and cloud calls saved.

## Evaluation (planned)

- **Benchmark:** [AppWorld](https://appworld.dev) (Trivedi et al., ACL 2024): everyday multi-app tasks solved in code and graded by the final app state, on a small set of recurring productivity workflows.
- **Baselines:** cheap model alone, frontier model alone, always-rent, always-coach, always-compile.
- **Metrics:** task success, cost per solved task, latency, number of cloud calls, and how much user data leaves the device.
- **Analysis:** break-even curves, ablations of the controller, and an error analysis of when skills hurt.

## Repository layout (planned)

```
loopy/
├── agent/        # our agent loop and model clients (cheap/local and frontier)
├── skills/       # coach (in-context skills) and compile (parameterized workflows)
├── controller/   # rent / coach / compile decision policy
├── eval/         # AppWorld harness, baselines, cost and latency logging
├── app/          # desktop app and MCP server
└── docs/         # proposal, notes, results
```

## Getting started

Setup instructions will be added once the first baseline runs. AppWorld installs with `pip install appworld`; see its documentation for data download.

## Roadmap

| Date | Milestone |
|---|---|
| Oct 26, 2026 | Final proposal |
| Nov 2 | Agent loop + cheap and frontier baselines on an AppWorld subset |
| Nov 16 | Coach and compile |
| Nov 23 | Controller + desktop app |
| Nov 30 | Ablations and error analysis |
| Dec 7 | Demo |
| Dec 15 | Final report and repository |

## Team

- Ton Hoang Nguyen (Bill) ([@HahaBill](https://github.com/HahaBill))
- Alfredo F. Frontera Del Valle ([@AlfredoFFD](https://github.com/AlfredoFFD))
- Harsh Kumar

## Related work

- Trivedi et al. (2024). *AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents.* ACL.
- Wang, Mao, Fried, Neubig (2025). *Agent Workflow Memory.* ICML.
- Zhang et al. (2025). *Agentic Context Engineering (ACE).*
- Yang et al. (2026). *Better Harnesses, Smaller Models: Building 90% Cheaper Agents via Automated Harness Adaptation.*
- Lei & Huang (2026). *TACIT-Switch: Cost-Aware Model Escalation for LLM Agents.*
- Wang et al. (2026). *Not All Skills Help: Measuring and Repairing Agent Knowledge.*
- Lotker, Patt-Shamir, Rawitz (2012). *Rent, Lease or Buy: Randomized Algorithms for Multislope Ski Rental.* SIAM J. Discrete Math.
- Purohit, Svitkina, Kumar (2018). *Improving Online Algorithms via ML Predictions.* NeurIPS.

## License

[MIT](LICENSE)
