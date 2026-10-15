# Status

*Session note. Progress (phases, tasks, which edicts are built) lives in the
committed gameplan, `.daedalus/roadmap/gameplan.json`: run `daedalus gameplan show`
and `daedalus doctor`. This file carries what the gameplan can't say. See
`docs/edicts/README.md`.*

**Last updated:** 2026-10-15 ~05:30 EDT (overnight: edicts 0012, 0013; PRs #68-#71 for review); earlier: the night shift (edict 0011); earlier: the reflection session (edict 0010); the TUI-design, Ariadne/experiment and memory-side sessions' notes follow

## Reflection session (2026-10-14)
- **Edict 0010 written with Kohl** (in chat and with Claude in chat), amended twice: user/self
  models differ (scope, forget, stances, lineage), and aspirations, asked cold, as a source of
  entropy. On main: df976a8, 2ef8143, 4ff6a1c.
- **Built on feat/0010-reflection, PR #39**, CI green on Linux and windows-latest. Workstream
  `reflection` tracks it (T-r1..T-r8; T-r7 local runner waits on T-e5).
- **Checked three ways:** hand counts on real (scrubbed) transcripts; a delphi dry run on this
  repo's four sessions (passed check on the second try; its notes changed the digest); Momus's
  criterion-by-criterion review (13 defects, all fixed with tests).
- **Open questions for Kohl** (in the PR): keep per-event details (commands, error text, secrets
  redacted) in digests, or amend the edict; one PR vs two.
- **Not done:** no real reflection has run (nothing is due until 2026-10-15); the benchmark for
  whether reflection works is still to be designed (Kohl: separately from the edict). The
  shipped identity text calls Kohl "he"; a fix awaits Kohl's go-ahead.
- Digests of this repo's sessions are backfilled in the main checkout's .daedalus/reflection/.

## Overnight 2026-10-15 (Kohl asleep; merge autonomy granted for this night only)
Everything merged tonight went through Momus and green CI first. Audit trail:
- **Merged:** #53 hook registration (several commands per event; T-e28); #54 reflection fixes from the first real
  run (T-r10, T-r12..T-r17); #55 edict 0013 dreaming (accepted, then amended from Momus's readiness review, built,
  reviewed twice, fixed). Edict 0013 and 0011 are `done`.
- **Edict 0014 (time and usage)** is on main as `proposed`, not accepted: Momus found 4 blockers; Kohl asked to
  formalise it later. `autoContinueAtUsageLimit` is on in Kohl's user settings (backup: ~/.claude/settings.json.bak-2026-10-15).
- **Edict 0012 (the TUI): merged as #61** and `done`. Core by Daedalus, screens by four parallel agents in separate
  worktrees, integrated; Momus reviewed (4 blockers: Textual's inherited ctrl+q/ctrl+c/ctrl+p reaching past the
  Claude pane and the palette's screenshot writing a file; two plugin protocols; Rich markup in project text crashing
  it; branch behind main) and verified the fixes. Not yet run against a real Claude Code session; needs the fresh
  install below to run here. Momus's open lows: cramped narrow layouts on some screens, no Dream screen, modified
  Enter is only a newline on terminals that report it.
- **Hermes → the Chorus** (#59, another session's PR, renamed at Kohl's call); "Chorus portents" is on the roadmap.
- **Later the same night (Kohl awake on and off; merge grant still on):**
  - **Merged:**
    - #65: doctor sees a stale or shadowed install (T-e27), which is what broke `source list` here.
    - #66: reflection-check leaks. Ratios and ranges now count as numbers; multi-day totals are refused, figures
      included; old tombstones still match, so forgetting stays forgotten.
  - **Dream-log PRs:** #56, #57, #58 and #62 were merged by Kohl. #64 (the `self` source) is open for review. The
    first dream moved to `.daedalus/dreams/2026-10-15/`, and its picks are roadmap `idea` items whose status tracks
    what's built (`daedalus roadmap list`).
  - **Edict 0017 (Ophanic, `proposed`): PR #70, for Kohl to accept or not; not merged.**
    - Momus's build review found 8 problems. The lint was overfitted to the TUI's diagrams, and the maps had edge
      and rendering bugs.
    - All 8 are fixed in 5ab9cf3, and Momus's re-verification is "shown".
    - Untested: the skill hasn't been tried in a real session.
    - `oph.components` has no committed project default, so doctor checks components only when you set it.
  - **The Ophanic perception pilot: PR #69, for review.** It ran on qwen3:8b with thinking off and is descriptive
    only.
    - Layout spatial questions: tied with the text encodings.
    - Proportions: Ophanic scored worse than always guessing "25"; the text encodings state the percentages outright.
    - Containment: a real gap for this model, 1 vs 29 on paired questions against JSON.
    - Graphs: at the floor in every encoding.
    - It says little about Claude. DESIGN.md has amendments A1-A9, informed by the pilot and awaiting Kohl's
      confirmation before any confirmatory run.
  - **The TUI Dream screen: PR #68, for review.** It opens on `D`, is read-only and is fully mode-blind. Momus's
    fixes are in, his verdict is ship, and CI is green.
    - Kohl to decide: whether the TUI may show the per-mode counts that 0013 allows in `dream log`.
  - **The TUI send form (dream pick 2): PR #71, for review.** It is stacked on #70; retarget it to main once #70
    merges.
    - `tui.send_form` takes `prose` (the default: unchanged, writes nothing), `text`, `ophanic` or `ab`.
    - `ab` draws between `text` and `ophanic`, which carry the same facts: labels are cut once, before either is
      rendered.
    - Each send's form goes to `.daedalus/tui/sends.jsonl`, with no content. `daedalus tui sends` summarises it.
    - Momus: three rounds, verdict ship. CI is green.
    - Kohl to decide: five panels, where 0017 amendment 6 says Gameplan only.
    - Not met: 0017's reflection-digest join. Until it exists, the A/B can't say which form helped.
  - **Coordination with the other session (daedalus-42):** it has 0015 (context map) and 0016 (toolbox hooks). The
    Ophanic edict was renumbered 0017. The file split is agreed, and the TUI's panel shapes are written into its
    edicts.
  - **A stand-in clock hook** is in this checkout's `.claude/settings.local.json` (`.claude/hooks/clock.sh`). Remove
    it when 0016's kit or 0014 provides the clock.
- **Dream-log ideas, as PRs for review, not merged:** #56 edicts with tests attached (pick 38); #57 `daedalus page`
  (pick 33).
- **A test leaked into real data:** one TUI test run wrote 4 test entries into `~/.config/daedalus/models/` (the
  models were empty before). Moved out (backup in the session scratchpad); the suite now redirects XDG config/cache
  for every test, with a guard test.
- **Kohl's install is stale:** the live `daedalus` is a Dec 2025 user-site editable named `daedalus` 0.1.0, so new
  dependencies and entry points (sources, dream, tui) are missing on this machine: `daedalus source list` finds no
  plugins. Fix: `pip uninstall --break-system-packages daedalus`, then `pipx install --force --editable .` (T-e27).
- **Found, not fixed:** doctor's `palace-dispatch-ignored` message says run hydrate, but only init writes that
  negation (TUI agent B).

## Night shift (2026-10-14/15): what happened
- **Edict 0011 built: PR #52, open, not merged.** Read its "judgment calls" before merging. Momus reviewed the
  build and verified the fixes (trial `.daedalus/momus/trials/2026-10-15-edict-0011-build.md`, local).
- **Neither source has run live.** Both say `unverified` in `daedalus source status`. ADO is yours on the work
  machine: start with `daedalus source sync ado --dry-run`. GitHub: try it here with `--dry-run` first.
- **New core dependency:** `keyring`. Reinstall after merging (`pip install -e .`).
- **This repo's roadmap index becomes committable** with #52; the local program-map item isn't committed yet.
- **The dream** is `docs/dreams/2026-10-15.md` on branch `docs/dream-2026-10-15` (pushed, no PR).
- Found: Ariadne's Tracker writes `roadmap/index.json` as a bare list (tolerated, not fixed).

## Night shift brief (2026-10-14/15): edict 0011, then a dream
- **Work:** workstream `sources`, phase p9-sources, tasks T-s1 to T-s8. Run
  `daedalus gameplan --workstream sources show`. The edict is 0011 as amended. Momus's readiness
  review that shaped it is in `.daedalus/momus/trials/2026-10-14-edicts-0011-0012-readiness.md`
  on Kohl's machine only.
- **Boundaries:** worktree on `feat/0011-sources`. Tests never touch live services. No pushing to
  main, no edits to edicts, no live sync. Where the edict is unclear, write a dissent or a PR note
  and skip that part.
- **The dream (T-s8), at Kohl's request:** after the PR, write `docs/dreams/2026-10-15.md`, open-ended
  speculation on where Daedalus could go.
  - *Generate before judging.* Write wide first: thirty-plus ideas, from small to absurd, one or two
    lines each, without stopping to check feasibility or hedging each one. Then a second pass picks
    the three to five you would most want to build, and says what would make each one real.
  - *It is not a proposal.* Ideas may cut against current edicts. Nothing goes into the gameplan
    or roadmap, and Momus doesn't review it. Label the file speculative at the top.
  - *Material, if wanted:* the gaps in `docs/design/tui/coverage.md`; what the build taught you; the
    aspirations idea in edict 0010 (entropy, not evidence); Kohl's "text is all you need" thesis
    in `~/ophanic/doc/`.
  - *Why:* Kohl finds full generative speculation hard to get out of Claude, and hopes Daedalus
    can help with that. This is a first try at giving it a protected slot.

## TUI design session (2026-10-14)
- **Edicts 0011 (sources and roadmap intake) and 0012 (the TUI)** are accepted and tracked as p9-sources
  and p8-tui. The design, coverage tracking and glossary are in `docs/design/tui/`. Build 0011 first.
- **Goal Kohl set for the TUI:** make Daedalus usable by someone who wasn't there. Read the design
  README's rules before building.
- **Roadmap as intake** is new to how we work. The roadmap index becomes committed under 0011.
- **The Claude pane's session backend is deliberately open** (past tmux trouble). Compare the options
  before picking one.
- **Open:** whether `ctrl+]` is free in Claude Code; whether to make Ophanic part of Daedalus (noted in
  p8-tui, with evidence in the README's dogfooding log).
- **Ophanic diagrams** were generated by a script kept only in the session scratchpad. Hand-edit the
  `.oph` files from here, keeping every row the same width.
- **The design branch `docs/tui-design` is merged.** Lazygit left a redundant autostash; its content is
  identical to main.

## Ariadne session (2026-10-13/14)
- **Released 0.2.0** to PyPI and GitHub (PR #35, tag v0.2.0). Verified by a fresh install from PyPI.
  It shipped the palace query CLI (T-e18, PR #33), the real Icarus identity again (T-e13, PR #34),
  and generic shipped agents (the test-runner had a hard-coded Cass Vessel home path). #14 is a known
  issue.
- **Experiment finished; report written and reviewed by Momus twice** (experiments/ariadne-local/REPORT.md on the
  local branch exp/ariadne-local, worktree ../daedalus-exp, not pushed). The design's outcome class: **negative** (H1 fails).
  - The gate helps (single-file precision ~80% ungated, 94-97% with verifier + judge), mostly by stopping the weaker
    workers. **Withdrawn:** the earlier "0 bad of 121" headline. The oracle didn't check that existing tests survived;
    counting deleted tests, 4-7 bad diffs landed.
  - H2 not met: on real bad diffs, once deleted tests count, both judges approve ~40-47%.
  - H4: no detectable effect of the Icarus identity (97/126 correct both ways).
  - qwen3:8b can't build multi-file features (toy 1/45, greenfield 0/12, this repo 1 clean in 54); Claude alone 3/3.
    No larger local worker tried yet.
  - Colliding pairs: 16/16 detected conflicts escalate on main (fb00f36); before #28, 11 of 13 were stopped only by git.
  - Product finding not on main: nothing flags a diff that deletes existing tests (no model needed to check).
- **Found and logged** (gameplan): T-e8, T-e10, T-e11 (CLI-loop direction), T-e12 (test backlog),
  T-e13 and T-e14 (both fixed), T-e15 to T-e18. Claude baselines are staged for 2026-10-23, at Kohl's
  budget call (experiments/ariadne-local/mature/RUNBOOK.md, greenfield/RUNBOOK.md).
- **Next:** the open checks in REPORT.md (re-verify rejected plan packages against their wave-time base; a 30B
  local worker on features; the two breaking runs on main); then the one-page system map and the video storyboard.

## Last session
- Built and merged edicts 0005, 0001 (as amended: an approved plan is approved
  intent), 0003, 0002 and 0008 (PRs #23-#26, merged as 915d65d). Each was
  reviewed by Momus before merge; its findings were fixed with tests.
- PR #28 (open): Ariadne recorded no escalated conflicts, so incompatible diffs
  could merge (T-e14, found by the Ariadne session).
- Edict 0009 reshaped from a mailbox into an agent message board, at Kohl's
  request. It is the next build.
- Two sessions worked in parallel (Ariadne and memory) and coordinated over
  Claude Code's cross-session messages; edict 0008 now models that.

## Open dissents
None.

## Notes
- Guardrail: never run live model calls (workers, judge, the live tier) on an
  employer's account or machine. The hermetic tier needs no model.
- Untested in 0007: Windows paths and console encoding.
