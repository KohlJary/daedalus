# Experiment: reflection over session logs

**Status:** built (PR #39), no real run yet
**Spec:** [edict 0010](../edicts/0010-reflection.md)
**Machine:** home machine. Digests and models never leave it; this page and the exported log
are what is shared. Export with `daedalus reflect log export docs/experiments/reflection-runs.jsonl`
(counts and IDs only) after a run worth recording.

## The question

Can Daedalus learn from the record of its own sessions? Concretely: when reflection points at a
pattern (a failure that recurs, a correction that repeats) and the user applies a fix, does the
pattern actually go away? And do the user and self models, built from evidence and changed by
evidence, come to say something true and useful, or just restate tool habits?

This is an unusual feature. It is kept as an experiment from the first day, so that whether it
worked can be judged from the record rather than from memory.

## What working would look like (draft; the benchmark is still to be designed)

From the design conversation with Kohl on 2026-10-14:

1. **Targeted fixes work.** Every applied proposal names the pattern it targets. Its rate falls
   after the fix, more than untargeted patterns move. This is the core test.
2. **The same correction doesn't come twice.** User corrections on something a note or model
   entry already covers become rarer.
3. **Proposals are good.** More applied than dropped; few contradicted by Momus; few reverted.
4. **The models are accurate.** Monthly, Kohl rates a sample of entries: accurate, wrong, stale.
5. **It pays for itself.** Tokens spent on reflection against tokens saved on targeted patterns.
6. **Aspirations move something.** Behavior moves toward some aspirations; answers change
   across months and models instead of repeating.

What would show it isn't working: after 4-6 weeks, targeted patterns haven't dropped more than
untargeted ones, and repeat corrections haven't fallen. The model-summary A/B test needs many
sessions per arm before it says anything; with one user it may take months.

## Baseline

Claude Code's cleanup ran on 2026-10-13, so the record starts late: these are the digests of
this repository's four sessions before any reflection ran (digested 2026-10-14).

| Session | Span (UTC) | Tool calls | Output tokens | Cache hit | Failures | Classifier denials | Approved at prompt | Background agents | Their tokens |
|---|---|---|---|---|---|---|---|---|---|
| 5e51440f | 10-13 21:35 to 10-14 23:41 | 572 | 869,381 | 0.994 | 8 | 2 | 5 | 14 | 1,201,030 |
| 7dbd1b09 | 10-13 21:29 to 10-14 23:40 | 404 | 561,489 | 0.994 | 21 | 0 | 1 | 11 | 567,505 |
| ae032057 | 10-14 22:49 to 23:42 | 101 | 104,077 | 0.988 | 2 | 2 | 1 | 0 | 0 |
| ba9e3abe | 10-14 21:50 to 23:42 | 212 | 283,201 | 0.992 | 2 | 1 | 0 | 4 | 364,687 |

Most of 7dbd1b09's failures are non-zero exits from probing commands, not breakage (dry run 1).
Sessions span more than a day because they were resumed; a session is dated by its end.

## Log

Newest last. Each entry: what ran, what it cost, what it found, and what changed because of it.
Runs from `daedalus reflect done` also land in the exported log.

### 2026-10-14: Fixture capture

Kohl drove a scratch session to produce the events no existing transcript had: a tool call
rejected at a prompt, an interrupt mid-reply, and interrupts before the reply began. Learned:

- An interrupt before streaming starts leaves no marker at all; only the missing reply shows it.
- A rejection writes the rejected result, then `[Request interrupted by user for tool use]`.
- Interrupting a running tool couldn't be captured: foreground `sleep` is blocked and long
  commands are backgrounded. It stays a recorded gap.
- Subagent transcripts record placeholder output tokens; the real totals arrive in the parent's
  completion notices. Read from the transcripts alone, 13 background agents in one session came
  to 2,516 output tokens; their notices reported 991,435 tokens in all.

### 2026-10-14: Dry run 1 (weekly 2026-W42, not a due run)

- **Ran:** delphi as an agent (claude-sonnet-5-5) on this repo's four digests; 73,410 tokens.
  Not reviewed by Momus, not imported: a test of the instructions, not a reflection.
- **Check:** passed on the second try. The first caught a retry cited as a failure.
- **Found:** 9 findings. Writes attempted without a fresh read in two sessions; most Bash
  failures being probes; long sleeps blocked by the harness; two classifier denials, one an edit
  to its own permission settings; background agents carrying a large share of the work; cache
  hit rates of 0.98-0.99; no user rejections or interruptions recorded.
- **Proposed:** 3. A CLAUDE.md note on long waits (inferred), and two self-model behaviors: "I
  write to files I haven't read" and "I hand a large share of the work to background agents"
  (shown).
- **Changed because of it:** digests gained per-event `details` and the `approved_at_prompt`
  count; the running session is left out of its own bundle; evidence shapes are validated;
  delphi's instructions spell out figures, citation types, self entries and the first run.

### 2026-10-14: Momus's review of the build

- **Ran:** Momus (claude-opus-5-5) against every acceptance criterion; 197,174 tokens.
- **Found:** 13 defects. The five that mattered most: a seed could cite a made-up quote and skip
  the user model's rules; file proposals could reach the identity files and settings; the report
  was rendered before his verdicts; `apply all` wasn't atomic and reports could requeue applied
  proposals; a stance could be revised in a batch.
- **Changed because of it:** all 13 fixed with tests (PR #39, commit "fixes from Momus's review").
