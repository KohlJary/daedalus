# Edict 0006: Memory reconstruction
Status: accepted
Depends on: Edict 0007 (memory backbone: `doctor`, pending proposals)

## Intent
0007 makes memory drift visible. This edict recovers what was lost. When the
gameplan has fallen behind the code, Daedalus rebuilds the missing period from
the evidence (commits, release notes, analyses, roadmap changes) as proposed
gameplan entries, has Momus check them, and hands them to a human to apply.

The first run, by hand on wonderland-ai on 2026-10-13, rebuilt 36 days and 95
commits that were missing from the gameplan as 5 phases and 24 tasks. It also
found that a task left `in_progress` since May (T-a1, milestone deletion) was
probably fixed in June under a different name, and that four shipped roadmap
items were still marked `backlog`.

Memory tools remember what they are told. This one recovers what nobody wrote
down, and says which parts it can prove.

0007's non-goal "no model-written resolutions" is lifted here, and only here:
model-written content is always a proposal, always cites evidence, and is
always checked by Momus before anyone sees it.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and
committed to `main` directly at his instruction.

## Constraints
- Reconstruction runs inside a Claude Code session, on request (a command and
  agent), never from a hook. 0007's rule that hooks make no model calls stands.
- `daedalus reconstruct gather` is deterministic and makes no model calls. It
  finds the gap (last gameplan commit to HEAD) and writes an evidence bundle:
  commits with subjects and bodies, release commits, files added under docs and
  analyses, roadmap diffs, and the current gameplan's open tasks.
- `gather` scores each commit message's evidence value deterministically, using
  signals such as: has a body, body length, references task, issue, or edict
  IDs, a specific subject (not "fix", "wip", "updates"), and message size
  relative to diff size. For commits below the threshold, the bundle includes
  the diff: the stat, plus a patch capped at a configurable size. A sample of
  high-scoring commits also gets diffs, so the score is checked against
  reality. Thresholds, caps, and the sample size live in config.
- Paths outside git that hold run evidence (e.g. gitignored run logs) can be
  listed in config. `gather` includes their file listings and timestamps, and
  the proposal says when it had git evidence only.
- A reconstruction agent (`mnemosyne`) turns the bundle into a proposal in the
  gameplan schema:
  - status changes to existing tasks
  - new phases and tasks
  - roadmap items whose status disagrees with the evidence
- Every resolution in a proposal cites commit hashes. Every proposed entry
  carries a confidence label (`shown`, `inferred`, or `unknown`), and says
  whether it rests on messages, diffs, or both. Every number cites the file it
  came from. Phase names not found in the evidence are marked as inferred. An
  outcome the record doesn't show is recorded as `unknown`, never guessed.
  Where sources disagree, both are recorded and neither is chosen.
- An existing task is proposed as `done` only on `shown` evidence. Anything
  weaker is proposed as "needs confirmation", along with the cheapest check
  that would settle it.
- Roadmap drift is checked item by item: every open roadmap item is compared
  against the commits in the window, not just the ones the agent happens to
  notice.
- Momus reviews every proposal before it is presented, and writes per-entry
  verdicts next to it. Entries Momus marks `contradicted` are dropped or
  corrected before presentation.
- Proposals are applied only through 0007's pending mechanism. Nothing writes
  to the gameplan or roadmap directly.

## Acceptance criteria
- `daedalus reconstruct gather` produces the evidence bundle and exits cleanly
  with "no gap" when the gameplan is current. Tested on a fixture repo.
- `daedalus reconstruct check <proposal>` deterministically confirms that every
  cited hash exists, falls inside the gap window (or is named as pre-window
  context), that every entry has a confidence label, and that every file the
  proposal references exists. It reports coverage: the commits in the window
  that no entry cites, by hash. It exits non-zero on any failure. Tested with
  fabricated and out-of-window hashes and a missing referenced file.
- Commit scoring is tested on a fixture repo that mixes rich and bare messages.
  Bare commits ("fix stuff") get diffs in the bundle; rich ones don't, except
  for the sample.
- `daedalus gameplan pending import <proposal>` loads the proposal as pending
  items, and 0007's `apply` / `drop` resolve them one at a time.
- The `mnemosyne` agent and a `/reconstruct` command ship with the plugin.
  The command runs gather, the agent, check, and Momus in order, and ends by
  showing the proposal with its verdicts.
- When `doctor` (0007) reports commits after the gameplan's last update, it
  suggests `/reconstruct`.
- The wonderland-ai reconstruction from 2026-10-13 is kept as a reference
  example in `docs/examples/wonderland-reconstruction/` (Kohl approved
  2026-10-13).
- The approach is run once on a repo with sparse commit messages, and its
  shown/inferred/unknown split is reported next to wonderland-ai's.

## Lessons from the first run
Momus's review of the hand-run wonderland-ai reconstruction shaped the rules
above:
- Every cited hash was real and correctly attributed. The errors were
  elsewhere:
  - a percentage misquoted (52% vs 53%, and projected, not measured)
  - a number attributed to the wrong file
  - one of two conflicting commit messages taken as fact
  - a pilot declared silent when 53 runs (~$188) sat in gitignored files
  - a reference to a report that didn't exist
- The roadmap drift list caught 4 items. Momus found many more candidates by
  checking item by item.
- 23 of 95 commits were cited by no entry, and nothing flagged it.
- The headline inference (T-a1) was proposed as `done`. Momus rated it
  "consistent, strongly", and running the fix's regression test against the
  older code made the case far stronger. Even so, it was not shown.

## Non-goals
- No automatic application, including of entries Momus marks `shown`.
- No reconstruction of free-form memory (session summaries, lessons). The
  gameplan and roadmap only.
- No running on a schedule or in the background.
