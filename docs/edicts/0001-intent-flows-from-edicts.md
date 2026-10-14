# Edict 0001: Intent flows from edicts
Status: done
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

## Amendments
- 2026-10-13, requested by Kohl: an approved Ariadne plan is also a source of
  approved intent, not only an accepted edict.
  - Approved intent is either an accepted edict's Intent and Acceptance
    criteria, or an approved plan's work package: its full description plus
    the plan's source (the edict it came from, or the feature request), with
    who approved the plan and when.
  - Kohl or the main Claude Code session may approve a plan. The plan records
    which, and when. An edit after approval voids it until the plan is
    approved again.
  - The gate reads approval from the edict file or the stored plan, never
    from a diff's metadata alone.
  - A plan sourced from an edict is approved intent only while that edict is
    accepted and has no open dissent. "Only accepted edicts are dispatched"
    still holds for those plans. A plan that isn't from an edict may be
    dispatched once approved.
  - Diffs with neither an accepted edict nor an approved plan are still
    routed to `NEEDS_REVIEW` in every autonomy mode.
  - Added acceptance criterion: a test where a package from an approved plan
    goes Dispatcher -> worker harness -> orchestrator and auto-commits on the
    judge's APPROVE, and one where the same package from an unapproved plan
    goes to `NEEDS_REVIEW`.

  Why: the planned local-worker loop (gameplan T-e11) puts the human or
  main-session judgment on the plan, once, instead of on every diff. A fresh
  Claude worker costs about as much as Claude doing the feature itself, so
  per-diff human review leaves the loop nothing to save. Reviewing plans also
  catches real defects before dispatch (same-file parallel packages,
  interface gaps). The judge grading only the feature title is why it must
  see the package's full description.
