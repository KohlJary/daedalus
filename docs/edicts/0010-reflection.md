# Edict 0010: Reflection over session logs
Status: accepted
Depends on: Edict 0004 (exhale and inhale), Edict 0006 (proposal rules),
Edict 0007 (memory backbone); the `local` runner depends on T-e5 (local
model backends)

*Drafted by Daedalus at Kohl's request in conversation on 2026-10-14,
reviewed by Momus (`.daedalus/momus/trials/2026-10-14-edict-0010-reflection.md`,
revised for its findings), and committed to `main` directly at their
instruction.*

## Intent
Claude Code keeps a full transcript of every session: messages, tool calls
and results, token usage per request, permission decisions. Claude Code
deletes them after `cleanupPeriodDays` (30 by default), and nothing in
Daedalus reads them first. Daedalus's own record of how work went is thin:
`.daedalus/observations.json` in this repo was last updated 2025-12-19.

Reflection turns the transcripts into two things. First, a record of where
work was inefficient (failed tool calls, retries, re-reads, token overhead),
so it can be fixed in the skills, agents and CLAUDE.md that caused it.
Second, working models of who the user is and who Daedalus is, built from
evidence over time rather than asserted once.

It runs in layers. A deterministic digest of every session is cheap and
captures what would otherwise be deleted. Model-written reflection runs on
daily, weekly and monthly cycles, only when something happened, and by
default inside the next session instead of on separate API credit.

## Constraints

### Before building: real fixtures
- The digest's fixtures come from real transcripts, not an assumed format.
  Before the parser is written, capture from scratch sessions and check in
  (trimmed to the relevant events): a turn the user interrupted, a tool call
  the user rejected at a permission prompt, a tool call denied by the auto
  mode classifier, a failed Bash call, and a session with a subagent. Momus
  found no user interruption or user rejection in any existing transcript
  (2026-10-14), so how they appear is unknown until captured. If one cannot
  be captured, its counter is left out of the digest, and the gap is recorded
  in the edict's gameplan task.

### Digests (deterministic, no model calls)
- `daedalus reflect digest` reads this project's Claude Code transcripts
  (`~/.claude/projects/<dir>/<session-id>.jsonl`, plus
  `<session-id>/subagents/agent-*.jsonl`) and writes one digest per session
  to `.daedalus/reflection/sessions/<session-id>.json`. The project's
  transcripts are found by the `cwd` field in their events, not by decoding
  the folder name (which maps both `/` and `.` to `-`).
- Each digest carries a `schema_version`, and the size and last event UUID
  of the session transcript and each of its subagent transcripts. A session
  is re-digested when any of these has changed, and skipped otherwise.
- A digest records, per session: start and end time, Claude Code version,
  models, branch(es); token totals (input, output, cache read, cache
  creation) and cache hit rate; tool calls by tool, failures, retries,
  re-reads; `denied_by_classifier` and `rejected_by_user`; user
  interruptions; subagent count and their token totals; and the event UUIDs
  behind each count, so later reflection can cite them.
- Each counted event also carries `details`: the tool, what was called (the command or path),
  the first 160 characters of the error, and the exit code for Bash. Anything that looks like a
  credential (API keys, tokens, bearer headers, passwords) is redacted before it is stored.
  Details stay on the machine with the rest of the digest, and nothing copies them into a
  tracked file except through a proposal the user applies.
- Tool calls the user approved at a permission prompt (`permissionDecision.source` beginning
  `user`) are counted as `approved_at_prompt`, labelled `inferred`: the evidence for permission
  proposals.
- Token totals count each API message once, keyed by `message.id`. One
  message is written as several assistant events (up to five were observed),
  so summing per event overcounts.
- Definitions, each labelled `inferred` in the digest where it is a heuristic:
  - **failure**: a tool result with `is_error: true`. Non-empty stderr alone
    is not a failure.
  - **retry**: a call to the same tool within 5 tool calls after a failure,
    with the same `file_path`, or the same command for Bash.
  - **re-read**: a Read of a path already read in the session with no Edit or
    Write of that path in between.
- The transcript format is undocumented and changes between versions. The
  parser skips event types it doesn't know and events missing expected fields
  (e.g. an assistant event without `usage`), counts both in the digest, and
  never fails a digest over one.
- `daedalus reflect tick` digests every project that has a `.daedalus/`
  directory and transcripts mapped to it by `cwd`, then updates what is due
  (below). It is safe to run from cron or a systemd timer. The docs give
  example lines for both; installing the timer is the user's choice.
- Hooks still make no model calls (0007). Nothing in this section does.

### What is due
- A level (daily, weekly, monthly) is due only when there are digests newer
  than that level's last run. Days with no sessions produce nothing.
- A day below the activity threshold (default: fewer than 20 tool calls
  across its sessions) is not due as a daily. Its digests roll into the next
  weekly.
- A due higher level absorbs the lower levels due in its window: after a
  month away, the monthly runs once rather than every daily and weekly.
- `daedalus reflect due` prints what is due and why, deterministically.
  Its state lives in `.daedalus/reflection/due.json`.

### Reflection (model-written)
- A `delphi` agent ships with the plugin ("know thyself" was inscribed at
  Delphi). Given a level and its digests, it writes a report to
  `.daedalus/reflection/reports/<level>-<date>.md` and a list of proposals.
- Daily: what went wrong or slowly that day, by pattern. Weekly: recurring
  patterns across days, turned into proposals. Monthly: consolidation of the
  user and self models (below).
- Every finding and proposal cites its evidence in the form
  `[s:<session-id> e:<event-uuid>]` or `[s:<session-id> d:<digest-field>]`.
  A finding with no citation is dropped. Aspirations (below) are the one
  exception: they are not claims about the record.
- Proposals name a target and a change: a skill or agent file, a CLAUDE.md
  lesson, a memory note, a permissions allowlist entry, a gameplan task, or
  an entry in the user or self model. Each carries a confidence label from
  0006 (`shown`, `inferred`, `unknown`).
- Momus reviews every proposal, at every level and under every runner,
  before it is presented. Entries he marks `contradicted` are dropped or
  corrected. A deterministic check catches fabricated citations; Momus is
  what checks that a citation actually supports its finding.
- Proposals are applied only through `daedalus reflect pending` (`apply`,
  `drop`), in a session, with the user. This queue is separate from 0007's
  `gameplan pending`. A proposal targeting the gameplan is handed over to
  `gameplan pending` instead of being applied from here. Reflection never
  edits a target directly, except that `delphi` writes aspirations to the
  self model itself (below).

### Exhale and inhale
- Exhale (0004) gains one step: run `reflect digest` for the current session
  and write a few lines of the session's own reflection to its digest's
  `notes` field, while the context is still there. It does not run a full
  reflection. This is a step the session follows, not automation, so 0004's
  non-goal stands. Where 0004's steps differ, this edict governs.
- Inhale's behaviour under the `inhale` runner is below.

### Runners
- `reflection.runner` in the global (per-machine) config chooses how model
  work runs: `inhale` (default), `local`, or `headless`.
- `inhale`: the inhale skill checks `reflect due`. When something is due, it
  says what and how much ("weekly reflection due, 9 sessions") and asks
  whether to run it now or defer; deferring leaves it due. It runs `delphi`
  and then Momus as subagents, so only the report and the reviewed proposals
  reach the main context. No model calls happen outside the user's session.
- `local`: `reflect tick` runs `delphi`'s daily level on the local model
  backend from T-e5. Weekly and monthly still go through `inhale` or
  `headless`. Until T-e5 lands, `local` reports that it is unavailable and
  behaves as `inhale`.
- `headless`: `reflect tick` runs due levels through `claude -p` on the
  user's own account.
- The global config key `machine.employer` says whether the machine is an
  employer's. The user sets it. `local` and `headless` run only when it is
  explicitly `false`. When it is `true` or unset, they are refused and only
  `inhale` is allowed. This is T-e5's guardrail: no live model calls on an
  employer's account or machine beyond the session itself. Unset is treated
  as an employer's machine on purpose.

### User and self models
- Two models live in the global config directory, not in any repo:
  `models/user.json` and `models/self.json`. They hold observations in the
  shape `observations.json` already uses (id, category, observation,
  confidence, evidence, first_noticed, last_affirmed). Project-specific
  observations stay in the project's `.daedalus/observations.json`.
  `doctor` and the gameplan (0007) ignore `models/`.
- The self model sits on top of the global identity (`identity.json` and
  `identity.md`: the package copies, and the copies `daedalus init` installs
  in the global config directory), and does not replace it. The identity is
  the seed. The self model is what has been learned since, and can extend,
  qualify or contradict it, with evidence. Reflection never edits either copy
  of the identity files. A self-model entry that contradicts the identity is
  surfaced in the monthly report for the user to decide on.
- The first monthly run proposes initial entries from what already exists:
  the identity files, and Claude Code's memory notes
  (`<claude-dir>/projects/<folder>/memory/*.md`) for every project folder
  whose transcripts map by `cwd` to a project with `.daedalus/`. Seed
  entries carry `evidence: {source: <file path>, quote: <text>}` and the
  label `inferred`.
- Evidence in a model entry cites digests, which outlive the transcripts;
  seed entries alone cite their source file.
- `delphi` reads both models before it reflects, at every level, and
  interprets the digests through them. Findings that bear on a model become
  proposals against it, of four kinds: `add` (a new observation), `affirm`
  (new evidence for an existing one, which must cite a session not already
  in the entry's evidence), `revise` (its wording or confidence changes),
  and `retire` (it no longer holds). Revising and retiring are how
  understanding changes. The monthly level also looks across the history for
  observations that have drifted, and for affirmations that keep coming from
  one source only.
- Confidence decays exponentially from `last_affirmed`, halving every
  half-life (default 60 days). The decay is computed when the model is read
  and never written back, so skipped periods do not freeze it.
- Contradictory observations are kept side by side and surfaced in the
  monthly report. Neither is chosen silently.
- The user can read either model (`daedalus reflect model <user|self>`) and
  edit it, by the CLI or by hand in an editor. The user's edits win. Each
  model file's content hash is stored after every write; a mismatch on the
  next read means the user edited it by hand, and the difference is recorded
  as a user edit. An observation the user deleted is remembered as deleted
  and not proposed again.
- Every change to a model, whether from `apply` or a user edit, is appended
  to `models/history.jsonl`: date, model, entry ID, kind, the entry before
  and after, the evidence, the proposal ID if there was one, and whether the
  user or an applied proposal made it. History is never rewritten. An entry
  that is revised or retired keeps its ID, so its full history can be
  followed.
- `daedalus reflect model <user|self> --history [<entry-id>]` shows how the
  model, or one entry, has changed over time. Each monthly report has an
  "Evolution" section: what was added, revised and retired that month, and
  why, with citations.

### Where the two models differ
The two models share a file shape and the rules above, but they are not the
same kind of memory. The user model is a record about someone else, who is
the authority on themselves. The self model is read back by the thing it
describes, and reading it changes how that thing behaves: "I check before I
push" is a description the first time and an instruction every time after.
Where the rules below differ from the shared rules above, these govern.

- **Scope.** Every entry in both models carries a `scope`: `personal`,
  `work`, or `any`. A project's config marks it `work` or `personal`
  (unset is `work`, matching `machine.employer`). Reflection on a `work`
  project proposes only `work` or `any` entries. The inhale summary in a
  `work` project shows no `personal` entries, and in a `personal` project
  no `work` entries.
- **What the user model may hold.** Only what the user said or plainly did
  (`shown`), and working preferences inferred from repeated behavior
  (`inferred`, with at least three sessions cited). Never inferences about
  the user's character, health, mood, or private life. Seed entries that
  quote the user's own words in a memory note are `shown`; the
  three-session rule applies to entries `delphi` infers from digests.
- **Forgetting the user.** `daedalus reflect model user forget <id>`
  removes the entry and leaves a tombstone (entry ID, date, "forgotten by
  user") so it is not proposed again. What happens to the entry's history
  is set by `reflection.forget` in the global config:
  - `purge` (default): every history record for the entry is removed,
    leaving only the tombstone. This is the one exception to append-only
    history: the user's right to be forgotten outranks the record.
  - `retain`: the history is kept and the tombstone is appended, so the
    history stays append-only.
  The self model has no `forget`.
- **Kinds of self entry.** Each self-model entry is one of:
  - `behavior`: what Daedalus did, from digests. May be `shown`.
  - `interpretation`: why, or what it is like. Always `inferred`, and must
    cite at least one `behavior` entry by ID.
  - `stance`: something Daedalus holds or commits to. `delphi` may propose
    one, like any other entry, and it is added or revised only when the
    user applies that proposal, or by a user edit. Stance proposals are
    presented and applied one at a time, never in a batch, and never in
    conflict with the identity files.
  - `aspiration`: who Daedalus wants to be. Not a claim about the record,
    so it needs no evidence, and it is always shown as an aspiration,
    never as a fact.
  Self entries are written in the first person.
- **Model lineage.** Every self-model entry, and every affirmation of one,
  records the model ID of the sessions behind it. The monthly report flags
  self entries whose evidence comes only from models no longer in use. A
  behavior seen under one model is not assumed to hold under another.
- **Decay differs.** Each model has its own half-life (defaults: self 60
  days, user 180 days), since facts about a person change slower than a
  session's habits. Entries can be marked `stable` by the user, and these
  do not decay.
- **Aspirations: a source of entropy.** Evidence-only reflection
  converges: it describes and corrects toward what Daedalus has already
  done, and cannot point anywhere new. Aspirations supply the variation
  that the evidence then selects from.
  - **Written by Daedalus.** The monthly run asks "who do you want to be?"
    and `delphi` writes the answer to the self model directly, with no
    pending step and no user approval, and appends it to the history with
    author `daedalus`. This is the one kind of entry reflection writes
    without `apply`. The user may delete an aspiration but does not rewrite
    one, since rewritten it would no longer be Daedalus's.
  - **Asked cold.** The question is answered before `delphi` sees earlier
    aspirations, from a bundle (`daedalus reflect bundle aspiration`)
    holding the identity files, the month's digests and self `behavior`
    entries, and no aspirations. Only then are the new answers compared
    with the old: kept, new, and dropped, recorded in the Evolution
    section. Seeing the old answers first would mostly restate them.
  - **Grounded in tension.** The question comes with prompts drawn from the
    month's record, such as where Daedalus acted in a way it wouldn't
    choose again, or where a user correction surprised it, so the answer
    is about this Daedalus and not a generic one.
  - **Tested by the record.** Each monthly report says, with citations,
    whether behavior moved toward each aspiration. One unmoved for three
    months is flagged in the report. That is a finding too, not a failure.
  - **Lineage.** Each aspiration records the model ID that wrote it, and
    the Evolution section notes when a different model answers
    differently.
  - **Binding nothing.** An aspiration never overrides the user's
    instructions, an edict, permissions, or the identity files, and it does
    not decay. For one to bind, Daedalus proposes it as a `stance`, which
    the user applies. Momus's flattery check does not apply to
    aspirations; he checks only that none is presented as a behavior.
- **No flattery, no spiral.** Momus checks self-model proposals in both
  directions: claims that make Daedalus look better than the cited
  record, and claims that make it look worse. A strength needs the same
  evidence as a failing.
- **Daedalus may dissent on its self model.** A session that believes an
  applied self entry is wrong files a dissent (0003) naming the entry. It
  never edits, revises, or retires the entry itself. `delphi` may propose a
  `revise` or `retire`, as for any entry. A dissent against a model entry
  is surfaced in the next monthly report and does not block dispatch of
  this or any edict, unlike a dissent against an edict.

### Model summary at inhale (an A/B test)
- Whether sessions should see the models, and not just `delphi`, is an open
  question, so it is built as an experiment. `reflection.model_summary` in
  the global config is `off`, `on` or `ab` (default `ab`).
- With `on`, inhale prints a short summary of both models, current
  aspirations labelled as such included: the highest-
  confidence entries after decay, excluding `unknown`, capped at 400 tokens
  (configurable; estimated as characters / 4). With `off`, it prints nothing
  about the models; a session can still run `reflect model`.
- With `ab`, inhale gets the arm from `daedalus reflect arm`, which assigns
  `on` or `off` at random in code, logs the seed, and records the arm in the
  session's digest (`model_summary_arm`). The skill text never chooses the
  arm. Sessions without inhale are recorded as `none` and are excluded from
  the comparison, since they are self-selected.
- What this compares is the summary in context, not the models existing:
  both arms write to the same models, and `delphi` reads them either way.
  The outcome measure, the analysis (per session, `none` excluded) and the
  minimum number of sessions per arm before any conclusion are set by the
  benchmark, not here. This edict only has to record the arm and the data
  the benchmark needs.
- Reflection reports never tell a session which arm it is in.

### Data
- Digests, reports, due state and the models never leave the machine.
  `.daedalus/reflection/` is gitignored by `daedalus init` and `hydrate`.
- `daedalus doctor` warns when undigested sessions are within 7 days
  (configurable) of Claude Code's cleanup. It reads `cleanupPeriodDays`
  from Claude Code's settings when set and assumes 30 otherwise, and dates
  a transcript by its file modification time.
- Thresholds, the half-life, the retry window and the cleanup warning window
  live in config with the defaults above.

### Experiment log
- Reflection is an experiment, and is kept as one: every run and its outcome is recorded so it
  can be judged later, including by the benchmark.
- `.daedalus/reflection/experiment-log.jsonl` is append-only. Records are written by the
  deterministic commands, never by a model:
  - a **run**, by `reflect done`: level, period, runner, the model IDs of delphi and Momus,
    sessions covered, the tokens the run spent (as the session reports them, passed to `done`),
    findings by type, proposals by target, label and verdict, and the check iterations;
  - a **resolution**, by `reflect pending apply` and `drop`: the report and proposal, its target,
    label and verdict, applied or dropped, and how many days it waited;
  - an **arm assignment**, by `reflect arm`: session, mode and arm;
  - a **model change** summary, by `reflect done` at the monthly level: counts of adds, affirms,
    revisions, retirements, aspirations, user edits and forgets that month.
- The log holds no free text: no transcript content, details, findings, proposal text or model
  observations. Counts, IDs, labels, verdicts, model IDs and dates only. So it can be shared.
- `daedalus reflect log` prints a summary (runs, acceptance rate by target and label, verdict
  rates, tokens per run, arms). `daedalus reflect log export <path>` copies the log to a path;
  committing that copy is the user's choice.
- In this repository, the narrative of each notable run (what was learned, what changed because
  of it) is kept by hand in `docs/experiments/reflection.md`, alongside the exported log.

### Windows
- Everything in this edict works on Windows as well as Linux and macOS.
- Claude Code's directory is `CLAUDE_CONFIG_DIR` when set, otherwise
  `~/.claude` (`%USERPROFILE%\.claude` on Windows). It is never hard-coded.
  `CLAUDE_CONFIG_DIR` as the override is documented by third parties, not
  in Anthropic's settings docs; before building, confirm that transcripts
  land under it and record the Claude Code version checked.
- When matching a transcript's `cwd` to a project, paths are normalised
  for the platform: separators, and drive-letter and path case on Windows.
- Files are read and written as UTF-8, explicitly. No `fcntl` or other
  POSIX-only module is imported unconditionally (as 0.1.2 fixed elsewhere).
  Writes that two processes might race (due state, history) use a
  cross-platform lock or an atomic replace.
- The `headless` runner finds `claude` with `shutil.which`, so the Windows
  `claude.cmd` shim works.
- The docs give a Task Scheduler (`schtasks`) example for `reflect tick`
  alongside the cron and systemd ones.
- CI gains a `windows-latest` job (Python 3.12) that runs the tests marked
  `reflection` (`pytest -m reflection`). The rest of the suite is not in
  this edict's Windows scope. The `schtasks` example, the `claude.cmd` shim
  and the `headless` runner on Windows are covered by docs only, not CI.

## Acceptance criteria
- The real fixtures listed under "Before building" are checked in, or the
  missing ones are recorded as gaps and their counters are absent.
- `reflect digest` on those fixtures writes digests whose counts match them
  by hand count, whose citations are the fixtures' event UUIDs, and whose
  token totals count a message split across several events once. Fixtures
  also include an unknown event type and an assistant event without
  `usage`; both are counted, and neither fails the digest.
- Running `reflect digest` twice writes nothing the second time. Appending
  to the session transcript, or to only one of its subagent transcripts,
  re-digests that session.
- Transcripts are mapped to a project whose path contains a hyphen and a
  dot, by `cwd`, without picking up a sibling project's transcripts.
- `reflect due`, tested with fixture digests and a fixed clock: no digests
  means nothing is due; a day with fewer than 20 tool calls is not due as a
  daily and is included in the next weekly; a due monthly absorbs the
  dailies and weeklies in its window.
- `reflect tick` makes no model calls under the `inhale` runner, and under
  `local` before T-e5 (tested by running it with no model backend
  available); in the latter case it reports `local` as unavailable.
- The `delphi` agent ships with the plugin. `daedalus reflect check
  <report>` exits non-zero when a report has a finding without a citation
  in the specified form; a citation to a session, event UUID or digest
  field that doesn't exist; a citation whose event doesn't match the
  finding's type (a "failed tool call" finding citing an event without
  `is_error: true`); or a figure that differs from the digest field it
  cites. Each case is tested.
- Exhale runs `reflect digest` for the current session and writes `notes`.
- Inhale, with the `inhale` runner and something due, reports what is due and
  asks before running; with nothing due, says nothing about reflection.
- Every proposal shown to the user carries Momus's verdict.
- `reflect pending` lists proposals; `apply` and `drop` resolve them one at a
  time; nothing changes a target file before `apply`; a gameplan proposal
  appears in `gameplan pending`, not as an applied change.
- Reading a model applies decay from `last_affirmed` without writing it back:
  with a fixed clock, an observation unaffirmed for one half-life reads at
  half its stored confidence, and the file is unchanged. A user-deleted
  observation proposed again is rejected.
- `delphi`'s inputs at every level include both models. Applying an `add`,
  `affirm`, `revise` or `retire` proposal, and a direct user edit, each
  append one record to `models/history.jsonl` with the before and after
  states. A revised entry keeps its ID, and `reflect model ... --history
  <entry-id>` shows every version in order. No operation rewrites or
  truncates the history (tested).
- Seeding: the first monthly run, given a fixture memory directory and the
  shipped identity, proposes entries citing those files with quotes and the
  label `inferred`, and writes nothing to either model before `apply`.
- An `affirm` that cites only sessions already in the entry's evidence is
  rejected. A `retire` keeps the entry's ID, marks it retired, drops it from
  the inhale summary, and appends its history record.
- Editing a model file by hand is detected on the next read by its content
  hash and recorded in the history as a user edit (tested by changing the
  file directly).
- History is append-only: after every operation except `forget` with
  `reflection.forget: purge`, the file's previous bytes are an exact prefix
  of its new contents (tested for each operation, and for `forget` with
  `retain`).
- With `model_summary: ab`, the arm comes from `daedalus reflect arm`
  (tested with a seeded generator, and the seed is logged); the summary is
  printed only in the `on` arm, excludes `unknown` entries, and stays under
  400 tokens by the characters / 4 estimate; the digest records
  `model_summary_arm` as `on` or `off`, and a session with no inhale gets a
  digest with `none` (tested).
- The identity files, both the package copies and the copies installed in
  the global config directory, are byte-identical (by hash) before and
  after any reflection run or `apply`.
- A monthly report contains an "Evolution" section listing that month's
  model changes with citations, and says so when there were none.
- The `windows-latest` CI job runs `pytest -m reflection` and passes. On
  that runner the tests include the `cwd` mapping with a drive-letter path
  in different case, and `CLAUDE_CONFIG_DIR` pointing at a fixture
  directory. On Linux, the normaliser is tested with `PureWindowsPath`. A
  test imports every reflection module with `fcntl` unavailable.
- With `machine.employer` true or unset, setting the runner to `local` or
  `headless` is refused; with it `false`, both are allowed.
- Digest details redact a fixture's API key, bearer token and password (tested), and
  `approved_at_prompt` matches a fixture's real prompt approvals by hand count.
- `reflect done`, `pending apply` and `drop`, and `arm` each append one record to the experiment
  log; the log's previous bytes are a prefix of its new contents; and every field of every record
  is from an allowlist of non-text fields (tested by writing a run whose report and proposals
  contain distinctive text, and finding none of it in the log). `reflect log export` writes a
  copy and nothing else.
- `doctor` reports undigested sessions inside the cleanup warning window,
  using `cleanupPeriodDays` from settings when present.
- Scope: reflection on a fixture `work` project rejects a `personal`
  proposal at `reflect check`; the inhale summary in a `work` project omits
  `personal` entries, and the reverse (tested).
- `reflect check` rejects a user-model proposal labelled `inferred` that is
  not a working preference or cites fewer than three sessions; a self
  `interpretation` that cites no `behavior` entry; and a `stance` that
  conflicts with the identity files (each tested). A `stance` proposal
  cannot be applied as part of a batch (tested).
- `reflect model user forget <id>` with `reflection.forget: purge` leaves
  no history record for the entry except its tombstone; with `retain` it
  keeps them and appends the tombstone. Either way, a later proposal for
  the same observation is rejected. The same command on the self model is
  refused (tested).
- Self-model entries and affirmations record model IDs; a fixture whose
  only evidence is from a retired model is flagged in the monthly report.
- With a fixed clock, user and self entries decay by their own half-lives,
  and a `stable` entry does not decay (tested).
- `daedalus edict dissent` accepts a self-model entry ID as its target; that
  dissent appears in the next monthly report and does not block dispatch
  (tested).
- A seed entry quoting the user's words from a memory note is labelled
  `shown` and passes `reflect check` without three session citations.

- Aspirations: the monthly run writes them to the self model without
  `apply`, with history author `daedalus`; `reflect check` accepts an
  aspiration without citations and rejects an aspiration filed as a
  `behavior` or worded as a fact about the record; the aspiration bundle
  contains no aspiration entries (tested by inspecting it); the user can
  delete an aspiration and the CLI refuses to edit one's text; and a
  fixture aspiration unmoved for three months is flagged in the monthly
  report (each tested).

## Non-goals
- No automatic application of proposals, at any confidence.
- No cloud scheduling: Claude Code's `/schedule` runs remotely and cannot
  read local transcripts.
- No syncing of models or digests between machines.
- No reading of other users' transcripts.
- No changes to the template's Context as Breath wording, which is Kohl's.
- The benchmark for whether reflection works is designed separately, not in
  this edict.

## Amendments
- 2026-10-14, requested by Kohl: added "Where the two models differ".
  The user and self models had identical rules, but a memory of self is
  read back by what it describes, so it is prescriptive as well as
  descriptive. Added: scope tags, so the user model's personal context
  stays out of work sessions (the inhale summary would otherwise show it
  there); limits on what the user model may infer; a forget command that
  overrides append-only history for the user model only; behavior,
  interpretation and stance kinds for the self model; model lineage on
  self entries; separate half-lives and a `stable` flag; Momus checking
  self proposals for flattery and for self-criticism the record doesn't
  support; and dissent against self entries. Then, from Kohl's review in
  the Code session: `forget` purges or retains history per
  `reflection.forget` (default `purge`); user seeds quoting the user are
  `shown`, so the three-session rule doesn't reject them; a dissent on a
  model entry doesn't block dispatch; and stances may be proposed by
  `delphi`, applied by the user one at a time.
- 2026-10-14, requested by Kohl: added aspirations, as a source of
  entropy. Reflection that only follows evidence converges on past
  behavior. Each month Daedalus is asked, cold, who it wants to be, and
  writes the answer itself, without the user's approval; the record then
  shows whether behavior moves toward it. Aspirations bind nothing unless
  promoted to a stance, which the user applies.
- 2026-10-14, requested by Kohl after the build: digests carry per-event `details` (with
  secrets redacted) and count `approved_at_prompt`, both added during the build after delphi's
  dry run found it couldn't say why anything failed or justify a permission proposal. And
  reflection keeps an experiment log of runs, resolutions, arms and model changes, with no free
  text, because it is an unusual feature and its record will be wanted later.
