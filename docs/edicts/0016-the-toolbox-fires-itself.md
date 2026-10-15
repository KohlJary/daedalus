# Edict 0016: The toolbox fires itself
Status: accepted
Depends on: Edict 0007 (hooks registered by init and hydrate; hooks make no model calls and only
propose); Edict 0011 (the config schema registry); Edict 0015 (the context map, which runs on this
edict's hook kit)

*Drafted by Daedalus at Kohl's request in conversation on 2026-10-15. Kohl asked to ship it "at least
as a starting ground", with the Momus gate opt-out. The draft rests on a hook audit of four sessions'
transcripts (2026-10-13 to 15) and the current Claude Code hooks docs. Momus reviewed the first draft
(`.daedalus/momus/trials/2026-10-15-edict-0016-toolbox-readiness.md`), and this text folds in its
findings. The TUI's needs come from the session that built edict 0012. Kohl accepts this edict by
setting `Status: accepted`; Kohl accepted it on 2026-10-15.*

## Intent
Daedalus has a workshop full of tools and mostly doesn't pick them up. Across four sessions, counted
with regexes over the transcripts (main thread only, approximate, re-run by Momus):
- the memory, labyrinth, docs and test-runner agents were called 0 times each;
- Theseus was called once, against about 200 edits;
- palace queries ran only in the sessions that were building the palace, against about 770 greps;
- `/inhale` ran once in about 10 session starts and compactions;
- exhale ran 3 times across 6 compactions.

Recording lags as well:
- **Commands:** there were 16 `gameplan task status` commands, 9 of them marking a task done, and 16
  applications of pending proposals, against 39 PRs created.
- **Doctor:** this morning it flagged two workstreams with 14 and 10 commits the gameplan never
  recorded.

The pattern behind those numbers: **a tool tied to an exact moment and an always-loaded rule gets
used.** Momus ran more than 30 times, mostly unprompted, because a memory rule ties it to "before
done". A tool tied to a vague moment ("before grepping blind", "what did we decide?") sits near zero,
even when a rule names it. The "Reach for Your Tools" table in CLAUDE.md is a list of triggers written
as suggestions.

This edict turns the strongest of those triggers into hooks. Each one:
- **fires at an exact event:** a commit, a PR, a merge, a compaction, a session start;
- **brings the data where it can,** not a reminder;
- **is cheap enough to run on every tool call;**
- **spends a small noise budget,** and logs whether each nudge led to the tool being used, so
  useless nudges get retired on evidence.

It is a starting ground: the shared hook kit, plus the triggers the audit rated strong. Everything
else stays explicit until the efficacy log says otherwise.

It matters beyond convenience. The paid baseline runs that will test whether Daedalus makes an agent
better (not before 2026-10-23) should test Daedalus as designed, not Claude sitting beside tools it
never opens.

## Constraints

### The hook kit
- **A top-level, standard-library-only package, `daedalus_hookkit`,** in the same distribution,
  with its own console script `daedalus-hook <event>`.
  - **Why it sits outside `daedalus`:** `import daedalus` alone costs 64-85 ms, because its
    `__init__` re-exports the labyrinth.
  - **Imports:** it never imports `daedalus`, click or the CLI at module level.
  - **Config:** it reads the project's `.daedalus/config.json` and the global config as raw JSON,
    with defaults matching the schema registry (a test checks they agree).
  - **Heavier modules** (palace, doctor, the reflection parser) are imported only inside a feature,
    once that feature's condition is met.
- **Speed.**
  - **Target:** "no feature fires" means a PostToolUse event for a `Read` call, with session state
    present and no threshold crossed. For that case, the `daedalus-hook` process, measured as a
    subprocess from start to exit, takes at most 40 ms at the median of 20 warm runs.
  - **SessionStart is exempt.** Its brief runs doctor, about 1.3 s today, once per session start
    and per compaction.
- **One dispatcher per event:** UserPromptSubmit, PreToolUse (Bash), PostToolUse (all tools),
  SessionStart, PreCompact and Stop.
  - Each reads stdin once and runs each enabled feature.
  - It merges their output in the form the docs give that event:
    - plain stdout for UserPromptSubmit and SessionStart;
    - `hookSpecificOutput.additionalContext` for PostToolUse;
    - a `permissionDecision` for PreToolUse.
  - **Stop and PreCompact never print.** Any Stop output continues the turn, at the cost of a full
    extra turn, and PreCompact output never reaches the model. On those events, features may only
    update state.
- **No `if` filters.** Matching `if` against compound and env-prefixed commands is unverified, and
  the docs call it best-effort. Bash features run inside the Bash dispatchers and match the command
  text themselves:
  - a command is split on `&&`, `||`, `;` and `|`;
  - each segment is checked after dropping leading `VAR=value` assignments.
- **Registration.**
  - `HOOKS` in `hooks.py` stays a list of entries per command. It gains a matcher field, and
    `register_hooks` compares on event, matcher and command, keeping per-command removal.
  - `init` and `hydrate` register a dispatcher when any of its features is enabled, and remove it
    when none is. They never touch other hooks.
  - Existing commands move onto the kit, with unchanged behavior except where this edict says so:
    the board hook (UserPromptSubmit) and the capture hook (SessionEnd and PreCompact, state only).
- **Fail soft.**
  - Every dispatcher catches `BaseException`, exits 0, and never exits 2. On UserPromptSubmit,
    exit 2 erases the prompt.
  - An error in a feature drops that feature's output.
  - A gate that errors **allows** the call, logs `allowed-by-error`, and adds one line saying the
    gate didn't run and why. Failures are visible, never silent.
- **Every feature is a no-op without a `.daedalus/` directory or a gameplan** (0007).
  `daedalus_hookkit` imports no dream module, and 0013's import test covers it.

### Relation to 0014 and 0015
- **This edict owns the kit, the registration and the noise budget.** Hook features from other
  edicts run as features of the kit. Whichever of these edicts is built first builds the kit as this
  edict specifies.
- **0015's context hook is a kit feature.**
  - Its 100 ms requirement is met by the kit's target plus its own incremental index.
  - Its nudges are limited by both 0015's `context.nudge_minutes` and this edict's
    `hooks.budget_per_hour`.
  - Its Stop and PreCompact paths only update state (the index and the saved plan), per the rule
    above.
  - Exhale at a threshold (the audit's "strong" row) is 0015's breakpoint and warn nudges, and isn't
    duplicated here.
- **0014's clock hook,** when built, is also a kit feature.
  - Its readiness review already requires a standard-library hook module, and this is that module.
  - The clock line is exempt from the nudge budget, since it states the time and nothing else. It
    keeps 0014's own throttle.
  - The stand-in clock in this checkout's `.claude/settings.local.json` (`.claude/hooks/clock.sh`)
    is removed when the kit's clock ships.
- **One registration per event.** Neither 0014 nor 0015 registers its own commands. 0015's
  "Registration" criterion is met when the kit's dispatchers are registered with its feature
  enabled.

### Shared state, the noise budget and efficacy
- **Per-session state** at `<cache>/hooks/<session_id>.json`, written atomically. It holds:
  - files edited, with times;
  - test runs;
  - PRs created (number → branch → head sha);
  - compaction times;
  - per-cycle flags;
  - the events log (below).

  State older than 7 days is pruned.
- **The events log.** Each entry is `{"at", "hook", "event", "nudge", "followed", "tool"}`:
  - `followed` is true or false once known, null until then;
  - `tool` is the tool the nudge names.

  Next to the log, the state keeps `"gate": {"blocks", "passes", "skips", "allowed_by_error"}` and
  `"budget": {"per_hour", "used"}`. The TUI (0012) reads this shape.
- **The noise budget.**
  - At most `hooks.budget_per_hour` nudge lines per session-hour (default 6), and at most one per
    tool call.
  - Each nudge id fires at most once per cycle, as its feature defines.
  - Lines over budget are dropped and logged, never queued.
  - Gates and the SessionStart brief don't count against the budget.
- **A fixed format.**
  - Every line starts with `Daedalus:` and a feature tag, states facts and a command, and stays under
    300 characters.
  - Lines never claim to be the user.
  - Quoted text from memory files, board posts or ledgers is marked as quoted data (0009).
- **Efficacy.** A nudge's `followed` becomes true when the tool it names is used within
  `hooks.efficacy_window` events (default 20), and false after that. The reflection digest (0010)
  gains:
  - per-agent-type and per-skill call counts;
  - followed and ignored counts per nudge;
  - the gate counts above.
- **The prompt cache is safe.** This is the same rule as 0014. Changing text goes only at the end of
  the context, and nothing writes into files read at session start.
- **Library functions.** Every piece of state is also available through library functions in
  `daedalus` (for example `hookstate.load(project_dir, session_id)`), for the TUI, which calls
  functions and never parses CLI output (0012).

### The triggers
1. **The Momus gate at merge** (`hooks.momus_gate`: `gate`, `nudge` or `off`; **default `gate`**).
   - **Scope.** The PreToolUse Bash dispatcher checks any segment that runs `gh pr merge`. Hooks see
     only Claude's tool calls, so a merge done by hand on GitHub is never affected.
   - **Finding the PR's branch and head:**
     - first, from session state: when a `gh pr create` succeeds, the PostToolUse dispatcher records
       the PR number from its output, with the current branch and HEAD;
     - otherwise, from `gh pr view <n> --json headRefName,headRefOid,files,body`, with a 5-second
       timeout. This is the only network call any hook makes. It's allowed because it runs only on a
       merge command, which is itself a network action. A timeout or error falls under fail soft;
     - a `gh pr merge` with no number uses the current branch.
   - **Where trials are read:** `.daedalus/momus/trials/` under `$CLAUDE_PROJECT_DIR`, or under the
     project root found from the hook's `cwd` when that's unset. They aren't found through
     `git rev-parse --git-common-dir`, which in a submodule points into the parent's `.git/modules`.
   - **When a trial covers the PR:**
     - **at the head:** its `Covers:` line names the PR's branch at the PR's head commit;
     - **at an earlier commit:** it still covers the PR when every later commit touches only `*.md`
       or `docs/` files. Otherwise the gate denies with "N commits since the trial";
     - **the verdict isn't read:** the gate checks that a review happened, not what it concluded.
       Acting on the verdict stays with the session and Kohl;
     - **no fallback** to a trial's first lines: coverage needs the `Covers:` line.
   - **What passes:**
     - a diff touching only `*.md` and `docs/` files;
     - a command with `DAEDALUS_MOMUS_SKIP="<reason>"`;
     - a PR body containing `momus: skip <reason>`.

     Each skip is logged with its reason.
   - **The deny reason** names the branch, the PR and both ways through.
   - **The Momus constitution changes.** `plugin/agents/momus.md`'s trial format gains a required
     first-block line, `Covers: <branch> @ <sha>`. Accepting this edict is Kohl's sign-off for that
     change.
   - **Opt-out, and watched.**
     - It is on by default, and the efficacy log counts what it does.
     - After two weeks of use, the reflection report says what the gate caught compared with what it
       cost, so Kohl can decide the default.
     - Daedalus ran about 5 or 6 of the last 39 merges, and only those reach the gate. Whether any of
       them lacked a trial is an open question the watch will answer.
   - **Night shifts and other unattended runs** turn the gate off through config, like any other
     hook. Dream PRs are not exempt: they pass or skip like any other PR.
   - **`nudge` mode.** After `gh pr create`, a PostToolUse line says that no trial covers the
     branch. The line also prints in `gate` mode.
2. **Gameplan capture at commit and merge** (`hooks.capture`; **the default changes to on**).
   - **After a `git commit` (PostToolUse):**
     - the hook runs the existing `propose_from_commits` (proposals only, as 0007 requires);
     - it adds one line naming the open task IDs the new commits touch, and the command that
       resolves them.
   - **After a `gh pr merge`,** the line also says:
     - whether the merged PR's `Implements edict NNNN` edict is still `accepted`;
     - whether the active phase now has every task done.
   - **Pending proposals become visible.**
     - The SessionStart brief gains "N pending gameplan proposals (`daedalus gameplan pending`)".
     - Doctor gains a hint for proposals older than a day.
3. **Memory lookup on mentions and questions** (`hooks.memory_lookup`, default on).
   - **When it fires:** on UserPromptSubmit, when the prompt matches `memory_lookup.patterns`, a
     configurable list. The defaults are "why did we", "what did we decide", "last time", and `T-`
     task and edict IDs.
   - **What it does:** it greps `decisions.md`, `session-summaries.md`, the gameplan's resolutions
     and `docs/edicts/` itself. It injects at most 3 hits as `file:line` plus the line, marked as
     quoted data, under 300 characters in all.
   - **Once per cycle:** each matched term injects at most once per compaction cycle.
   - **What it's betting on:** in the audit, questions about the past were rare. About 6% of prompts
     matched any pattern, nearly all of them IDs. This is a bet that lookups don't happen because
     they cost a step, not a fix for lookups that were made and then ignored. The efficacy log tests
     the bet, and the feature is cut if it doesn't pay.
4. **Inhale after compaction, made specific** (part of the SessionStart brief).
   - **When it checks:** on SessionStart with source `compact`, the brief checks whether anything
     was recorded since the previous compaction.
     - **The previous compaction:** its time in session state, or the session's start if there is
       none.
     - **Recorded:** a write to `session-summaries.md`, or a gameplan resolution, after that time.
   - **If nothing was recorded,** the brief names what is unrecorded: commits after the gameplan's
     last update, and `in_progress` tasks with no resolution.
   - **Otherwise it adds nothing.** 0015's recovery block covers what the summary lost. This covers
     what was never written down.
5. **Tests for the commit** (`hooks.tests_at_commit`, default on once the graph cache exists).
   - **The line:** after a `git commit` (PostToolUse), one line names the tests that cover the commit
     (`palace tests-for --diff --base HEAD~1`). It also says whether a test run happened after the
     last edit to those files, from session state.
   - **Why after the commit:** the line arrives after the commit has run. Its job is to catch an
     untested commit before a push or PR, not to block the commit.
   - **The cache:** the palace graph is cached at `<cache>/palace/<project-hash>.pickle`, keyed by
     the path, size and modification time of every source file. Any change rebuilds it.
   - **Speed:** if the cached query takes over 300 ms, the line is skipped for that commit and
     logged as slow. It's never late, and never blocking.
6. **Reflection due** (part of the SessionStart brief).
   - **Source:** `.daedalus/reflection/due.json`, with `due` (a list of levels), `checked_at`,
     `covered_through` and `runs`.
   - **When it shows:** one line when `due` is non-empty. Like the Sources and Dream lines, it's read
     as raw JSON, with no imports.
   - **When the data is stale:** when `checked_at` is over a day old, the line says so, rather than
     reporting it as current.

### What stays explicit
- **Dreams.** 0013 forbids running them from hooks. The due line already exists.
- **Reflection runs and board posts.** The first makes model calls. The second needs the owner's
  approval (0009).
- **The docs, test-runner, labyrinth, Ariadne and reconstruct workflows.** Triggers 3 and 5 do
  their deterministic part.
- **A Stop gate on "done" wording.** About 126 messages in four sessions read as done-claims, so it
  would fire constantly, and each block costs a full turn.
- **Later candidates, if the budget allows:**
  - palace impact on a file's first edit, run as an A/B arm the way 0010 does;
  - a Theseus nudge on big edits to complex files;
  - a one-line reminder on edits to `docs/edicts/*.md`.

### Doctor
Doctor gives a hint (not a finding) when:
- the registered hooks differ from config, which means a missed `hydrate`. Today only SessionStart
  is registered in this repo, though the board hook defaults on;
- the working directory is a git worktree with no `.claude/settings.json`, so it runs without
  Daedalus's hooks.

### Config
Every key goes in the 0011 schema registry with a description, and each can be overridden per
project. `PROJECT_SETTING_GROUPS` gains `memory_lookup`.
- `hooks.momus_gate`
- `hooks.capture` (the default changes to on)
- `hooks.memory_lookup` and `memory_lookup.patterns` (a list)
- `hooks.tests_at_commit`
- `hooks.budget_per_hour` and `hooks.efficacy_window`

## Acceptance criteria
- **The kit is light.**
  - A test imports `daedalus_hookkit` and checks that `sys.modules` contains no `daedalus`,
    `click` or `daedalus.cli`.
  - A timing test runs the `daedalus-hook` console script as a subprocess 20 times on the "no
    feature fires" event. The median must be 40 ms or less. On slow CI the test skips with a message.
- **Registration.**
  - After `hydrate`, `.claude/settings.json` has the dispatchers, and running hydrate twice changes
    nothing.
  - Turning off every feature of a dispatcher removes that dispatcher. Other hooks are untouched.
  - With 0015's feature on, its context hook is served by these dispatchers, with no separate
    registration.
- **Defaults agree.** A test checks the kit's built-in defaults against the schema registry.
- **Silent events.** Given state that would produce a nudge, the Stop and PreCompact dispatchers
  print nothing and update state.
- **Fail soft.**
  - A feature that raises produces no output, and the others still print.
  - A dispatcher that hits an exception still exits 0.
  - A gate that raises allows the call, prints its one-line notice, and logs `allowed-by-error`.
- **No-op without Daedalus.** In a directory with no `.daedalus/`, every dispatcher prints nothing
  and exits 0.
- **The budget.**
  - With frozen time, the seventh nudge in an hour is dropped and logged.
  - A nudge id doesn't repeat within its cycle.
  - Gates and the brief aren't counted.
- **The Momus gate.** These tests run on fixtures: a temporary repository, worktrees, trial files,
  and a fake `gh` on `PATH`.
  - **Matching commands:**
    - `cd x && gh pr merge 12 --merge` is checked;
    - `FOO=1 gh pr merge 12` is checked;
    - `echo gh pr merge` is not checked.
  - **Finding the PR's branch:** PR 12's branch comes from session state recorded at a fixture
    `gh pr create`. Without that state, it comes from the fake `gh pr view`.
  - **Denied,** with the branch and PR named:
    - no trial;
    - a trial naming another branch;
    - a trial at an older commit with a code commit after it ("1 commit since the trial").
  - **Allowed:**
    - a `Covers:` trial at the head;
    - a trial at an older commit followed only by docs commits;
    - a docs-only diff;
    - `DAEDALUS_MOMUS_SKIP="reason"`;
    - `momus: skip reason` in the fake PR body.

    Each skip is logged with its reason.
  - **A hanging `gh`:** a fake `gh` that hangs past the timeout allows the call, with the notice.
  - **Modes:**
    - with `off`, nothing happens;
    - with `nudge`, the merge isn't blocked, and `gh pr create` without a trial adds the line.
  - **Submodules:** with `CLAUDE_PROJECT_DIR` set to a project whose `.git` is a submodule's gitlink,
    trials are read from that project's `.daedalus/`.
- **Momus's format.** `momus.md` requires the `Covers:` line, and the gate's parser reads a sample
  trial.
- **Capture.**
  - After a fixture commit that touches a task's files, the line names the task ID and the resolve
    command.
  - After a fixture merge of a PR saying `Implements edict 0099`, the line reports the edict's
    status and whether the phase is complete.
  - The brief shows the pending-proposal count, and doctor hints at proposals older than a day.
- **Memory lookup.**
  - "why did we drop chars/4?" against a fixture `decisions.md` injects the matching `file:line`,
    marked as quoted.
  - No match prints nothing.
  - The output is at most 300 characters and three hits.
  - A second mention of the same edict in the same cycle prints nothing.
- **Inhale after compaction.**
  - With fixture commits after the gameplan update, and nothing recorded since the stored compaction
    time, the SessionStart (compact) brief names those commits and the `in_progress` tasks.
  - With a recording after that time, it adds nothing.
  - With no state, the session's start time is used.
- **Tests for the commit.**
  - With a cached graph and a commit changing a covered function, the line names the test and
    whether a test run happened after the last edit.
  - With no cache, it's silent.
  - Changing one source file's modification time rebuilds the cache.
  - A query over 300 ms is skipped and logged.
- **Reflection due.**
  - With a fixture `due.json` whose `due` is `["weekly"]`, the brief has the line.
  - With `due` empty, it doesn't.
  - With `checked_at` two days old, the line says the data is stale.
- **Efficacy.**
  - In a fixture session with two nudges, where the named tool follows one within 20 events, the
    digest reports one followed and one ignored.
  - Per-agent-type and per-skill counts appear.
  - The gate's counts include `allowed_by_error`.
  - The state file has the shape given above, and `hookstate.load` returns it.
- **Doctor.**
  - With the board hook enabled but not registered, it hints `daedalus hydrate`.
  - In a worktree without `.claude/settings.json`, it says so.
- **Docs.**
  - The README lists every hook, what it injects, its key and its default, and the gate's two skip
    routes.
  - The "Reach for Your Tools" table in `plugin/templates/CLAUDE_TEMPLATE.md` notes which rows now
    fire by themselves.

## Non-goals
- **No model calls from hooks.** This is 0007's rule, unchanged.
- **No hook writes the gameplan, the status note or an edict.** Hooks write proposals only.
- **No gate on Kohl's own actions.** Hooks see only Claude's tool calls.
- **No new subagents.** Where a hook can do the deterministic part (triggers 3 and 5), it does it
  rather than summoning an agent.
- **Not every row of the table.** This is the starting ground, and the efficacy log decides what
  comes next.
