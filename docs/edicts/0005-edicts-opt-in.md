# Edict 0005: Edicts opt-in, intent from any approved source
Status: accepted
Depends on: Edict 0001 (intent flows from edicts)

## Intent
Edicts are how Kohl runs his own projects. They should not be imposed on
every project that installs Daedalus. In a team or enterprise repo, design
intent already lives in tickets, issues, and ADRs, and "merging is sign-off"
already means something else there. A default CLAUDE.md that says "only build
accepted edicts" would stall ordinary work.

The part that must hold everywhere is narrower: Ariadne's judge grades a diff
against intent a human approved, never against the worker's own description
(0001). That rule does not care where the intent comes from. So edicts become
one intent source among others, and they are off by default.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and
committed to `main` directly at his instruction.

## Constraints
- Config key `edicts.enabled` (default `false`). `daedalus init --edicts` sets
  it to `true` and scaffolds `docs/edicts/README.md` (format and lifecycle) and
  `docs/edicts/dissents/`.
- The CLAUDE.md template's Edicts section, and its edict line in the status
  handoff, are rendered only when `edicts.enabled` is true. Otherwise neither
  appears.
- Ariadne reads approved intent through a single intent-source interface that
  returns: source ID, intent text, acceptance criteria, and whether it is
  approved. Built-in sources:
  - `edict`: accepted edicts on `main` (0001's rules, unchanged).
  - `github-issue`: an issue carrying a configured approval label (default
    `approved`), with its body as intent and an `## Acceptance criteria`
    section as criteria.
- 0001's fail-closed rule applies to every source. A diff with no approved
  intent goes to `NEEDS_REVIEW` and is never auto-committed.
- Where this conflicts with 0001's "only edicts with `Status: accepted` may be
  dispatched", this edict governs: work items from any approved source may be
  dispatched.
- This repository enables edicts (`edicts.enabled = true`).

## Acceptance criteria
- With `edicts.enabled` false, `daedalus init` creates no `docs/edicts/`, and
  the rendered CLAUDE.md contains no edict instructions.
- With it true, the rendered CLAUDE.md matches today's Edicts section, and
  `docs/edicts/README.md` exists after init.
- Re-rendering the managed CLAUDE.md section in a project that already has
  edicts on disk but no config key leaves the Edicts section in place and
  prints a hint to set `edicts.enabled`. Upgrading never silently drops it.
- Ariadne planning from a `github-issue` source records
  `diff.metadata["intent_source"]` (e.g. `github-issue:42`) and the intent and
  criteria, and the judge grades against those.
- An unlabeled issue is not approved. Its diffs route to `NEEDS_REVIEW`.
- Tests cover: template rendering with the flag on and off, the upgrade hint,
  both sources, and fail-closed for each.

## Non-goals
- No Jira, Linear, or ADR sources yet. The interface should allow them; the
  edict does not build them.
- Dissent (0003) stays edict-only. Other sources raise disagreement through
  their own channels (issue comments, review).
- No change to how Kohl's own edicts are written, accepted, or amended.
