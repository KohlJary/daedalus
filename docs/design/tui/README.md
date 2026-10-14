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
notation: fixed-width box drawing, `◆Name` component references, one diagram
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

## From Wonderland's TUI (~/wonderland-ai/src/wonderland/tui)

Take:
- The app owns long-lived state and screens subscribe and replay
  (`active_run.py`).
- Detached processes survive a restart and are found again on startup (tmux
  here).
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
