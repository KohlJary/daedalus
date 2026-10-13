# Edict 0004: Memory backbone
Status: accepted

## Intent
Make the gameplan the backbone of Daedalus's memory, and make memory drift
visible instead of silent.

Across three projects, Daedalus's memory went stale exactly when work was
busiest. In cass-vessel, session summaries have a 53-day gap (2025-12-19 to
2026-02-11) covering 70 commits, and the roadmap is empty but still queried at
every session start. In wonderland-ai the gameplan was used heavily (27 phases,
detailed task resolutions) but stopped being updated on 2026-05-18 while work
continued to 2026-06-23, and `session-summaries.md` was never written at all.

What does get written is structured memory tied to a task: a gameplan
resolution is recorded as part of finishing the task. Free-form memory is a
separate chore, and it gets skipped. So the gameplan carries the memory,
tooling catches it when it falls behind, and the free-form files become
optional.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and
committed to `main` directly at his instruction.

## Constraints
- Everything stays plain files in the repo. No database or service.
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
  - `docs/status.md` naming an edict status that disagrees with the edict file
  - top-level source packages absent from `project-map.md`, when that file exists
  - memory files that are empty templates but still read by a hook
  It exits non-zero when it finds anything, so it can run in CI.
- Tests run `doctor` against fixtures modelled on the wonderland-ai and
  cass-vessel `.daedalus/` states, and each finding above fires on its fixture.
- The session-start hook leads with the active phase's goal, the next
  pending task, and the head of `docs/status.md`, followed by any `doctor`
  findings in one line each. It reads the roadmap from `.daedalus/roadmap/`
  (today it reads `data/roadmap/index.json`, a cass-vessel path) and prints
  nothing for an empty roadmap. Output stays under 40 lines.
- A `SessionEnd`/`PreCompact` hook matches commits since the last gameplan
  update against active-phase tasks (by task ID or title in the commit message)
  and writes proposed status changes to a pending file. `daedalus gameplan
  pending` lists them, and `apply` / `drop` resolve them.
- `daedalus init` no longer creates empty `warnings.md`, `lessons.md`, or
  `observations.json`. The memory agent and hooks treat missing files as normal.
- The README presents the gameplan and the committed `docs/status.md` as the
  core, and says plainly how this differs from Claude Code's built-in per-user
  memory: it is committed, shared, and structured around tasks.

## Non-goals
- No model-written resolutions or summaries. Drafting prose with a model is a
  later edict, once the deterministic version has been used for a while.
- No automatic writes to the gameplan, status, or edicts.
- No migration of existing session summaries into the gameplan.
- No Theseus report indexing (gameplan phase p3) or resume benchmark (p4).
