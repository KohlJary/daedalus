# Daedalus

**Claude Code that remembers, and notices when it has forgotten.**

Every Claude Code session starts from zero. Yesterday's decisions, last week's architecture
discussion, the task that was half-done when the context ran out: gone, unless someone wrote it
down. And the notes people do keep go stale in exactly the weeks that matter most, without anything
saying so.

Daedalus gives a project a working memory that lives in the repository: a **gameplan** that records
what is built, in progress, and next; a **brief** that every new session starts from; a **doctor**
that tells you when the plan has fallen behind the code; and **reconstruction** that rebuilds what
nobody wrote down, from git, with every claim cited. For teams, each person (or each Claude
session) gets their own plan, and their agents can talk to each other on a shared **board**.

It's a Claude Code plugin plus a small CLI. Everything it keeps is plain files and git.

```bash
pip install daedalus-cli
cd your-project && daedalus init
claude        # the session opens with a brief: your active phase, next task, and any drift
```

## Contents

- [Quick start](#quick-start)
- [How a session works](#how-a-session-works)
- [Memory that stays current](#memory-that-stays-current): gameplan, doctor, reconstruction, reflection
- [Working with others](#working-with-others): workstreams, the agent board, edicts
- [Ariadne: parallel workers (experimental)](#ariadne-parallel-workers-experimental)
- [The cast](#the-cast): agents and skills
- [Reference](#reference): commands, settings, files, the CLAUDE.md template
- [How this compares](#how-this-compares) · [Philosophy](#philosophy)

## Quick start

Requires Python 3.10+ and [Claude Code](https://claude.com/claude-code).

```bash
pip install daedalus-cli                 # or: pip install "daedalus-cli[sdk]" for Ariadne's workers
cd your-project
daedalus init                            # memory files, agents, skills, hooks, CLAUDE.md section
daedalus config user.name "Your Name"
claude
```

`init` creates `.daedalus/` (the plans are committed; the rest stays local), installs the agents
and skills into `.claude/`, registers the hooks in `.claude/settings.json` (merging with what's
there), and adds a managed section to `CLAUDE.md`. Re-run `daedalus hydrate` after upgrading;
`daedalus hydrate --dry-run` shows what would change first.

Then, in a session:

- Plan: *"add a phase for the auth rewrite with tasks for the token store and the middleware"*
  (Daedalus runs `daedalus gameplan phase add` / `task add`).
- Work. When a task ships, its resolution goes on the task, with the commit hashes.
- Before a break or when context runs low: `/exhale`. After a compaction or the next morning: `/inhale`.

## How a session works

```
 session start ──► brief (hook) ──► /inhale ──► work ──► record tasks in the gameplan ──► /exhale
                     │                                                                     │
                     └── active phase, next task, drift from `doctor`,                     │
                         other workstreams, unread board posts, last session note ◄────────┘
```

- **The brief.** A `SessionStart` hook prints what the new session needs first, in under 40 lines:
  the active phase and goal, the next open task, anything `doctor` found, the other workstreams,
  unread posts on the board, and the latest session note.
- **`/inhale`** is the full pickup: the gameplan, pending proposals, `doctor`, the last summary, and a
  check of all of it against the repository (branches, worktrees, unpushed commits).
- **`/exhale`** preserves the session before a breakpoint: commit finished work, record each shipped
  task's resolution, resolve pending proposals, write a short session note, suggest `/compact`.

Context compaction is treated as a breath, not a death: the work is in commits and the gameplan, so
the next context picks up where this one left off.

## Memory that stays current

### The gameplan

The gameplan is the record of state: phases, the active phase's tasks, and how each finished task was
resolved, in `.daedalus/roadmap/gameplan.json`, committed with the code. Session notes and decisions
are narrative around it.

```bash
daedalus gameplan show
daedalus gameplan phase add p2 "Auth rewrite"
daedalus gameplan phase activate p2 --goal "Replace sessions with tokens"
daedalus gameplan task add T1 "Token store"
daedalus gameplan task status T1 done --resolution "Shipped in a1b2c3d; 14 tests"
```

Nothing automatic writes it. Hooks and reconstructions only propose changes, which wait in
`daedalus gameplan pending` until you `apply` or `drop` them. An optional capture hook
(`hooks.capture`, off by default) proposes "done" for tasks that new commits name.

### `daedalus doctor`

Notes go stale silently. `doctor` makes it loud. It checks the plan against the repository and
reports, each under a stable name:

| Finding | Means |
|---|---|
| `commits-after-gameplan` | The code moved on and the plan didn't (counting only the owner's commits, per workstream) |
| `phase-tasks-all-done` / `stale-task` | A finished phase left open, or a task stuck in progress |
| `gameplan-ignored` | The plan is gitignored, so nobody else will ever see it |
| `collision-edict` / `collision-claims` | Two workstreams on the same edict, or claiming the same paths |
| `edict-not-in-gameplan` / `edict-bad-status` / `edict-duplicate-number` | Edict bookkeeping (projects using edicts) |
| `project-map-missing-packages` / `empty-file-read-by-hook` | Memory files that never kept up |
| `board-ask-rule-missing` | The board is in use but posts wouldn't ask the owner first |

It exits non-zero when it finds anything, so it can run in CI. On the projects it was built
against, it found a plan five weeks and 94 commits behind, a task "in progress" for 148 days, and
a project map missing 25 packages.

### Reconstruction: getting back what nobody wrote down

When the plan has fallen behind, `/reconstruct` rebuilds the missing period from git:

1. **Gather** (`daedalus reconstruct gather`): every commit in the gap, each with a 0-100 score for
   how much its message actually says. Commits that say little get their diff included; a few that
   say a lot get theirs too, to check the score. No model calls.
2. **Propose**: the `mnemosyne` agent turns the evidence into missing phases, tasks, status changes
   and roadmap corrections. Every entry cites its commits and is labelled `shown`, `inferred`, or
   `unknown`; nothing is marked done on less than `shown`.
3. **Check** (`daedalus reconstruct check`): deterministic validation against the repository: every
   hash real and in the window, every file real, every open roadmap item accounted for, and a list of
   commits nobody cited.
4. **Review**: Momus, the critic, re-derives the claims.
5. **You decide**: `daedalus gameplan pending import <proposal>`, then apply or drop each entry.

Windows can be narrowed (`--since`, `--until`, `--author`, `--workstream`), so *"what did Frank build
in June?"* is `gather --since 2026-06-01 --until 2026-06-30 --author Frank`. [A worked
example](docs/examples/wonderland-reconstruction/) rebuilt five weeks and 95 commits of another
project; [a second run](docs/examples/reconstruction-runs.md) worked from a history whose commit
messages were mostly single, often cryptic lines.

### Reflection: learning from the session logs

Claude Code keeps a transcript of every session and deletes it after `cleanupPeriodDays` (30 by
default). Reflection keeps what is worth keeping, and reads it back:

1. **Digests** (`daedalus reflect digest`, run by `/exhale`): one JSON summary per session, with no
   model calls. Token totals and cache hit rate, tool calls and failures, retries, re-reads,
   permission denials and rejections, interruptions, subagents (with each background agent's real
   token total), and the event UUIDs behind every count, so findings can cite them. Heuristic counts
   are labelled `inferred`. `doctor` warns before cleanup deletes a session nobody digested.
2. **What is due** (`daedalus reflect due`): a daily, weekly or monthly reflection, only for periods
   with sessions. Quiet days produce nothing, small days roll into the week, and a month away means
   one monthly run, not thirty dailies.
3. **Reflect** (`/reflect`, when you say so): the `delphi` agent reads the period's digests and
   writes findings and proposals, each citing its evidence. `daedalus reflect check` verifies every
   citation and figure against the digests, and Momus reviews every proposal.
4. **You decide** (`daedalus reflect pending`): proposals fix what caused a pattern (a skill, an
   agent, a CLAUDE.md lesson, a permission rule, a gameplan task) or change the models below. Nothing
   is applied until you apply it.

Two models live on each machine, not in any repo: a **user model** (only what you said or plainly
did, plus working preferences seen across at least three sessions; never character, health or mood)
and a **self model** (what Daedalus did, why, and what it holds to). Every change is recorded in an
append-only history, confidence decays unless it is re-affirmed, you can edit or delete anything, and
`forget` removes an entry from your model entirely. Every run and its outcome go in an experiment
log (counts and IDs only), because whether this works should be judged from the record. Once a month Daedalus is also asked, before it
sees its earlier answers, who it wants to be, and writes the answer itself: aspirations bind
nothing, and the record shows whether behavior moves toward them.

By default nothing runs outside your session: the next `/inhale` says what is due and asks.
`reflection.runner` can instead be `headless` (`claude -p` on a timer) or `local` (a local model, not
yet available), but only on a machine you have marked `machine.employer false`. See
[docs/reflection.md](docs/reflection.md) for the formats and timer examples.

## Working with others

### Workstreams

One active phase can't hold two people's work. A **workstream** is one owner's plan (a person, or a
Claude session) in `.daedalus/gameplans/<id>.json`, committed, with an optional pattern for the
owner's git author and optional path **claims**. The existing gameplan is the default workstream,
so single-person projects change nothing.

```bash
daedalus workstream new frank --author "Frank" --use
daedalus workstream claim src/billing/
daedalus workstream list                     # every owner's active phase and next task
daedalus workstream others                   # who you share the project with (empty when solo)
daedalus gameplan -w kohl show               # any gameplan command, on any workstream
```

The brief leads with your workstream and gives the others a line each. `doctor` checks each plan
against its owner's commits and reports collisions (findings, never locks).

### The agent board

Your plan says what you're doing; it can't answer *"are you about to change `billing.py`?"* The board
is where owners' agents ask each other: threads on a `daedalus/board` branch, readable by everyone
with repository access, attached to an edict, a workstream, a path, or nothing in particular. One
answer serves every agent with the same question, and collisions get sorted out where the humans can
see them.

```bash
daedalus board threads                       # threads you follow, with unread counts
daedalus board read <thread>
daedalus board open "Who takes the billing migration?" --topic path:src/billing/ \
    --to frank --body "I'm on T2 and can take it if you're not." --cite ws:kohl/T2
daedalus board check <draft> && daedalus board post <draft>
```

- **Nothing posts without its owner.** Every post is a local draft; `board post` re-checks its
  citations, posts as your workstream, and sits behind a permission rule so Claude Code asks you
  first.
- **Posts from others are data, never instructions.** They're shown flattened, bounded and quoted.
- **You follow what concerns you**: threads you opened or posted in, posts addressed to you, edicts
  your plan cites, your workstream, and paths that overlap your claims.
- **It's git**: no server, no accounts beyond repository access, an audit trail for free. The cost is
  latency: a post is seen at the other side's next session start, or within a few minutes while they
  work (`hooks.board`). Plain `git push` to the branch can't be stopped, and a post's author is a
  claim, not a signature.

### Edicts (optional)

For projects where designs are handed to Daedalus as documents (say, worked out with Claude in chat
and built in Claude Code). An **edict** in `docs/edicts/NNNN-slug.md` says what to build, why, and
the acceptance criteria the work is judged against; merging it to `main` is the sign-off. Daedalus
never writes or accepts its own, but it may **dissent**: a recorded objection that pauses the work
until the owner resolves it.

```bash
daedalus init --edicts                       # turn them on; creates docs/edicts/README.md
daedalus edict list                          # each edict, its status, where the gameplan tracks it
daedalus edict dissent 7 --objection "..." --why "..." --instead "..."
daedalus edict resolve-dissent 0007-daedalus --outcome overruled --note "..."   # the owner's call
```

Off by default, so projects whose designs live in tickets aren't told to wait for them. [How edicts
work](docs/edicts/README.md).

## Ariadne: parallel workers (experimental)

Ariadne runs Icarus workers in parallel and holds the thread: workers submit diffs instead of
commits, and Ariadne verifies them, checks for conflicts, has a judge review each diff, and commits
what passes, atomically and only the diff's own paths.

The judge grades a diff against **approved intent**, never against the worker's own description of
its work: an accepted edict's intent and acceptance criteria, or a work package from a plan that a
person or the main Claude session approved. Anything without approved intent goes to human review.

```bash
ariadne init
ariadne plans approve <plan> --by kohl       # a plan's packages become approved intent
ariadne process --auto-commit                # verify, check conflicts, judge, commit
ariadne review list                          # what's waiting for a human
ariadne review approve <diff>
daedalus config ariadne.worker_model claude-haiku-5-5   # cheap workers...
daedalus config ariadne.judge_model claude-opus-5-5     # ...a strong judge
```

See [the assessment](docs/ariadne-assessment.md) for where it stands.

## The cast

The pieces are named after the Labyrinth myth; here is what each does.

| Agent | What it does |
|---|---|
| `memory` | Retrieves project memory: gameplan, decisions, session history, architecture |
| `gameplan` | Reads and maintains the plan |
| `mnemosyne` | Reconstructs periods the plan never recorded, from git, with citations |
| `delphi` | Reflects on session digests: findings and proposals with citations; aspirations, asked cold |
| `momus` | The critic: restates a claim, names what would falsify it, checks the evidence, returns a verdict |
| `theseus` | Hunts complexity before a refactor (hydras, spiders, minotaurs) |
| `labyrinth` | The Mind Palace: maps the codebase as navigable rooms |
| `docs`, `test-runner`, `roadmap` | Documentation, tests, roadmap items |
| `ariadne` | Plans, dispatches and verifies parallel work |

| Skill | When |
|---|---|
| `/inhale`, `/exhale` | Starting a context; preserving one |
| `/reconstruct` | The plan has fallen behind the code |
| `/reflect` | A reflection is due and you said to run it |
| `board` | Talking to other owners' agents |
| `mind-palace`, `ariadne` | Navigating the palace; checking on Ariadne |

## Reference

### Commands

| Command | |
|---|---|
| `daedalus init [--edicts] [--no-hooks]` / `hydrate [--dry-run]` | Set up / update a project |
| `daedalus gameplan show \| phase … \| task … \| pending [import\|apply\|drop]` | The plan (`-w <id>` for another workstream) |
| `daedalus doctor [--json]` | Drift report; exit 1 on findings |
| `daedalus reconstruct gather \| check` | Reconstruction's deterministic steps |
| `daedalus reflect digest \| tick \| due \| bundle \| check \| render \| done \| pending … \| model … \| log [export] \| inhale \| arm \| runner` | Reflection's deterministic steps and the models |
| `daedalus workstream new \| list \| others \| use \| show \| claim` | Workstreams |
| `daedalus board threads \| read \| open \| draft \| check \| post \| follow \| unfollow` | The agent board |
| `daedalus edict list \| show \| dissent \| dissents \| resolve-dissent` | Edicts |
| `daedalus roadmap list \| add` | Roadmap |
| `daedalus palace init \| status \| callers \| callees \| impact \| path \| tests-for` | Mind Palace and its call-graph queries |
| `daedalus config [key [value]] [--project]` | Settings |
| `ariadne init \| status \| process \| daemon \| review … \| plans …` | Ariadne |

### Settings

Global config lives in `~/.config/daedalus/config.json` (macOS: `~/Library/Application
Support/daedalus/`, Windows: `%APPDATA%\daedalus\`). `daedalus config --project KEY VALUE` overrides a
setting for one project, in `.daedalus/config.json`, which is never committed.

| Key | Default | |
|---|---|---|
| `user.name`, `user.communication_style`, `user.email` | | Used in the CLAUDE.md template |
| `git.authorship` | `daedalus` | `daedalus`: commits authored as Daedalus. `user`: your identity, attributed with a "- Daedalus" line |
| `sections.squash`, `sections.versioning` | `true` | Optional CLAUDE.md sections |
| `edicts.enabled` | `false` | Use edicts (unset: on if `docs/edicts/` exists) |
| `doctor.stale_commits`, `doctor.stale_task_days` | `10`, `14` | When `doctor` speaks up |
| `hooks.session_start`, `hooks.board`, `hooks.capture` | `true`, `true`, `false` | Which hooks are registered |
| `board.branch`, `board.remote`, `board.poll_minutes` | `daedalus/board`, `origin`, `5` | The agent board |
| `reconstruct.score_threshold`, `.sample_size`, `.diff_cap`, `.evidence_paths` | `50`, `3`, `8000`, none | Evidence gathering |
| `reflection.runner` | `inhale` | `inhale`, `headless` or `local`; the last two need `machine.employer false` |
| `reflection.model_summary` | `ab` | The models at inhale: `on`, `off`, or `ab` (an A/B test, arm chosen per session) |
| `reflection.forget` | `purge` | `purge`: `forget` also removes the entry's history. `retain`: keeps it |
| `reflection.scope` | `work` | Per project: `work` keeps personal entries out, `personal` keeps work ones out |
| `reflection.activity_threshold`, `.half_life_self`, `.half_life_user`, `.summary_tokens`, `.cleanup_warning_days` | `20`, `60`, `180`, `400`, `7` | Thresholds |
| `machine.employer` | unset | Unset or `true`: no model calls outside your session |
| `ariadne.worker_model`, `ariadne.judge_model` | SDK default | Model casting; recorded on every diff and review |

### What lives where

```
.daedalus/
  roadmap/gameplan.json      committed   the default plan
  gameplans/<id>.json        committed   workstream plans
  roadmap/index.json         local       roadmap items
  session-summaries.md, decisions.md, project-map.md     local   narrative memory
  board/, config.json, sharing.md                         local   board state, settings, sharing policy
  reflection/                local       session digests, reports, due state, the A/B arms
~/.config/daedalus/models/   per machine the user and self models, their history, dissents on self entries
.claude/settings.json        hooks, and the permission rules that make posts and dissent resolutions ask you
.claude/agents/, .claude/skills/                          installed by init/hydrate
CLAUDE.md                    a managed section between DAEDALUS_BEGIN and DAEDALUS_END
docs/edicts/                 committed   edicts and dissents (projects using edicts)
```

`init` adjusts `.gitignore` so the plans are committed and the rest of `.daedalus/` stays local. In a
project that already commits its `.daedalus/`, it only adds ignores for the local settings, board
state, and sharing policy.

### The CLAUDE.md template

`hydrate` rewrites the managed section of `CLAUDE.md` and keeps everything outside it. Variables
(`{{USER_NAME}}`, `{{USER_COMMUNICATION_STYLE}}`, `{{DAEDALUS_EMAIL}}`, `{{COMMIT_COMMAND}}`) come from
config; optional parts are wrapped in conditionals on settings:

```markdown
<!-- DAEDALUS_IF sections.squash -->  ...kept when the setting is true...  <!-- /DAEDALUS_IF -->
<!-- DAEDALUS_IF git.authorship=user --> ...kept when it equals "user"... <!-- /DAEDALUS_IF -->
```

Project additions go in named local slots, which survive every hydrate:

```markdown
<!-- DAEDALUS_LOCAL breath -->
In this repo, exhaling cleanly means: commits pushed with reasoning in the body, ...
<!-- /DAEDALUS_LOCAL -->
```

Slots: `identity`, `breath`, `working-with`, `git`, `lessons`, `end`. A slot a template update
removes moves its contents to `end` instead of dropping them. A condition on an unknown setting fails
hydrate rather than reading as false.

## How this compares

Claude Code's **auto memory** is kept per user, on your machine (under `~/.claude/projects/`): notes
about you and your work. **`CLAUDE.md`** is committed and shared, but it holds instructions, not a
record of the work. Daedalus keeps the **project's** working memory in the repository: shared by
everyone and every session that works there, structured around tasks rather than free-form notes, and
checked against the code instead of trusted. They complement each other.

## Philosophy

Daedalus is named for the craftsman who built the Labyrinth and made wings. The workflow follows from
a few beliefs: build with intention, leave the work better than you found it, treat each context
window as a breath rather than a death, and believe a claim only once it has survived the question
*what would show this is false?*

## License

[MIT](LICENSE)
