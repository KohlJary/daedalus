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

## Roadmap
Intake: the work that's been asked for, from anywhere, whether that's an idea,
a bug, or an item imported from ADO or Jira. The gameplan is what we're doing
about it: phases pull roadmap items in and break them into tasks.
Each item says where it came from: a source, or local.
*Lives in* `.daedalus/roadmap/index.json` (committed). *CLI:* `daedalus roadmap list`,
`daedalus roadmap show <id>`

## Source
A plugin that connects an outside tracker to Daedalus. ADO and GitHub Issues
ship with Daedalus; others, like Jira, can be added as plugins. A sync turns
outside items into pending proposals, and finishing the work proposes updating
the outside item. Like every outward-facing change, that update asks first.
*Lives in* `sources.<name>` in config; tokens in the system keyring. *CLI:*
`daedalus source list`, `daedalus source sync --dry-run`, `daedalus source status`

## Pending proposal
A suggested gameplan or roadmap update, for example "T-e5 looks done" or "a new
issue arrived from GitHub". It is left by a hook, a reconstruction from git, or
a source's sync. Hooks never edit the gameplan
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
*Lives in* `docs/status.md` and `.daedalus/*.md`. *CLI:* `daedalus hook session-start` (the brief), or read `docs/status.md`

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
*Lives in* a tmux session named `daedalus-<project>` on the `daedalus` socket (or a plain PTY that ends with the TUI). *CLI:* `tmux -L daedalus attach -t daedalus-<project>`

## Reflection
Daedalus reading its own Claude Code session logs to learn from them. It
counts what happened, writes periodic reports with checked citations, and
turns what it learns into proposals that you apply. None of it leaves this
machine.
*Lives in* `.daedalus/reflection/` (gitignored). *CLI:* `daedalus reflect due`

## Digest
One session's numbers: tokens, failures, denials, rejections,
interruptions and subagents. Each count can be traced to the events behind
it. Making a digest calls no model.
*CLI:* `daedalus reflect digest`

## Due
Which reflections are owed. Daily, weekly and monthly reflections are due only
for completed periods that had sessions. Small days roll into the week.

## delphi
The agent that writes a reflection report. Every claim in it must cite an
event or a digest field. `reflect check` and Momus both check the report
before you see it.

## User model
What Daedalus has learned about you, kept only on this machine. Each entry has
a confidence that fades over time unless you mark it stable. You can edit,
forget or delete any entry.
*CLI:* `daedalus reflect model user`

## Self model
What Daedalus has learned about itself, written in the first person. Each
entry is a **behavior** (what it did, from the record), an
**interpretation** (why, citing behaviors), a **stance** (something it
commits to, which only you can apply), or an **aspiration** (who it wants to
be, which binds nothing).
*CLI:* `daedalus reflect model self`

## Machine: employer
Whether this is an employer's machine. Leaving it unset counts as yes, on
purpose: reflection then runs only inside your own session, never as a
separate model call.
*Config:* `machine.employer`

## Config
Every setting Daedalus reads, each with a description, a default and the
values it takes. A setting can be set for you (globally) or for one project;
the project's value wins. Tokens are never settings: they live in the system
keyring and are never shown.
*Lives in* `~/.config/daedalus/config.json` (yours) and `.daedalus/config.json` (this project's, not committed). *CLI:* `daedalus config --schema`, `daedalus config <key> <value>`

## Dream
A protected phase where Daedalus generates widely about where the project
could go, judged only afterwards and only by you. Seeds come from what it
already keeps; a cold waking pass picks three to five ideas. Every dream is
labelled speculative: not a proposal, not evidence, not reviewed. Picks reach
the roadmap only through the `dream` source, as proposals you apply or drop.
*Lives in* `.daedalus/dreams/` (gitignored). *CLI:* `daedalus dream show`, `daedalus dream log`

## A/B experiment
Whether showing Daedalus its models at the start of a session helps. Each
session is put in an arm, `on` (it sees the models) or `off`, chosen in code
from a logged seed so nothing being measured can steer it. The experiment log
records runs, resolutions, arms and model changes as counts and IDs only, so
it can be shared.
*Lives in* `.daedalus/reflection/experiment-log.jsonl` and `arms.json`. *CLI:* `daedalus reflect log`, `daedalus reflect arm`

## TUI plugin
A package that adds to the TUI: a kind of item in Needs you, Explain cards, or
a screen in the plugin menu (`m`). It registers through the `daedalus.tui`
entry point. Plugins can't change the home screen's layout or add writes.
*Lives in* an installed package's `daedalus.tui` entry point. *CLI:* `pip show <package>`

## Send form
What `s` hands Claude. `prose` (the default) sends the prompt alone and logs
nothing. `text` adds the focused panel's state as plain lines; `ophanic` adds
the same facts as an Ophanic diagram, which says how to read it and writes
every count as a number. `ab` draws `text` or `ophanic` when you paste, in
code, so the two arms differ only in form. Each send under those three is
logged with its panel, form, a hash of the prompt, the snapshot's size and
whether you edited it, never the content.
*Lives in* `.daedalus/tui/sends.jsonl` (local). *CLI:* `daedalus tui sends`, `daedalus config tui.send_form ab`
