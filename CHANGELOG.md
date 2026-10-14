# Changelog

## 0.2.0 (2026-10-14)

The first release since 0.1.2 (May 2026). Daedalus now plans with you, remembers across sessions,
coordinates with other people's agents, and gates parallel workers before anything lands.

### Added
- **Gameplan-first memory** (edict 0007): `daedalus doctor` checks memory drift (gameplan behind the
  code, stale tasks, unreferenced edicts); a session-start hook prints a short brief; an optional
  capture hook proposes gameplan updates from commits.
- **`/exhale` and `/inhale` skills** (edict 0004): preserve a session's work at a breakpoint, and pick it
  back up after compaction. `hydrate` and `init` install plugin skills.
- **Memory reconstruction from git** (edict 0006): `daedalus reconstruct gather | check | import`, the
  `mnemosyne` agent, and `/reconstruct` rebuild missing gameplan history from commits.
- **Workstreams** (edict 0008): several owners or sessions each keep their own plan in the same
  project, with per-owner drift and collision findings in `doctor` and the brief.
- **The agent board** (edict 0009): threads between different owners' agents over a git branch, with
  owner-approved posts and citations checked against commits.
- **Edicts** (edicts 0001, 0003, 0005): design decisions as accepted documents, opt-in per project
  (`daedalus init --edicts`), with `daedalus edict list | show`, dissents, and status handoffs.
- **Palace call-graph queries** for the main agent: `daedalus palace callers | callees | impact
  [--tests] | path | tests-for [--diff]`. They build a call graph from source on every call, need no
  palace, and write nothing. Measured on this repo, test selection lists 93% of the tests that
  actually execute a changed function (a superset, not an exact list).
- **Momus**, a critic agent that checks claims against evidence before they're believed.
- **Ariadne**:
  - an approved-intent gate: diffs are reviewed against an approved plan or accepted edict, and
    anything without one goes to NEEDS_REVIEW;
  - model casting (`ariadne.worker_model`, `ariadne.judge_model`), recorded on each diff;
  - conflict escalation that actually holds both diffs (`... orchestrator conflicts list | resolve`);
  - `plans approve` for approving a plan from the CLI.
- `hydrate` local slots and per-project template settings (`daedalus config --project`).
- CI runs the test suite on pull requests (Python 3.10 and 3.12).

### Fixed
- **Workers run with the real Icarus identity again.** Since 2025-12-24 a moved file made workers
  using the default prompt silently fall back to a 266-character stub. A missing identity now warns.
- Ariadne:
  - escalated conflicts were never recorded, so two incompatible diffs touching different lines
    could merge in one commit;
  - atomic commits dropped new files and swept in unrelated modified files;
  - workers' diffs never reached Ariadne;
  - parallel workers shared one working tree;
  - the verifier could pass a broken diff when the temp directory sat inside another git repository;
  - the judge saw only a work package's first line.
- Windows: imports, UTF-8 file handling, and CLAUDE.md line endings.
- The palace status crash, and the root cause of room misplacement.
- Shipped agents, skills and commands (`test-runner`, `labyrinth`, `mind-palace`, `/palace`) no
  longer contain Cass Vessel specifics or a hard-coded home path.

### Known issues
- **Ariadne's buses default to machine-wide paths** (`/tmp/icarus-bus`, `/tmp/ariadne-bus`), so two
  projects on one machine share them (#14). Run one project's Ariadne at a time until per-project
  defaults land.
- Ariadne's verifier picks tests by file name and runs none when nothing matches (#15). Pair it with
  `daedalus palace tests-for --diff`, or run the full suite.
- The palace builder's own call graph (used for rooms) drops private methods; the new query commands
  don't share that limitation.
