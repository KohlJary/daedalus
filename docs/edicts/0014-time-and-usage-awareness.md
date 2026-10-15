# Edict 0014: Time and usage awareness
Status: proposed
Depends on: Edict 0007 (hooks registered by init and hydrate; hooks make no model calls);
Edict 0011 (the config schema registry)

*Drafted by Daedalus at Kohl's request in conversation on 2026-10-15, from a check of the current
Claude Code docs (hooks, statusline, costs, settings).*

## Intent
Give Daedalus a working sense of time and of its own budget, so that it can work unattended
overnight and stop cleanly instead of being cut off.

**Today, Daedalus doesn't know what time it is.**
- It sees a date at session start and nothing after that.
- It can't tell that an hour has passed during a long run, or that its owner hasn't replied since
  midnight.
- It misjudges its own pace. Edict 0011 was planned as a night shift and took 44 minutes.

**It also can't see how close the account is to its usage limits.**
- Claude Code passes the 5-hour and weekly usage only to the status line script, and shows it only
  to the user.
- An unattended session therefore runs until it hits a limit mid-task.
- `autoContinueAtUsageLimit` makes Claude Code wait for the reset and carry on, but the work is
  still interrupted wherever it happened to be.

**The fix uses only documented pieces:**
- **A hook that puts the time into context.** It fires on each prompt, and also during long runs.
- **A status line command that records the usage numbers it is given** to a local file.
- **The same hook reports those numbers**, so Daedalus can reach a clean stopping point (commit,
  exhale) before a limit hits.

## Constraints

### The clock hook
- **`daedalus hook clock` is registered by `init` and `hydrate`**, for two events. Like the other
  hooks, it is controlled by config (`hooks.clock`, default true).
  - **UserPromptSubmit:** on every prompt, plain stdout carries one line:
    `Now: 2026-10-15 Thu 04:12 -04:00 · session 1h52m · since your last message 6h03m`.
  - **PostToolUse:** the same line, as JSON `hookSpecificOutput.additionalContext`, since plain
    stdout from PostToolUse doesn't reach the model. It is throttled to once every
    `clock.tool_interval_minutes` (default 5; 0 turns it off). The throttle state is a small file,
    per session, under the cache directory.
- **The time is the machine's local time with its UTC offset.** `clock.timezone` overrides it
  (an IANA name).
- **Session time is measured from the session's first hook call**, recorded per `session_id`.
  "Since your last message" is measured from the previous UserPromptSubmit in the same session,
  and is left off when there was none.
- **The hook is cheap and silent on failure.**
  - It makes no model calls and no network calls (0007).
  - It imports nothing beyond the standard library and Daedalus's config.
  - It finishes in under 100 ms on a warm cache.
  - On any error it prints nothing and exits 0, so it can never block a prompt or a tool call.
- **Each injection stays under 200 characters**, so a long session pays tens of tokens per prompt
  or per five minutes, not more.

### Usage: the status line bridge
- **`daedalus statusline` is a status line command.**
  - It reads Claude Code's status line JSON on stdin.
  - It prints a compact status line for the user: the model, context used, 5-hour and weekly usage
    with their reset times, and the active gameplan task.
  - It writes the usage it was given to a local file, `<cache>/usage.json`. That file records the
    `rate_limits` object as given (`five_hour` and `seven_day`, each with `used_percentage` and
    `resets_at`), the time it was written, and the `session_id`.
  - Usage limits are per account, not per project, so there is one file per machine.
- **`daedalus usage record` does only the write and prints nothing.** It's for an owner who keeps
  their own status line and pipes the JSON through it as well.
- **Whether the status line is set up** is decided by config (`statusline.install`, default true).
  - `init` and `hydrate` set `statusLine` in the project's `.claude/settings.json` to
    `daedalus statusline`, with `refreshInterval` 60, so the file stays fresh while the session is
    idle.
  - They never replace a `statusLine` the project or user already has. `doctor` notes that case and
    shows how to add `daedalus usage record`.
- **The file is written atomically** (a temporary file, then a rename), so a reader never sees half
  a file.

### Usage: what Daedalus sees
- The clock line gains usage when `<cache>/usage.json` exists and was written within
  `usage.fresh_minutes` (default 10): `· 5h 62% (resets 06:00) · week 31%`.
- **Stale or missing data is reported as such**, never shown as current:
  - a stale file gives `usage unknown (last seen 03:40)`;
  - no file gives no usage part at all. An API-key account never gets `rate_limits`, and the docs
    say so.
- **Thresholds turn the readout into guidance.** The thresholds are `usage.warn_percent` (default
  80) and `usage.wrap_percent` (default 90), applied to both windows.
  - At warn, the line adds: `near the limit: finish the current step before starting a new one`.
  - At wrap, it adds:
    `at the limit: reach a clean stopping point now (commit, gameplan, exhale)`.
  - These are the only instructions the hook ever gives. Each states a budget fact, and names no
    task.
- **The exhale and inhale skills learn the line.**
  - Exhale says that the wrap line is a reason to exhale.
  - Inhale reads the clock line and the time of the last session note, and says how long it has
    been since the last session ("last session ended 9h ago").

### Don't break the prompt cache
Prompt caching reuses everything up to the first changed token. Anything that changes from turn to
turn and sits early in the context makes every later request a cache miss, at full price.
- **Changing text goes only at the end of the context.**
  - UserPromptSubmit output joins the newest user turn.
  - PostToolUse `additionalContext` sits next to the newest tool result.
  - Both are at the end, after everything the cache already holds.
- **Nothing this edict adds may change the cached prefix.** No clock line, usage or context figure
  is written into CLAUDE.md, the identity files, skills, agents, the SessionStart brief, or
  anything else read at session start.
  - The SessionStart brief may say the date. It is written once per session, before the first
    request, and never rewritten.
- **The line's format is fixed.** The same fields always come in the same order, and only the
  values change. The line is short, so a turn's new tokens stay few.
- **The throttle on PostToolUse is there for cost as well as noise.** At the default of 5 minutes,
  a long autonomous run adds a line a handful of times an hour, not once per tool call.
- **The cache hit rate is watched.** `daedalus statusline` shows the session's cache hit rate when
  the status line JSON carries `prompt_cache`. 0010's digests already record it per session, so a
  drop after this edict ships is visible in the next reflection.

### Context usage: see Edict 0015
How full the context is, and with what, is Edict 0015's (the context map). It measures both
exactly from the transcript's per-request usage, nudges at natural breakpoints and when the context
fills, and feeds the exhale skill.

What this edict keeps:
- **`daedalus statusline` may show the context percentage to the user,** from the status line's
  `context_window`. That's display only. It isn't recorded, and the clock line doesn't carry it.
- **The clock line carries no context figure,** so that 0015's nudge is the single source.

### Unattended runs
- **`autoContinueAtUsageLimit` is the owner's setting.** It lives in Claude Code's user settings,
  so Daedalus never sets it.
- **`doctor` gives a hint, never a finding,** when the setting is off on a machine with
  `hooks.clock` on: an unattended run will stop at the limit instead of waiting for the reset.
- **After an automatic continue, the first clock line says so:**
  `resumed after the usage reset at 06:00`. The hook knows from the time since the last tool call
  and from the reset time that passed. Daedalus then re-reads the gameplan before going on, as it
  would after a compaction.

### Config
These keys register in 0011's schema registry, each with a description:
- `hooks.clock`
- `clock.tool_interval_minutes` and `clock.timezone`
- `statusline.install`
- `usage.fresh_minutes`, `usage.warn_percent` and `usage.wrap_percent`

(`context.warn_percent` belongs to Edict 0015.)

`hooks.clock`, `clock.*` and `usage.*` can be overridden per project.

## Acceptance criteria
- **The clock hook on prompts.** After `daedalus init` (and `hydrate`), `.claude/settings.json`
  registers `daedalus hook clock` for UserPromptSubmit and PostToolUse. Running hydrate twice
  doesn't duplicate it. With `hooks.clock false`, it's removed.
- **UserPromptSubmit output.** The hook prints one line with the date, weekday, local time and
  offset. With a frozen clock in a test, it shows the session time and the time since the last
  prompt. A first prompt has no "since" part.
- **PostToolUse output.** The output is valid JSON with
  `hookSpecificOutput.hookEventName == "PostToolUse"` and `additionalContext` set. A second call
  inside the interval prints nothing. With an interval of 0, nothing is printed.
- **Usage in the line.**
  - With a fresh fixture `usage.json`, the line shows both windows and their reset times.
  - With a stale one, it shows `usage unknown (last seen ...)`.
  - With none, it shows no usage part.
  - At 80% and 90% it adds the warn and wrap phrases. The fixture's shape is the documented
    status line JSON, labelled synthetic with the doc URL.
- **The status line.** `daedalus statusline`, given fixture status line JSON on stdin, prints the
  status line and writes `usage.json` atomically. Given JSON with no `rate_limits`, it prints a
  status line and writes nothing. `usage record` writes and prints nothing.
- **An existing status line is kept.** `init` and `hydrate` leave an existing `statusLine`
  unchanged, and `doctor` names the `usage record` alternative.
- **Failure is silent and fast.**
  - With an unreadable cache directory, the hook prints nothing and exits 0.
  - Importing the hook's module imports nothing outside the standard library and `daedalus.config`.
  - A test times the hook at under 100 ms over 20 runs on a warm cache, and skips with a message
    on slow CI runners.
- **The cache stays intact.** A test runs `init` and `hydrate` with the clock on and checks that
  no file read at session start (CLAUDE.md, skills, agents, identity) contains a time, usage or
  context figure. Another test checks that two clock lines a minute apart differ only in their
  values.
- **Context.** The clock line never contains a context figure, and a test checks that. With
  fixture status line JSON carrying `context_window`, `daedalus statusline` shows the percentage
  and writes no context figure to `usage.json`.
- **Resuming.** Given a gap that spans a `resets_at` in the usage file, the next line says
  `resumed after the usage reset at <time>`.
- **doctor.** It hints when `autoContinueAtUsageLimit` is unset or false and `hooks.clock` is on.
  The hint is not a finding, and doesn't fail CI.
- **Config.** Every new key has a description in the registry, and invalid values are refused
  with their allowed range.
- **Docs.** The README's settings table and "What lives where" list the new keys and
  `<cache>/usage.json`. The docs say plainly that usage numbers exist only for Pro and Max
  accounts (or behind a gateway with a spend limit), and only after the session's first response.

## Non-goals
- **No reading usage any other way.** No undocumented endpoint, no scraping of `/usage`, and no
  network calls. The status line JSON is the only source.
- **No acting on the budget on its own.** Daedalus doesn't stop or commit just because the hook
  fired. The hook informs, and the session decides. Its skills say what a clean stop is.
- **No time limits or schedules for unattended shifts.** "Work until 07:00" is a later edict.
  This one only gives the clock that such an edict would need.
- **No changes to Claude Code settings beyond the project's own `.claude/settings.json`.** The
  owner keeps `autoContinueAtUsageLimit` and anything else in user settings.

## Readiness (not yet amended)
Momus reviewed this draft on 2026-10-15 (`.daedalus/momus/trials/2026-10-15-edict-0014-readiness.md`)
and found it not ready. There are four blockers:
- **Under 100 ms is false.** Importing `daedalus.config` alone takes about 95 ms. The fix is a
  standalone stdlib-only hook module.
- **One shared usage file mixes concurrent sessions' context figures.** Per-session data needs a
  file per session.
- **A `resets_at` that has passed is still shown, and the wrap phrase has no hysteresis.** That
  includes 90% of a weekly window, five days out.
- **The `autoContinueAtUsageLimit` doctor hint is wrong.** The setting is on by default for
  subscribers, and it never applies to `-p` runs, background sessions, or resets more than 24
  hours away.

There are also major findings:
- hook registration holds one command per event, and the board hook already uses
  UserPromptSubmit;
- the "resumed" inference is unsound;
- chars/4 underestimates context by about 2.4 times; scale it to the status line's token count;
- some acceptance criteria can't fail;
- a committed `statusLine` would override teammates' own.

The trial has proposed amendment text for each. Kohl asked to formalize this later.

## Amendments
- **2026-10-15:** the "Context usage" section and its acceptance criterion now defer to Edict 0015,
  and `context.warn_percent` moved there.
  - **Asked for by:** Kohl, in conversation: "Amend 0014", after 0015 was written to replace this
    section's breakdown.
  - **Why:** 0015 measures context exactly from the transcript. This section estimated it as
    characters / 4, which the readiness review found undercounts by about 2.4 times. Two
    edicts nudging about the same context would also double the noise.
  - **What didn't change:** the rest of the readiness findings above are still open.

