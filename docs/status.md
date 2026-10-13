# Status

*Committed handoff snapshot. Daedalus updates this at the end of each working
session so work can be picked up from outside the session. See
`docs/edicts/README.md`.*

**Last updated:** 2026-10-13, by a Daedalus session (branch `test/ariadne-real-smoke`)

## Current phase
Ariadne: proving the worker -> Ariadne -> verify -> commit loop. The hermetic
tier (real worker, scripted model) is done on `test/ariadne-real-smoke`; the
live tier with real models is proposed in #16 and waits on an edict.

## Edicts
| Edict | Status | Notes |
|-------|--------|-------|
| 0001 Intent flows from edicts | proposed | Depends on the semantic review gate (merged) |
| 0002 Model casting | proposed | Not started. A worker `model` parameter was added and then removed on `test/ariadne-real-smoke` so 0002 gets built to its spec. Its "no non-Anthropic backends" non-goal conflicts with the local backend proposed in #16. |
| 0003 Dissent | proposed | |

## Open dissents
None.

## In flight
- `test/ariadne-real-smoke`: hermetic end-to-end tests through a real `IcarusWorker`, and the fixes they forced (see "Last session"). PR to `main`.
- #12 `template/reach-for-tools` (open PR).
- Issues: #6 (hydrate edited-file detection), #13 (permission path-prefix check), #14 (machine-wide bus roots), #15 (verifier passes when no tests match), #16 (proposal: local backends + live tier).

## Last session
Built `tests/test_ariadne_worker_loop.py`: a real worker executing work
packages in Ariadne mode with only the model scripted, the real verifier
running a fixture project's pytest suite, the orchestrator merging and
committing. Every test failed on the existing code. Fixed:
- Worker diffs never reached Ariadne (the prompt asked the model to call a
  harness method it had no tool for; nothing else called it). The harness now
  submits the diff itself.
- New files were dropped (`git diff HEAD` skips untracked files).
- Parallel workers shared one working tree. Each work package now runs in its
  own git worktree.
- The verifier passed a change that breaks a test: when the temp dir is inside
  another git repository, `git apply` skipped the whole patch and exited 0. The
  copy is now its own repo, and a skipped patch fails setup.

**Guardrail:** never run live model calls (workers, judge, the live tier) on
an employer's account or machine. The hermetic tier needs no model.

**Next, in order:** merge `test/ariadne-real-smoke`; decide 0002 and #16 (amend
or new edict for local backends); build the local backend with a stub-server
test; then the live tier, local first on the home GPU.
