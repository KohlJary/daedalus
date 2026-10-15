# Edict 0015: The context map
Status: accepted
Depends on: Edict 0007 (hooks registered by init and hydrate; hooks make no model calls); Edict
0010 (the transcript parser in `reflection/digest.py`)

*Drafted by Daedalus at Kohl's request in conversation on 2026-10-15. Momus reviewed the first
draft (`.daedalus/momus/trials/2026-10-15-edict-0015-readiness.md`), and this text folds in its
findings. Kohl accepted it on 2026-10-15. Before the PR merged, it was aligned with Edict 0016 (the shared
hook kit; Stop never prints), following 0016's readiness review, and given library functions for
the TUI.*

## Intent
Today the context window is one undifferentiated block. Daedalus can't see what fills it, and
compaction summarizes all of it at once: the task in flight gets the same treatment as a test
run from two hours ago. Compaction also tends to happen late and all at once, when the window is
nearly full, rather than at a natural pause.

Kohl's goals, in their words: "compacting more often, harmoniously, through better tracking of
our context state and selective operation, and getting better compaction notes/more efficient
discarding of what's actually totally out of context, ideally without giving you amnesia." In
practice:
- **More often, at natural points.** Compact when a lot of the context is finished and recorded,
  not only when it is nearly full.
- **Better notes.** Each compaction is told what to keep, by name.
- **Discard what's truly done.** Drop only parts that are quiet and recorded elsewhere.
- **No amnesia.** Dropping something from the context never destroys it. The transcript is
  append-only and keeps everything, reflection (0010) still reads all of it, and a dropped part
  can be recalled on demand.

This edict gives Daedalus four things, and **all of them run from hooks**, so they happen without
anyone remembering to ask.

1. **A map.** It shows how big the context is, and how much of it belongs to each subject and each
   task. It is measured from the session's own token counts, not guessed.
2. **A plan.** Before the context fills, the map says what to keep, what to summarize, and what
   to record somewhere durable so it can safely be let go.
3. **Recovery.** After a compaction, Daedalus puts back what the plan said to keep and the
   summary lost.
4. **Recall.** A dropped part can be read back from the transcript on demand, in brief.

A prototype run on one conversation-heavy session (N=1) shows why the map matters. At 126k tokens,
52% of the context was the base: everything present at the first request after the last
compaction. At 146k tokens it was 45%. Tool results were about 12%. Daedalus's own output,
including thinking resent in full but barely visible in the transcript, was about two-thirds of the
growth since that compaction. Those proportions will differ by session, and the map exists to show
them.

Claude Code owns the context window, and two things can't be done from inside it:
- removing one segment from the live context;
- adding instructions to an automatic compaction. The hooks docs say PreCompact receives
  `custom_instructions` as null for automatic compactions, and its documented output is only a
  block.

Both go into a ledger, `docs/harness-ledger.md`, of what a Daedalus-owned harness would make
possible. This edict does not build that harness.

## Constraints

### Hooks first
The map, the nudges and the recovery come from hooks. The CLI commands are the engine and a way
to look by hand; nothing depends on anyone running them.

| Event | Command | Does |
|---|---|---|
| PostToolUse | the context feature | Extends the map's index from the transcript's new bytes. Prints nothing unless a threshold is crossed (below). |
| Stop | the context feature | Extends the index. **Never prints:** any Stop output continues the turn and costs a full extra one. |
| PreCompact | the context feature | Saves the plan for this boundary. No output: the docs give PreCompact no way to add instructions. |
| SessionStart (source `compact`) | the context feature | Runs the check against the saved plan and puts back what the summary lost (below). |

- **It runs on Edict 0016's hook kit.** The context hook is a feature of the kit's dispatchers,
  under the config key `hooks.context` (default true). 0016 owns registration, the standard-library
  kit and the shared noise budget. Whichever of the two edicts is built first builds the kit as 0016
  specifies. The hook path imports only the standard library, and on a warm index it finishes in
  under 100 ms.
- **Cold start.** If there's no index yet and the transcript is over `context.cold_limit_mb`
  (default 5), the hook indexes in slices of that size, one per call, and stays silent until it
  has caught up. It never blocks a turn on a full parse.
- **Fail soft.** On any error the hook prints nothing and exits 0.
- **The prompt cache is safe.** Hook output goes only where the docs put it, at the end of the
  context: PostToolUse `additionalContext`, or SessionStart output after a
  compaction, when the cache is rebuilt anyway. Nothing is written into files read at session
  start. This is the same rule as 0014.
- **A noise budget.** The PostToolUse path speaks at most once per `context.nudge_minutes`
  (default 20), and only when what it would say has changed. Its lines also count against 0016's
  `hooks.budget_per_hour`. Each line stays under 300 characters, in a fixed format.

### Measuring
- **The context size is exact.** Every main-thread assistant entry carries its request's `usage`.
  The context at a request is `input_tokens + cache_read_input_tokens +
  cache_creation_input_tokens`. It is counted once per `requestId`: a request's entries share one
  usage.
- **Growth is attributed in two parts.** Between two consecutive requests:
  1. **Daedalus's output, exactly.** The previous request's `output_tokens` go to an `output`
     line (text, tool calls and thinking). Thinking is resent but barely visible in the transcript,
     so a size split would spread it over everything else.
  2. **The rest, split by size.** The remainder is split among the other entries added in the
     step, by serialized size.

  Where growth is less than `output_tokens` (a version that strips thinking), the whole step is
  split by size and marked `estimated`. Entries added after the last request are shown as
  `pending`, with a size estimate.
- **The base.** The first request after the last `compact_boundary` sets the base: everything
  present before any new work.
  - The base line is exact.
  - Its breakdown is an estimate. It uses `compactMetadata.postTokens` and the compaction summary
    when present, the identifiable injected files (each CLAUDE.md path, MEMORY.md) scaled by the
    session's measured ratio, and the rest as `system, tools and preserved messages`. Absent
    fields are skipped.
- **The ratio.** Wherever characters are converted to tokens, the session's own measured ratio is
  used, never a fixed 4.
- **Running totals reset at every `compact_boundary`.**
- **Subagents.** Their own traffic is in separate files (`<session>/subagents/`) and never enters
  the main context. What enters is:
  - the launch result (counted under `Agent: <type> (launch)`);
  - for asynchronous agents, the report, which arrives later as a task-notification message. It is
    matched to the launch by agent ID, typed from the subagent's `.meta.json` (`agentType`), and
    counted under `Agent: <type>`.

  Fixtures for this follow the real shape, as 0010 requires.
- **Reuse, not a second parser.** Transcript reading reuses `reflection/digest.py`: its
  `KNOWN_TYPES` and unknown-type counting, and its compaction and usage extraction. An
  offset-capable reader is added beside `iter_events`, which reads from byte 0. The per-session
  index stores the byte offset, the running totals and the first line's hash. A shrunk transcript,
  or a changed first line, resets it.

### Two views
- **By subject** (`daedalus context`, the default):
  - **Files read or edited:** by path relative to the project root, two directories deep. Paths
    outside the project are grouped as `outside: <first two components>`.
  - **Command output:** by command. A command line is split on `&&`, `||`, `;` and `|`. Segments
    that are only `cd <dir>` or variable assignments are dropped. The first word of the first
    remaining segment names it (`cd x && FOO=1 pytest -q` → `pytest`).
  - **Subagents:** by type, as above.
  - **Messages:** yours; system reminders and attachments.
  - **`output`** (Daedalus's text, tool calls and thinking), and everything else.
- **By task** (`--by task`). A **task marker** is a gameplan task ID (`T-...`) in your message, or
  in a Bash command line (commit messages and `daedalus gameplan task` commands). IDs in tool
  output and listings are not markers. A git branch change also starts a new segment. Each entry
  belongs to the latest marker or branch change before it. Entries before any belong to the
  branch, or else to `unassigned`.
- **What's gone quiet.** A subject or task is touched when an entry is added to it. Each line
  shows tokens, share, and the time since it was last touched. A footer gives the share untouched
  for `context.quiet_minutes` (default 60).
- **Output** shows the ten largest lines (`--all` for every line), or `--json`. Each number is
  labelled `exact`, `attributed` or `estimated`. The total is exact, and the lines sum to it
  within one token per line.
- **Library functions for the TUI (0012),** which calls functions and never parses CLI output:
  - `context.measure(project_dir, session_id) -> dict` returns `session_id`, `measured_at`,
    `window_tokens`, `used_tokens`, `measured` (true when exact), `by_subject` (each item has
    `key`, `subject`, `kind` (file, command, agent, conversation, output or other), `tokens`,
    `share` (0-1), `quiet`, `last_touched`), `by_task` (`key`, `task`, `tokens`, `share`, `quiet`),
    `plan` (`key`, `action`, `reason`) and `pins`.
  - `context.plan(...)`, `context.pin(project_dir, session_id, key)` and `unpin` are the same
    operations as the CLI.
  - Each subject and task has a stable `key`, so a pin set from the TUI survives later
    measurements.
  - `--json` prints the same dict.
  - The files the TUI should watch (the per-session index and saved plans under the cache
    directory) are listed in the README.

### The plan
- **Each task** (or each subject, with `--by subject`) gets one mark, checked in this order:
  1. `keep`: the task in play (the latest marker), an `in_progress` gameplan task, or anything
     pinned.
  2. `record first`: would be dropped, but its state isn't recorded. That means a task with no
     resolution, or a subject whose files have uncommitted changes in the repository containing
     them (found with `git -C <dir> status --porcelain`). The reason is given.
  3. `drop`: quiet longer than `context.quiet_minutes`, and recorded: a done task with a
     resolution, or a subject with no uncommitted changes.
  4. `summarize`: everything else.

  `keep` wins over `record first`. A kept task with no resolution is noted as such, but kept.
- **Pins.** `daedalus context pin <task-or-subject>` and `unpin` keep a part through every plan.
  Pins are stored per session.
- **The plan renders as compaction instructions:** plain text, at most 1,500 characters. Every
  `keep` identifier (paths, task IDs, PR numbers, commit hashes) is listed first. When the limit
  binds, the summarize and drop lines are shortened, then cut, never the identifiers. Then, if
  needed, the identifiers of the oldest kept parts are moved to a line that says how many were
  cut. `daedalus context plan --instructions` prints only that text, for a manual
  `/compact <instructions>`.
- **The plan is saved per boundary**: one per session and compaction, so a later plan never
  overwrites the one a check needs.

### Nudges: when to compact
The PostToolUse hook says one line, within the noise budget, in two cases.

1. **A natural breakpoint.** The context is past `context.breakpoint_percent` of the window
   (default 40), and the parts marked `drop` make up at least `context.drop_percent` of it
   (default 30). The usual cause is that a task has just been recorded as done and its material
   has gone quiet. This is the "compact more often" trigger: a lot of the context can be let go
   safely, so now is a good time.

   `context 52%: 34% is done and recorded (T-e22, pytest, momus) · good point to exhale and compact`

2. **Filling up.** The context is past `context.warn_percent` (default 70), whatever the plan
   says.

   `context 74% (exact): T-e24 41%, pytest 18% quiet 2h, output 22% · record first: T-e24 (no resolution)`

- **The window size** is taken from the model's known window. It can be overridden with
  `context.window_tokens`.
- **The nudge informs, and the session decides.** The exhale skill says what a clean stop is:
  1. record the `record first` parts;
  2. offer the owner `/compact` with the plan's instructions.
- **The hook never writes the gameplan, and never runs `/compact`.**

### Recovery after compaction
On SessionStart with source `compact`, the hook:
1. finds the newest compaction summary: the `isCompactSummary` entry after the last boundary, not
   necessarily adjacent;
2. reads the plan saved at that boundary;
3. lists the `keep` identifiers the summary lost;
4. prints one short block, at most 800 characters:
   `After compaction: the summary dropped PR #49, T-e24. Kept by the plan; their state is in: gameplan T-e24, branch feat/...`.
   It points to where the state lives rather than restating it.

This is how selective compaction works without control over the compactor: the plan decides what
matters, and recovery puts back what the summary lost. If nothing was lost, it prints nothing.

### Recall: dropping is not forgetting
- **The transcript is the archive.** Each saved plan records, for every part marked `drop` or
  `summarize`, the transcript's entry UUIDs that make it up.
- **`daedalus context recall <task-or-subject>`** prints a brief of that part from the
  transcript, at most `context.recall_chars` (default 4,000):
  - your messages and Daedalus's text, in order, each cut to its first lines;
  - tool calls as one line each (the command or path);
  - tool results as their first and last lines.

  It works for parts dropped in any earlier compaction of the session (`--boundary N` picks one;
  the default is the latest).
- **The recovery block names the command.** After a compaction it says, for example:
  `dropped: T-e22, pytest, momus · daedalus context recall <name> brings any back`.
  Daedalus knows what it let go and how to get it back.
- **Reflection is unaffected.** It reads whole transcripts and never sees compaction as a loss.

### CLI
`daedalus context` (both views), `context plan` (`--instructions`), `context pin` and `unpin`,
`context recall`, and `context check`: the recovery report for the latest boundary, by hand. All of
them read the same index as the hook.

### Cost and safety
- **No model calls and no network calls.**
- **Read-only on Claude Code's files.** Daedalus never edits or truncates a transcript.
- **The index and the plans** live under the cache directory, per session, written atomically.

### Relation to 0014
0014 is proposed and not yet amended. Its "Context usage" section has two parts:
- **"How full"**, from the status line: this edict measures it exactly from the transcript, so it
  no longer needs the status line.
- **"With what"**: this edict replaces it.

This edict doesn't change 0014's text. The PR asks Kohl to amend 0014 so its context section and
criteria (the chars/4 breakdown and the top three subjects in the clock line) point here. Until
then the two edicts overlap, and each is judged against its own text.

### The harness ledger
- **`docs/harness-ledger.md` records what building inside Claude Code can't do**, and what a
  Daedalus-owned harness would allow instead. Each entry gives:
  - the date;
  - what was blocked;
  - the workaround in use, or "none";
  - what an own harness would allow;
  - the edicts it affects;
  - sources for claims about Claude Code.
- **Daedalus adds an entry whenever building an edict runs into such a limit.**
- **The ledger's "When to build" section is Kohl's to set.** The ledger only keeps the count.

### Config
These keys register in the schema registry (0011), each with a description:
- `hooks.context`
- `context.warn_percent`, `context.breakpoint_percent` and `context.drop_percent`
- `context.quiet_minutes` and `context.nudge_minutes`
- `context.recall_chars`
- `context.window_tokens` and `context.cold_limit_mb`

## Acceptance criteria
- **Registration.** With `hooks.context` on, 0016's dispatchers for PostToolUse, Stop, PreCompact
  and SessionStart run the context feature. With it off, they don't, and nothing else changes. The
  Stop and PreCompact paths print nothing, even when a nudge would be due.
- **Library.** `context.measure` returns the dict above for a fixture. Its `key`s are stable
  across two measurements of a growing transcript. `context.pin` with a key keeps that part in
  every later plan.
- **Exact size.** On a fixture with `usage` on its assistant entries (several entries sharing a
  `requestId`), `daedalus context --json` reports the last request's context as the fixture's
  sum. The lines sum to it within one token per line.
- **Output attribution.** In a fixture step where the previous request's `output_tokens` is 1,200
  and the growth is 3,200, with a 9,000-character tool result and a 1,000-character message added,
  `output` gets 1,200, the tool result 1,800 and the message 200. With growth below
  `output_tokens`, the step is split by size and labelled `estimated`.
- **The ratio.** A fixture whose measured ratio is 3 converts estimates at 3, not 4.
- **Boundaries.** Entries before the last `compact_boundary` contribute nothing, and the totals
  reset there. The summary is found when it isn't adjacent to the boundary.
- **Subagents.** In a real-shape fixture (a launch stub, a later task-notification, and a
  subagents directory with `.meta.json`), the report counts under `Agent: <agentType>` and the
  launch under `(launch)`.
- **Subjects.**
  - Tests cover `cd x && FOO=1 pytest -q` → `pytest`, `a; b | c` → `a`, an absolute path inside
    the project, and a path outside it.
  - In a fixture mentioning `T-a1`, then switching branch, then mentioning `T-b2`, the entries
    after the switch and before `T-b2` belong to the branch segment.
  - A `T-` ID that appears only in a tool result changes nothing.
- **Quiet share.** With frozen timestamps, the footer counts exactly the lines untouched for
  `context.quiet_minutes`.
- **Incremental and cold.**
  - A second run reads only appended bytes, checked by the stored offset.
  - A rewritten first line resets the index.
  - With a 12 MB fixture and `cold_limit_mb` 5, the hook catches up over three calls, silent
    until done.
- **The plan.**
  - A done task with a resolution, quiet for 2 hours, is `drop`; without a resolution it is
    `record first`.
  - An `in_progress` task without a resolution is `keep`, and noted.
  - A pinned subject is `keep`.
  - With 40 keep identifiers, `--instructions` stays at or under 1,500 characters, every
    identifier that fits is present, and the cut line gives the count of the rest.
- **Plans per boundary.** After two compactions, each boundary's check uses its own saved plan.
- **The nudge.**
  - With frozen time and a fixture crossing 70%, the hook prints the line once.
  - Within `nudge_minutes` it prints nothing.
  - After that interval it prints again only if the line changed.
  - Under 70% it prints nothing.
  - Its output is valid PostToolUse JSON with `additionalContext`.
  - **Breakpoint.** At 45% with 35% marked `drop`, the breakpoint line prints. At 45% with 20%
    marked `drop`, nothing prints. At 35% with 35% marked `drop`, nothing prints.
- **Recall.** After a fixture compaction that dropped `T-a1`:
  - `daedalus context recall T-a1` prints that part's messages and calls, in order, within
    `recall_chars`, and nothing from other parts.
  - `--boundary` picks an earlier compaction's plan.
  - The recovery block lists the dropped parts and names the recall command.
- **Recovery.** Given a saved plan and a fixture summary missing one kept PR number, the
  SessionStart path prints a block naming that number and where its state lives. If nothing is
  missing, it prints nothing. The block stays at or under 800 characters.
- **The hook module.**
  - Importing it imports only the standard library and its own module: a test checks
    `sys.modules`.
  - A timing test runs it under 100 ms over 20 warm runs, and skips with a message on slow CI.
  - With an unreadable cache directory, it prints nothing and exits 0.
- **No model, no network, read-only.** A test blocks sockets and confirms that the transcript's
  modification time and size are unchanged after a run.
- **Exhale.** The exhale skill's steps run the plan, record the `record first` parts, and offer
  `/compact` with the instructions. This is reviewed by reading the skill. It is not a test.
- **Ledger.** `docs/harness-ledger.md` has the entry format above, the surgical-removal entry and
  the PreCompact entry (with its source), and a "When to build" section marked as Kohl's.
- **Docs.** The README documents the hooks, the commands, and which numbers are exact, attributed
  or estimated.

## Non-goals
- **No editing of the live context.** Nothing is removed, reordered or rewritten mid-session. The
  ledger tracks that.
- **No model-written summaries.** Claude Code's compaction still writes the summary.
- **No automatic compaction.** The hook never runs `/compact`.
- **No semantic topic detection.** Tasks come from markers and branches. Smarter segmentation
  comes later, if this proves too coarse.
- **No changes to what Claude Code injects.** If the base turns out to be mostly duplicated
  CLAUDE.md text, fixing that is separate work, and the map is how we'd find out.
