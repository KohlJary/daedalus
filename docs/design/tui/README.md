# Daedalus TUI — design diagrams

**Status:** draft design, not an edict. These diagrams are input for an edict
Kohl may write; nothing here is approved to build. Tracked as gameplan phase
`p8-tui`.

**Goal:** make Daedalus usable by someone who wasn't there when it was built.
Everything in `.daedalus/` and `docs/edicts/` exists, but today it's only
reachable by people who already know the vocabulary and the commands. The TUI
is the way in: it shows the state and explains each concept in place, and
behind every view it teaches the CLI.

(This supersedes the Dec 2025 "CLI/TUI Removal" entry in
`.daedalus/decisions.md`, which removed an earlier dashboard because "Claude
Code is the interface". Nothing in that old TUI is carried forward.)

Every screen is drawn in [Ophanic](https://github.com/KohlJary/ophanic)
notation (Daedalus's conventions and lint: [docs/ophanic.md](../../ophanic.md); the
[`ophanic` skill](../../../src/daedalus/plugin/skills/ophanic/SKILL.md) teaches sessions to draw first;
`daedalus oph check docs/design/tui --components src/daedalus/tui` lints these files): fixed-width box drawing, `◆Name` component references, one diagram
per `@variant`, and `## ◆Name` sections for a component's internals. Desktop
diagrams are 100 columns wide, narrow ones 60, and in-column panels are
drawn at their real width in the shell (34). The sample data is illustrative:
PR #38, edict 0011 and the board threads don't exist.

## Files

| File | What it shows |
|------|---------------|
| `shell.oph` | Home screen (desktop, narrow, first run), header, key bar and its focus states, tab bar |
| `needs-you.oph` | The queue of what's waiting on the owner: compact, empty, expanded, narrow, and the detail for each kind |
| `gameplan.oph` | Gameplan panel, phases → tasks → detail, workstreams tab |
| `health.oph` | `daedalus doctor` panel and its expanded view |
| `claude-pane.oph` | The embedded Claude Code session and the send-to-Claude modal |
| `edicts.oph` | Read-only edict browser |
| `board.oph` | Agent board threads |
| `story.oph` | The narrative: status now, session history, decisions, lessons, warnings, map |
| `explain.oph` | The `?` card shown on any panel, and the first-run welcome |
| `glossary.md` | Draft text for every Explain card |
| `sources.oph` | Source plugins (ADO, Jira, …): sync health, mapping, write-back |
| `config.oph` | Every setting, the layer it comes from, editing, and secrets |
| `reflection.oph` | Reflection (edict 0010, PR #39): due, reports, user and self models, the A/B experiment |
| `coverage.md` | How much of Daedalus the design shows, tracked over time |

## Screen map

```
shell ── 1 / enter ─▶ needs-you (expanded) ── PR/ED/DS/BD item ─▶ its detail
      ── 2 / enter ─▶ gameplan (expanded) ── tabs: plan · workstreams · roadmap
      ── 3 / enter ─▶ health (expanded)
      ── 4 / c ─────▶ focus Claude pane (ctrl+] returns)
      ── 5 / w ─────▶ story ── tabs: now · sessions · decisions · lessons · warnings · map
      ── e ─────────▶ edicts        ── b ─▶ board
      ── s (anywhere with a selection) ─▶ send-to-Claude modal
      ── ? (any panel) ─▶ explain card ── g ─▶ glossary
      ── , ─────────▶ config (also from Sources: c configure)
      ── R ─────────▶ reflection ── tabs: due · reports · user model · self model · experiment
esc returns to the shell from any expanded screen.
```

## Design rules these diagrams commit to

1. **Read-mostly.** The TUI calls the same library functions as the CLI and
   never parses CLI output. The only direct write in v1 is applying or
   dropping a pending gameplan proposal.
2. **Judgment stays where it lives.** Merging a PR and accepting an edict happen
   on GitHub, and board posts go through `daedalus board post`. The TUI shows
   these things and offers to hand them to Claude; it has no accept or merge key.
3. **Focus model.** While the Claude pane has focus, every key goes to Claude
   except `ctrl+]`. The key bar always says which mode you're in. No priority
   bindings, which would steal keys from the terminal.
4. **Send to Claude pastes, never submits.** There is always one human
   keystroke between a selection and Claude acting on it.
5. **Not colour alone.** Kinds and states carry text tags (`PR`, `ED`, `[>]`,
   `⚠`) so they read in any theme.
6. **Legible to a newcomer.** Every panel has an Explain card with three
   parts: what it is, where it lives, and the CLI that shows it. Labels say
   what a thing is, not its internal codename.
7. **Empty states teach.** A fresh project shows Welcome, not empty tables.
   An empty panel says what will appear there and how to start it.
8. **The TUI is a way in, not a dead end.** Every view names the file or
   command behind it, so a reader can leave the TUI and keep going.
9. **Owner-neutral.** The design never assumes the owner is Kohl: "Needs you",
   not "Needs Kohl".
10. **Config is editable, secrets are not visible.** Every setting can be
    changed from the TUI, at the layer you choose (user or project), through
    the same library as `daedalus config`. Credentials live in the system
    keyring and are never shown or written to a config file.

## Send form

What `s` hands Claude is set by `tui.send_form` (dream pick p2; the send-form A/B edict 0017 deferred):

- `prose` (the default): the prompt the screen builds, byte for byte as before, and nothing is written to disk.
  Nothing changes unless you opt in.
- `text`: the prompt, then the focused panel's state as plain text lines in a ```` ```text ```` fence.
- `ophanic`: the prompt, then the same state as an Ophanic diagram in an ```` ```oph ```` fence.
- `ab`: each send draws `text` or `ophanic` in code, from a seed and a counter in `.daedalus/tui/send-ab.json`.

Gameplan (each tab: plan, workstreams, roadmap), Needs you, Health, Edicts and Board have snapshots
(`src/daedalus/tui/sendform.py`). Other screens send prose.

**Same facts, different form.** `text` and `ophanic` are rendered from one spec per panel: the same graph, slugs,
labels, marks, details, links, counts and notes. A test checks that every node's id and label and every count
appear in both. That is why `ab` draws between them and not between `prose` and `ophanic`. The ophanic arm would
also carry the panel's state, which prose doesn't, so a difference couldn't be credited to form. Edict 0017's
amendment 6 calls the comparison arm "the panel's own text (`panel_text()`)". No such function existed, and
`text` is that arm. One difference remains: a diagram cuts labels longer than its box with `…`, and the text form
cuts nothing. Snapshots draw one box per row (full width) to keep cutting rare. Ids come first in each line (a
board thread's id and author come before its title) so they survive. The diagram says so in its reading notes.

**The arm is hidden until the paste.** Under `ab`, Send to Claude shows only the prompt and a note that a snapshot
will be added. The arm is drawn when you paste, and the snapshot is appended then. You see it in Claude's prompt
before you press enter. Cancelling draws nothing, so a send can't be re-rolled by cancelling. The seed sits in a
local file: this guards against accidental steering, not against an owner who reads it.

Momus's perception pilot (PR #69) found that a small model misread containment and read proportions off box widths.
So every snapshot opens with how to read it (a `·` line inside a box belongs to that box, and nothing else does),
spells out its marks, says that sizes and positions mean nothing, and states its counts as numbers. Every snapshot
passes `daedalus oph check` at 100 and 60 columns (tests/test_tui_send_form.py).

Each pasted send under `text`, `ophanic` or `ab` appends one line to `.daedalus/tui/sends.jsonl`. It stays local:
the folder carries its own `.gitignore`. A line holds the time, the panel, the form, a hash of the prompt, the
snapshot's size, the A/B draw, and whether you edited the text first. It never holds the content. Plain prose
isn't an arm, so it logs nothing. `daedalus tui sends` counts sends per form and per panel.

**Kohl to decide:**
- **Scope.** Amendment 6 says v1 covers only the Gameplan panel; this covers five. It is opt-in and off by
  default. The alternatives are to gate the other four behind `ab` only, or to drop them.
- **The criterion isn't met.** Edict 0017's acceptance criterion says the draw is "recorded in the session's
  reflection digest". That isn't built. Until each send is joined to the session that received it, and to what
  Claude did next, the A/B answers nothing: the log only says what was sent. That join, through reflection's
  digests, is the next step.

## Extensibility: sources and plugins

The TUI will grow, and different users track work in different places: ADO
at Kohl's work, Jira or GitHub Issues elsewhere. The seam for that belongs in
Daedalus core, not in the TUI, because a source is useful without the TUI too
(for example a `daedalus source sync` command).

**Sources (core).** A source plugin registers under a Python entry-point
group (for example `daedalus.sources`). It does three things:
- fetches items from the outside system;
- maps each item to **pending proposals**;
- optionally, proposes a write-back when something changes here.

Because imports arrive as pending proposals, an existing rule still holds:
nothing writes the gameplan until the owner applies it. Write-backs are
outward-facing, so they always ask first.

This also gives the roadmap a clear job, which coverage.md flagged as
confusing. The **roadmap is intake**: what's been asked for, from anywhere.
The **gameplan is the plan**: what we're doing about it. ADO maps onto that
as Epic → phase, Story → roadmap item, Task → gameplan task. GitHub Issues
maps as Milestone → phase, Issue → roadmap item, sub-issue → task. Each
source declares its own mapping. ADO and GitHub ship first-party (edict 0011).

The follow-on chain for one ADO story:

```
ADO AB#4812 ─sync─▶ pending proposal ─apply─▶ roadmap item + tasks
   ▲                                              │ Claude works them
   └─ asks first ◀── write-back proposal ◀── task done, with a resolution
```

Along the way:
- the Story view links `AB#` IDs back to ADO;
- `doctor` flags drift between the source and the gameplan (closed in ADO but
  still open here, or the reverse);
- Sources shows sync health (`sources.oph`).

**TUI contributions.** A plugin can add:
- a NeedsYou kind (its tag, detail renderer and actions);
- Explain cards;
- a full screen reached from a menu.

The shell layout itself is not pluggable. A fixed home screen is part of what
keeps it legible.

**Open questions for this layer:**
- Its own edict? Yes: sources and roadmap intake are one edict, the TUI is
  another (decided 2026-10-14).
- Conflicts: configurable per source (`on_conflict`: `propose` (default),
  `source` or `local`). Decided 2026-10-14.
- Credentials: never in the repo, but keyring or environment variables?
- Write-back granularity: state only, or also comments with the resolution?

## From Wonderland's TUI (~/wonderland-ai/src/wonderland/tui)

Take:
- The app owns long-lived state and screens subscribe and replay
  (`active_run.py`).
- Detached processes survive a restart and are found again on startup (the session
  backend here).
- Lazygit-style list then detail.
- Theme tokens only, cycled with `t`.
- Shared vim navigation and a quit confirmation.
- Liveness kept separate from progress (the chase strip).
- Smoke tests through Textual's test pilot.

Avoid:
- A 3,660-line screen and a 1,383-line single stylesheet. Here it's one widget
  per `◆component`, with its CSS beside it.
- A 0.5s polling loop per bridge. Here it's one file watcher over `.daedalus/`
  and `docs/edicts/` feeding every panel.
- Priority single-key bindings next to an embedded terminal.

## Open questions

- Should PRs come from `gh` (needs network and auth) or only from local
  branches ahead of main?
- Should a `@wide` (≥160 columns) layout give Claude a second column or a
  second pane?
- Should the TUI help the owner start a new edict from a template, or leave that to
  the editor and git?
- Should the Roadmap tab be its own view or fold into the gameplan's phase
  column?
- Is `ctrl+]` really unused by Claude Code? It needs checking.
- Reflection's model edits, digest-now and log export are writes beyond 0012's
  four kinds. Amend 0012 to allow them, or send them through Claude? (The
  user model is the owner's own data, which argues for allowing them.)

## Ophanic dogfooding log

Evidence for a possible edict making Ophanic part of Daedalus (gameplan
`p8-tui` notes). Record where the diagrams helped or got in the way.

- 2026-10-14: The diagrams were generated by a script with a width guard. It
  caught one header overflow that would have produced a ragged box by hand.
  `ophanic parse` (Feb 2026 build) can't read the shared-divider style used
  here: it collapses to the first component. It also returns side-by-side
  nested boxes as a column in the wrong order. Takeaway: the notation is useful
  now, and the parser isn't ready to depend on.
- 2026-10-14: Adding the newcomer goal touched the shell (a LastSession strip
  and a first-run variant). Because the shell only holds `◆` references, it was
  a two-line change; the panels' internals didn't move. Composition did its
  job.
