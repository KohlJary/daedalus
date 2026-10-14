# Ariadne with local models: experiments

Started 2026-10-13. Question: can cheap local models (Ollama on a 16 GB GPU) do Ariadne's work packages,
with Ariadne's gate keeping their mistakes off main, and Claude involved only where judgment matters?
Gameplan: T-e5 (local backends), T-e10 (planner), T-e11 (CLI loop). Results write-up: REPORT.md (pending).

| Path | What |
|---|---|
| `spike_local_worker.py`, `score.py` | First feasibility spike: can a local model drive a 4-tool loop at all |
| `gate_exp/tasks.py` | 10 small tasks, each with hidden oracle tests (validated by `validate_oracles.py`) |
| `gate_exp/exp.py` | Gate experiment: worker runs, Ariadne's real verifier + hidden oracle, local judges, retry arm, report |
| `gate_exp/feature.py`, `todo_app.py` | Multi-part features through Ariadne's real planner/dispatcher/harness/orchestrator; 5 conditions incl. an LLM planner and Claude plan review |
| `gate_exp/results/` | Raw JSONL: every diff, gate decision, oracle result, token usage |
| `gate_exp/mutate.py` | Mutation test of the judge: oracle-verified bugs injected into correct diffs, for large-n catch and false-reject rates |
| `gate_exp/tasks_new.py`, `collide.py` | Pilot-design ticket types: behaviour-preserving refactors, ambiguous tickets, colliding pairs |
| `gate_exp/make_ariadne_src.py` | Rebuilds the pinned Ariadne code the runs use (BASE_COMMIT + PR #24's atomic-commit fix) |
| `mature/` | Same conditions on this repo itself, with three real gameplan tasks; `RUNBOOK.md` has the Claude steps |

Design: `docs/experiments/ariadne-local-pilot.md` (PR #20). Tonight's runs use a bare worker prompt, so they are that design's arm D; arm A (Icarus identity) is `exp.py gen --arm A`.

Ground truth is always hidden oracle tests that neither workers nor the gate see. Each oracle is validated
to fail on the original code and pass on a reference implementation.

Guardrail: never run live model calls (workers, judge) on an employer's account or machine.
