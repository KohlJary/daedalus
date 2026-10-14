# Status

*Session note. Progress (phases, tasks, which edicts are built) lives in the
committed gameplan, `.daedalus/roadmap/gameplan.json`: run `daedalus gameplan show`
and `daedalus doctor`. This file carries what the gameplan can't say. See
`docs/edicts/README.md`.*

**Last updated:** 2026-10-14, by the Ariadne/experiment Daedalus session (the memory-side session's notes follow)

## Ariadne session (2026-10-13/14)
- **Released 0.2.0** to PyPI and GitHub (PR #35, tag v0.2.0). Verified by a fresh install from PyPI.
  It shipped the palace query CLI (T-e18, PR #33), the real Icarus identity again (T-e13, PR #34),
  and generic shipped agents (the test-runner had a hard-coded Cass Vessel home path). #14 is a known
  issue.
- **Gate experiment (pilot design, arm D, bare prompt):**
  - Verifier plus the qwen3-coder judge: 0 bad of 121 landed, against 26 of 151 ungated.
  - One retry with feedback: 121 -> 129 correct landed, but 2 bad got through.
  - Mutation test of the judges (H2): both near the 10% false-approve line, neither conclusively
    below it.
  - The code and results so far are on the local branch exp/ariadne-local (worktree ../daedalus-exp,
    not pushed).
- **Still running overnight**, from that session's background queue:
  - arm A (identity, H4);
  - refactor, ambiguous and colliding-pair tickets;
  - toy features under 5 planning conditions;
  - the mature run on this repo;
  - greenfield;
  - the memory arm.
  ComfyUI restarts automatically when the queue ends.
- **Found and logged** (gameplan): T-e8, T-e10, T-e11 (CLI-loop direction), T-e12 (test backlog),
  T-e13 and T-e14 (both fixed), T-e15 to T-e18. Claude baselines are staged for 2026-10-23, at Kohl's
  budget call (experiments/ariadne-local/mature/RUNBOOK.md, greenfield/RUNBOOK.md).
- **Next:** read the overnight results; hand-audit the oracle/gate disagreements; write REPORT.md
  (with Momus) on exp/ariadne-local; then a one-page map of the system as it now exists.

## Last session
- Built and merged edicts 0005, 0001 (as amended: an approved plan is approved
  intent), 0003, 0002 and 0008 (PRs #23-#26, merged as 915d65d). Each was
  reviewed by Momus before merge; its findings were fixed with tests.
- PR #28 (open): Ariadne recorded no escalated conflicts, so incompatible diffs
  could merge (T-e14, found by the Ariadne session).
- Edict 0009 reshaped from a mailbox into an agent message board, at Kohl's
  request. It is the next build.
- Two sessions worked in parallel (Ariadne and memory) and coordinated over
  Claude Code's cross-session messages; edict 0008 now models that.

## Open dissents
None.

## Notes
- Guardrail: never run live model calls (workers, judge, the live tier) on an
  employer's account or machine. The hermetic tier needs no model.
- Untested in 0007: Windows paths and console encoding.
