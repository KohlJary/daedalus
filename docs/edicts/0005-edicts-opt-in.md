# Edict 0005: Edicts opt-in
Status: done

## Intent
Edicts are how Kohl sends designs from Claude in chat to Claude Code. They
should not be imposed on every project that installs Daedalus. In a team or
enterprise repo, design intent already lives in tickets, issues, and ADRs, and
"merging is sign-off" already means something else there. A default CLAUDE.md
that says "only build accepted edicts" would stall ordinary work.

So edicts are off by default and turned on per project.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and
committed to `main` directly at his instruction.

## Constraints
- Config key `edicts.enabled` (default `false`). `daedalus init --edicts` sets
  it to `true` and scaffolds `docs/edicts/README.md` (format and lifecycle) and
  `docs/edicts/dissents/`.
- The CLAUDE.md template's Edicts section is rendered only when
  `edicts.enabled` is true.
- When edicts are off, Ariadne's fail-closed rule from 0001 still applies: a
  diff with no human-approved intent goes to `NEEDS_REVIEW` and is never
  auto-committed.
- This repository enables edicts (`edicts.enabled = true`).

## Acceptance criteria
- With `edicts.enabled` false, `daedalus init` creates no `docs/edicts/`, and
  the rendered CLAUDE.md contains no edict instructions.
- With it true, the rendered CLAUDE.md contains the Edicts section, and
  `docs/edicts/README.md` exists after init.
- Re-rendering the managed CLAUDE.md section in a project that already has
  edicts on disk but no config key leaves the Edicts section in place and
  prints a hint to set `edicts.enabled`. Upgrading never silently drops it.
- With edicts off, every Ariadne diff routes to `NEEDS_REVIEW`.
- Tests cover: template rendering with the flag on and off, the upgrade hint,
  and fail-closed with edicts off.

## Non-goals
- No other intent sources (GitHub issues, Jira, Linear, ADRs). Add them when a
  real team needs them.
- No change to how Kohl's own edicts are written, accepted, or amended.

## Amendments
- 2026-10-13, requested by Kohl: cut down to opt-in only. Removed the
  intent-source interface, the `github-issue` source, `intent_source`
  metadata, and the override of 0001's dispatch rule; 0001 stands unchanged.
  Dropped the dependency on 0001 and the edict line in the status handoff
  (0007, then numbered 0004, makes `status.md` a session note). Why: the
  pluggable sources were designed for enterprise teams that don't exist yet,
  and they added a second layer over the gameplan.
- 2026-10-13, requested by Kohl, alongside 0001's amendment: with edicts
  off, a diff is auto-approvable only if it comes from an approved Ariadne
  plan. The criterion "With edicts off, every Ariadne diff routes to
  `NEEDS_REVIEW`" becomes "With edicts off, every Ariadne diff that doesn't
  come from an approved plan routes to `NEEDS_REVIEW`". Why: approved plans
  are a source of approved intent that doesn't need edicts (see 0001).
