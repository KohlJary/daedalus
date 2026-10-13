# Edict 0007: Memory backbone
Status: accepted
Depends on: Edict 0004 (exhale and inhale as plugin skills)

## Intent
Make the gameplan the center of Daedalus's memory, and make memory drift
visible instead of silent.

Across three projects, Daedalus's memory went stale exactly when work was
busiest. In cass-vessel, session summaries have a 53-day gap (2025-12-19 to
2026-02-11) covering 70 commits, and the roadmap is empty but still queried at
every session start. In wonderland-ai the gameplan was used heavily (27 phases,
detailed task resolutions) but stopped being updated on 2026-05-18 while work
continued to 2026-06-23, and `session-summaries.md` was never written at all.

What does get written is structured memory tied to a task: a gameplan
resolution is recorded as part of finishing the task. Free-form memory is a
separate chore, and it gets skipped. So the gameplan is the record of state,
tooling catches it when it falls behind, and free-form notes are narrative
around it rather than the source of truth.

The gameplan is also what crosses the boundary from Claude Code back to Claude
in chat. Designs travel chat → code as edicts; progress travels code → chat
through the gameplan. That only works if the gameplan is committed. Each fact
lives in one place: an edict says what to build and why; the gameplan says
what has been built.

0004's exhale and inhale skills are the rituals; this edict gives them a
center (the gameplan), an always-on entry point (the session-start hook), a
drift check (`doctor`), and a safety net for sessions that end without
exhaling.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and
committed to `main` directly at his instruction.

## Constraints
- Everything stays plain files in the repo. No database or service.
- `.daedalus/roadmap/gameplan.json` is tracked in git. `daedalus init` makes
  sure it is not ignored, even if the rest of `.daedalus/` is.
- Phases and tasks may carry an optional `edict` field (e.g. `"0007"`). Whether
  an edict has been built is recorded only in the gameplan, never in the edict
  file or in `docs/status.md`.
- The gameplan is the record of state. Session summaries (written by 0004's
  exhale) and `docs/status.md` are narrative: what happened, why, and what the
  gameplan can't say. They do not duplicate phases, tasks, or edict progress,
  and `doctor` never flags a missing summary.
- Hooks are deterministic and make no model calls. They must be cheap, testable,
  and safe to run on any machine.
- Hooks never edit the gameplan, `docs/status.md`, or edicts directly. They only
  propose changes, and a human or a session applies them.
- Projects that never adopt the gameplan keep working. Every check and hook
  degrades to a no-op or a single hint line.
- Thresholds (e.g. how many days counts as stale) live in config with defaults,
  and are not hard-coded.

## Acceptance criteria
- `daedalus doctor` exists and reports, each as a separate named finding:
  - commits on the current branch made after the gameplan's last update
  - an active phase still `in_progress` whose tasks are all `done`
  - tasks `in_progress` for longer than the configured threshold
  - edicts whose `Status:` line is not one of `proposed | accepted | done`
  - two edict files with the same number
  - accepted edicts that no gameplan phase or task references (only when
    edicts are enabled, see 0005)
  - the gameplan file being ignored by git
  - top-level source packages absent from `project-map.md`, when that file exists
  - memory files that are empty templates but still read by a hook
  It exits non-zero when it finds anything, so it can run in CI.
- Tests run `doctor` against fixtures modelled on the wonderland-ai and
  cass-vessel `.daedalus/` states, and each finding above fires on its fixture.
- `gameplan phase add` and `gameplan task add` accept `--edict <id>`, and
  `gameplan show` displays it.
- The session-start hook is wired. `daedalus init` and `hydrate` register it as
  a `SessionStart` hook in the project's `.claude/settings.json` (merging with
  existing settings, never clobbering them), `--no-hooks` skips it, and
  `hydrate --dry-run` lists it.
- The session-start hook leads with the active phase's goal, the next pending
  task, and any `doctor` findings in one line each, then the latest session
  note. It reads the roadmap from `.daedalus/roadmap/` (today it reads
  `data/roadmap/index.json`, a cass-vessel path) and prints nothing for an
  empty roadmap. Output stays under 40 lines. It points to `/inhale` for the
  full pickup.
- Inhale (0004) reads the gameplan first and treats `doctor` findings as the
  test of whether the last session exhaled. Exhale (0004) records gameplan
  task status and resolutions before writing its session summary, and the
  summary refers to tasks by ID rather than restating them.
- A capture hook (`SessionEnd` and `PreCompact`), off by default
  (`hooks.capture`), matches commits since the last gameplan update against
  active-phase tasks (by task ID or title in the commit message) and writes
  proposed status changes to a pending file. `daedalus gameplan pending` lists
  them, and `apply` / `drop` resolve them. It is the safety net for sessions
  that end without exhaling; it does not run exhale.
- `daedalus init` no longer creates empty `warnings.md`, `lessons.md`, or
  `observations.json`. The memory agent and hooks treat missing files as normal.
- The CLAUDE.md template and `docs/edicts/README.md` describe the split: edicts
  carry designs, the gameplan carries progress, summaries and `status.md`
  carry narrative.
- The README presents the gameplan as the core, and says plainly how this
  differs from Claude Code's built-in per-user memory: it is committed,
  shared, and structured around tasks.

## Non-goals
- No model-written resolutions or summaries in hooks. Model-drafted
  reconstruction is 0006, run on request.
- No automatic writes to the gameplan, status, or edicts.
- No automatic conversion of edicts into gameplan phases. Claude Code does that
  by hand; `doctor` only flags edicts that nothing references.
- No migration of existing session summaries into the gameplan.
- No Theseus report indexing (gameplan phase p3) or resume benchmark (p4).

## Amendments
- 2026-10-13, requested by Kohl: the gameplan is committed, and tracking
  whether an edict is built lives only there (`edict` field on phases and
  tasks). `status.md` shrinks to a session note. `doctor` gains checks for
  accepted edicts that nothing references and for an ignored gameplan file,
  and drops the `status.md`-vs-edict check. Why: the edict file, a gameplan
  task, and a `status.md` table were all tracking the same thing ("hat on a
  hat"), and the gameplan being gitignored was the reason `status.md` had to
  duplicate it for chat.
- 2026-10-13, requested by Kohl: renumbered from 0004 to 0007. Another session
  had already merged and built a different 0004 (exhale and inhale skills).
  Rebuilt on top of it:
  - The gameplan is at the center, and exhale's summaries are narrative.
  - The session-start hook is wired by `init`/`hydrate` rather than retired.
    0004 said inhale supersedes it, and 0004 is amended to match.
  - The capture hook stays but is off by default, as a safety net rather than
    a replacement for exhale. Kohl was unsure about it.
  - `doctor` flags duplicate edict numbers, which is how this collision went
    unnoticed.
