# Harness ledger

Daedalus runs inside Claude Code: as a plugin, a CLI, hooks, skills and subagents. Claude Code
owns the loop, the context window and the session. Most of the time that's the right trade: we
get a mature harness for free and build only what's ours.

Some things can't be done from inside, though. This ledger records each one when we hit it, so
the question "should Daedalus run its own harness?" gets answered by a count, not a mood.

## When to build

*Kohl's to set.* The draft below is Daedalus's suggestion, not a decision.

> Build an own harness when the limits below block the acceptance criteria of **two or more
> accepted edicts**, or when one limit blocks something Kohl calls central (for example, the
> context map's live editing).

Until then, each entry names its workaround (or says there is none), and the workaround is what ships.

## Entries

Each entry: date, what was blocked, the workaround in use (or none), what an own harness would
allow, the edicts it affects, and sources for any claim about Claude Code.

### 1. No surgical editing of the live context
- **Date:** 2026-10-15
- **Blocked:** Removing, summarizing or pinning one part of the context mid-session (one task's
  tool output, one finished topic). Compaction is all or nothing.
- **Workaround:** Edict 0015. Measure the context per subject and per task, record what must
  survive, then steer a full compaction with instructions built from a keep/summarize/drop plan.
- **Own harness would allow:** Per-segment controls on the live window (drop, summarize in place,
  pin), because the loop that assembles each request would be Daedalus's own.
- **Edicts:** 0015 (and 0014's context section).

### 2. Usage and context figures reach only the status line
- **Date:** 2026-10-15
- **Blocked:** The model can't see the 5-hour and weekly usage or the context percentage directly.
- **Workaround:** Edict 0014, which is proposed and not yet built. The status line command would
  record them to a file, and a hook would read them back into context. (Edict 0015 gets the
  context size exactly from the transcript instead, so only usage still needs the status line.)
- **Own harness would allow:** Budget and context state as first-class inputs to the loop.
- **Edicts:** 0014.

### 3. Chat sessions can't message Claude Code sessions
- **Date:** 2026-10-14
- **Blocked:** Handing a design from claude.ai chat to the Code session that builds it, and
  getting the builder's objections back, without Kohl copying text between them.
- **Workaround:** Kohl relays by hand. Filed as anthropics/claude-code #102202 (bug) and #102203
  (feature request).
- **Own harness would allow:** One session protocol for chat and code, with the edict handoff
  built in.
- **Edicts:** none yet (affects the edict workflow itself).

### 4. No instructions for automatic compactions
- **Date:** 2026-10-15
- **Blocked:** Telling an automatic compaction what to keep. A PreCompact hook receives
  `custom_instructions` only for a manual `/compact`; for `auto` it is null. Its documented output
  is only a block, and Claude Code discards its `systemMessage` and `continue` fields.
- **Workaround:** Partial (edict 0015). PreCompact saves the plan. After the compaction, the
  SessionStart hook puts back the kept identifiers the summary lost, and names the recall command
  for dropped parts. The nudges aim to make manual, planned compactions the norm.
- **Own harness would allow:** Daedalus would write the compaction itself, from the plan.
- **Edicts:** 0015.
- **Source:** code.claude.com/docs/en/hooks, PreCompact section, read 2026-10-15 (Momus trial
  `.daedalus/momus/trials/2026-10-15-edict-0015-readiness.md`). Whether PreCompact accepts
  `additionalContext` wasn't read word for word; it's treated as no.
