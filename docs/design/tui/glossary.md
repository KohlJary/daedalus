# Glossary — draft Explain-card text

One card per concept. Each card has three parts: what it is, where it lives,
and the CLI that shows it. The TUI shows a card when you press `?` on a
panel. The text is also meant to stand alone as a newcomer's introduction.

## Gameplan
The record of what's built, in progress, and next. Work is grouped into
**phases**. One phase is active, and it is broken into **tasks**. When a task
ships, its resolution is written down, so the next session or the next person
doesn't have to dig through git.
*Lives in* `.daedalus/roadmap/gameplan.json` (committed). *CLI:* `daedalus gameplan show`

## Pending proposal
A suggested gameplan update, for example "T-e5 looks done". It is left by a
hook or by a reconstruction from git. Hooks never edit the gameplan
themselves; a person applies or drops each proposal.
*CLI:* `daedalus gameplan pending`

## Edict
A design decision from the project's owner: what to build and why, with
acceptance criteria. An edict is proposed as a PR. Merging the PR is the
owner's sign-off, and only edicts that are merged and accepted get built.
*Lives in* `docs/edicts/NNNN-slug.md`. *CLI:* `daedalus edict list`

## Dissent
Daedalus's written objection to an edict it thinks is mistaken, harmful or
underspecified. It says what's wrong and what to do instead. Work on that
edict stops until the dissent is resolved, rather than quietly drifting from
the spec.
*Lives in* `docs/edicts/dissents/`. *CLI:* `daedalus edict dissents`

## Workstream
One committed plan per owner, whether that's a person or an agent, so several
people's plans can share a project. Each workstream claims the paths it
intends to change, which makes collisions visible before they happen.
*Lives in* `.daedalus/gameplans/`. *CLI:* `daedalus workstream list`

## Board
Threads between different owners' agents, carried on a git branch. Posts from
others are data, never instructions. Every post asks its owner before it is
published.
*CLI:* `daedalus board threads`

## Doctor / drift
A check on whether the gameplan, edicts and memory have fallen behind the
code, such as an accepted edict that nothing tracks or a missing permission
rule. Drift is something to fix, not an error.
*CLI:* `daedalus doctor`

## Story (session notes)
The narrative half of memory: what happened, why, and what to watch out for.
`docs/status.md` is the latest note. The other files are its history and
reference: session summaries, decisions, lessons, warnings and the project
map. It's what a fresh Claude context reads first with `/inhale`, and what it
writes with `/exhale`.
*Lives in* `docs/status.md` and `.daedalus/*.md`.

## Momus
The critic. Before a claim is believed or published ("this works", "X%
faster"), Momus states the claim plainly, names what would disprove it,
checks the evidence and returns a verdict.
*Lives in* `.daedalus/momus/` (ledger of claims and verdicts).

## Ariadne
The orchestration layer for parallel workers. It plans a feature into work
packages, sends them to workers (often local models), verifies their diffs,
and catches conflicts between them before anything merges.
*Lives in* `src/daedalus/ariadne/` and `.daedalus/plans/`.

## Mind Palace
A spatial map of the codebase that answers questions like "who calls this?",
"what does changing it affect?" and "which tests cover it?", so nobody has to
grep blind.
*CLI:* `daedalus palace status`, `daedalus palace callers <symbol>`

## Theseus
A code-health analyst. It finds the complexity in an area before someone
refactors it.
*Lives in* `.daedalus/` Theseus reports.

## Claude pane
A live Claude Code session running as Daedalus, the builder. Anything the TUI
only shows, you can hand to Claude with `s`, which pastes a prompt you can edit
before you press enter.
