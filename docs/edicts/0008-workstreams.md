# Edict 0008: Workstreams
Status: accepted
Depends on: Edict 0007 (gameplan, doctor, session-start hook); Edict 0006 (reconstruct, for
per-workstream reconstruction)

## Intent
Let more than one person or session work in the same project, each with its own plan, without
overwriting each other and without colliding unseen.

The gameplan has one active phase. On 2026-10-13 two Daedalus sessions worked this repository at
once, one on Ariadne (phase p1) and one on memory (edicts 0007 and 0006). The memory work could
not be made the active phase without clearing p1's task list, so it was tracked in phase notes
instead. A team has the same problem, worse.

A workstream is one owner's plan: a person, or a session. Each is its own committed file, so two
owners updating their plans never conflict in git. Together they are the public coordination
layer: phases, tasks, resolutions, the edicts they implement, and the paths they intend to change.
Nothing else is shared. Private memory stays on each owner's machine.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and committed to `main`
directly at his instruction.

## Constraints
- A workstream is `.daedalus/gameplans/<id>.json`, committed, in the gameplan schema plus an
  `owner` block: `{"id", "kind": "person" | "session", "git_author": "<pattern for git --author>"}`.
- The existing `.daedalus/roadmap/gameplan.json` remains the default workstream. A project that
  never creates another workstream works exactly as it does today.
- The current workstream comes from `DAEDALUS_WORKSTREAM`, then the local project config
  (`workstream.current` in `.daedalus/config.json`, which is not committed), then the default.
- A workstream may list `claims`: paths or globs it intends to change.
- Commands write only the current workstream unless `--workstream` names another. Hooks and
  `doctor` read all of them and write none.
- Everything stays deterministic: no model calls in workstream commands, hooks, or checks.
- Collisions are findings, not locks. Nothing blocks a commit or a dispatch.

## Acceptance criteria
- `daedalus workstream new <id> [--kind person|session] [--author PATTERN]`, `list`, `use <id>`,
  and `show [<id>]` exist.
- `gameplan` commands accept `--workstream <id>` and otherwise act on the current workstream.
- Two workstreams can each have an active phase with its own tasks at the same time. A test
  reproduces 2026-10-13: an Ariadne workstream and a memory workstream, each activated, neither
  disturbing the other.
- The session-start brief shows the current workstream's phase and next task first, then one line
  per other workstream (owner, active phase, current task), and stays under 40 lines.
- `doctor` runs its gameplan checks per workstream, counting only commits matching that
  workstream's `git_author` for commits-after-gameplan, and adds collision findings:
  - two workstreams with open work citing the same edict
  - two workstreams whose `claims` overlap
  The edict-not-in-gameplan check counts references from every workstream.
- `daedalus reconstruct gather --workstream <id>` anchors on that workstream's file and filters
  by its `git_author`.
- Tests cover: the default workstream unchanged for single-plan projects, concurrent active
  phases, per-owner drift, both collision kinds, and the brief.

## Non-goals
- No messaging between agents. That is edict 0009.
- No locks, and no change to Ariadne dispatch on a collision (a later edict may pause dispatch).
- No reports about people: no per-person activity summaries, counts, or comparisons. A workstream
  is its owner's plan, kept for picking work back up, not a view of how someone works.
- No sharing of anything in `.daedalus/` beyond the workstream files.
