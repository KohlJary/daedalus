# Edict 0001: Intent flows from edicts
Status: accepted
Depends on: Ariadne semantic review gate (`feat/semantic-review-gate`, currently
merged into `feat/local-slots-config`, not yet on `main`)

## Intent
Every Ariadne task traces back to a human-approved statement of intent. The
semantic judge grades diffs against that statement, never against the worker's
own description of its work.

Today `Orchestrator._diff_intent()` falls back to `diff.description`, which the
worker writes. A worker that misunderstood its task will describe its wrong
implementation confidently, and the judge will approve the diff against that
description. The student is grading its own exam.

## Constraints
- Edicts live in `docs/edicts/NNNN-slug.md` in the format described in
  `docs/edicts/README.md`.
- Only edicts with `Status: accepted` may be dispatched to workers.
- When planning from an edict, the planner copies the edict ID into
  `diff.metadata["edict"]` and its intent plus acceptance criteria into
  `diff.metadata["intent"]`.
- Diffs submitted without an edict (ad hoc work) remain allowed, but they
  cannot be auto-approved by the judge.

## Acceptance criteria
- `_diff_intent()` no longer falls back to `diff.description`.
- A diff with no `metadata["intent"]` is routed to `NEEDS_REVIEW` in every
  autonomy mode, regardless of the judge's verdict. It is never auto-committed.
- `daedalus edict list | show <id>` exists and reads edicts from the current
  checkout. Acceptance happens by merging the edict to `main` (see the README's
  flow section), so there is no `accept` command.
- An edict's status moves to `done` when every diff tagged with its ID has
  merged.
- Tests cover: the fail-closed path for missing intent, intent being sourced
  from the edict, and the status transitions.

## Non-goals
- No UI. CLI and conversation only, matching `ariadne review`.
- No automatic edict generation. Daedalus does not write or accept edicts.
- No parsing beyond the section headings and the `Status:` line.
