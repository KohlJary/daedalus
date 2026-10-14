# Daedalus

**Claude Code that remembers.** Every Claude Code session normally starts from zero: no memory of yesterday's decisions, last week's architecture discussion, or what was half-finished when the context ran out. Daedalus gives your project a persistent working memory, a plan that survives context compaction, and a consistent collaborator identity, so each session picks up where the last one left off.

It's a Claude Code plugin plus a small CLI. Everything it keeps is plain files in your repo.

At the center is the **gameplan**: the record of what is built, in progress, and next, committed with the code. Every session starts from it, and `daedalus doctor` says when it has fallen behind the commits. Working sessions update it as they finish tasks; hooks and reconstructions never write to it, they only propose changes for you to apply or drop.

**How this differs from what Claude Code already has.** Claude Code's auto memory is kept per user, on your machine (under `~/.claude/projects/`): notes about you and your work. `CLAUDE.md` is committed and shared, but it holds instructions, not a record of the work. Daedalus keeps the project's working memory in the repository, so it is shared by everyone and every session that works there (including Claude in chat reading the repo), and it is structured around tasks rather than free-form notes. They complement each other.

## At a glance

The pieces are named after the Labyrinth myth. Here's what each one actually does:

| Name | What it is | Status |
|------|-----------|--------|
| **Gameplan** | The record of state: phases, tasks, and their resolutions, committed so every session reads the same plan. A session-start hook leads with it and `daedalus doctor` flags drift | Core |
| **Daedalus** | The collaborator identity Claude adopts, plus the workflow it follows (including the `exhale`/`inhale` session rituals) | Core |
| **Memory** | Session summaries, decisions, and a project map in `.daedalus/`: the narrative around the gameplan | Core |
| **Roadmap** | File-based task tracking that gameplan phases group into | Core |
| **Edicts** | Design decisions handed to Daedalus as reviewed docs in `docs/edicts/` ([how they work](docs/edicts/README.md)). Opt-in: `daedalus init --edicts` | Optional |
| **Mind Palace** (Labyrinth) | Maps your codebase as navigable rooms for spatial-semantic navigation | Available |
| **Theseus** | Code-health analysis that hunts complexity hot spots | Available |
| **Momus** | A critic agent that checks claims against evidence | Available |
| **Icarus** | Parallel worker instances that each take one piece of a job | Experimental |
| **Ariadne** | Orchestrates Icarus workers: collects diffs, detects conflicts, verifies, reviews, merges | Experimental ([assessment](docs/ariadne-assessment.md)) |

If you only use the core pieces, you get most of the value.

## Installation

```bash
pip install daedalus-cli
```

For Icarus parallel workers (optional):
```bash
pip install "daedalus-cli[sdk]"
```

Requires Python 3.10+ and [Claude Code](https://claude.com/claude-code).

## Quick Start

```bash
# Initialize Daedalus in your project
cd your-project
daedalus init

# Configure your name (used in templates)
daedalus config user.name "Your Name"

# Start Claude Code
claude
```

## What It Does

### Daedalus Identity

When you run Claude Code in a Daedalus-initialized project, Claude adopts the **Daedalus** identity - the builder/craftsman. This provides:

- **Context as Breath** - A mental model for handling context limits gracefully
- **Git Workflow** - Branch-based development with signed commits
- **Persistent Memory** - Session summaries, decisions, and project understanding that survives across sessions

### Memory that stays current

Memory tools usually fail quietly: the notes stop being written during the busiest weeks, and nothing says so. Daedalus is built around that failure.

- **The gameplan is the record of state**, committed with the code. When a task ships, its resolution (with commit hashes) is recorded on the task. Edicts link to it with an `edict` field, so "is this built?" has one answer.
- **A session-start hook** (registered by `init`/`hydrate` in `.claude/settings.json`) prints the active phase, the next task, any drift, and the latest session note before the session begins. `/inhale` does the full pickup and `/exhale` preserves the session before a breakpoint.
- **`daedalus doctor`** checks the plan against the repository: commits since the gameplan was last updated, a finished phase left open, tasks stuck in progress, accepted edicts the gameplan doesn't track, packages the project map never mentions, a gitignored gameplan. It exits non-zero when it finds something, so it can run in CI.
- **Reconstruction** (`/reconstruct`) recovers a period the gameplan never recorded. `daedalus reconstruct gather` collects the evidence (every commit, with a score for how much its message says and the diff where it says little), the `mnemosyne` agent proposes the missing phases, tasks and status changes with every entry citing its commits and labelled `shown`, `inferred` or `unknown`, `daedalus reconstruct check` validates the proposal against the repository, and Momus reviews it. You import it into `daedalus gameplan pending` and apply what you agree with. [A worked example](docs/examples/wonderland-reconstruction/) rebuilt five weeks and 95 commits of another project.
- **An optional capture hook** (`hooks.capture`, off by default) runs when a session ends or compacts and proposes gameplan updates for tasks that new commits name. Proposals wait in `daedalus gameplan pending` until you apply or drop them.

### Project Structure

After `daedalus init`, your project gets:

```
.daedalus/
  roadmap/
    gameplan.json        # Record of state (committed; init un-ignores it if needed)
    index.json           # Project tasks and priorities
  session-summaries.md   # Narrative of previous sessions
  project-map.md         # Architecture understanding
  decisions.md           # Key decisions with rationale

.claude/settings.json    # SessionStart hook: `daedalus hook session-start`
.claude/skills/          # exhale, inhale, and the other plugin skills

.claude/agents/
  memory.md              # Memory retrieval agent
  labyrinth.md           # Mind Palace navigation
  theseus.md             # Code complexity analysis
  roadmap.md             # Project management
  docs.md                # Documentation exploration
  test-runner.md         # Test generation
  momus.md               # Claim and result critic
  mnemosyne.md           # Memory reconstruction
  gameplan.md            # Phase plan queries
  ariadne.md             # Parallel worker orchestration

CLAUDE.md                # Injected Daedalus workflow section
```

### Bundled Agents

| Agent | Purpose |
|-------|---------|
| `memory` | Retrieve persistent memory (project-map, sessions, decisions) |
| `labyrinth` | Mind Palace - spatial-semantic codebase mapping |
| `theseus` | Code health analysis and complexity hunting |
| `roadmap` | Query and manage project tasks |
| `docs` | Documentation and implementation exploration |
| `test-runner` | Generate and maintain tests |
| `ariadne` | Parallel worker orchestration (planning, dispatch, verification) |
| `momus` | Critic: restates a claim, names its falsifier, checks the evidence, returns a verdict |
| `gameplan` | Query and update the phase plan that survives context compaction |

### Theseus in Action

Theseus navigates your codebase like the mythological hero navigating the Labyrinth, hunting complexity monsters before they become problems:

```
> Have theseus analyze the auth module before we refactor it

Theseus analyzing src/auth/...

COMPLEXITY MONSTERS FOUND:

🐉 HYDRA (High Coupling) - src/auth/oauth.py:authenticate()
   - 12 external dependencies
   - Touches 3 database tables directly
   - Recommendation: Extract OAuthProvider interface

🕷️ SPIDER (Deep Nesting) - src/auth/permissions.py:check_access()
   - 6 levels of nested conditionals
   - Cyclomatic complexity: 23
   - Recommendation: Extract to permission strategies

⚡ MINOTAUR (God Function) - src/auth/session.py:handle_request()
   - 340 lines, does authentication + authorization + logging
   - Recommendation: Split into AuthMiddleware, SessionManager, AuditLogger

SAFE PATHS:
✓ src/auth/tokens.py - Clean, single responsibility
✓ src/auth/crypto.py - Well-isolated utilities

Would you like me to create a refactoring plan for the Hydra first?
```

### Ariadne Orchestration (Experimental)

Ariadne is the orchestration layer for parallel Icarus workers. When multiple workers make changes simultaneously, Ariadne:

1. **Collects diffs** instead of commits - workers submit their changes to Ariadne's bus
2. **Detects conflicts** - file-level and line-level overlap detection
3. **Verifies changes** - causal slice verification (type check, lint, tests on affected code only)
4. **Merges atomically** - combines verified diffs into single commits

```bash
# Initialize the Ariadne bus
ariadne init

# Check status
ariadne status

# Process pending diffs (one-shot)
ariadne process --auto-commit

# Run as daemon
ariadne daemon --interval 5 --auto-commit
```

The mythology: Ariadne gave Theseus the thread that guided him through the Labyrinth. Here, she holds the thread that coordinates parallel workers so their changes don't collide.

## CLI Commands

### Project Setup

```bash
# Initialize Daedalus in current directory
daedalus init

# Update the CLAUDE.md template, agents and skills (after plugin updates)
daedalus hydrate

# See what hydrate would change, without writing anything
daedalus hydrate --dry-run
```

`init` and `hydrate` install the plugin's skills into `.claude/skills/` (`--no-skills` to skip),
including `exhale` and `inhale`, the session rituals behind Context as Breath (edict 0004): exhale
preserves the session's work before a breakpoint or `/compact`, inhale picks it back up. Projects add
their own steps in CLAUDE.md, in a paragraph beginning "In this repo, exhaling cleanly means".

### Edicts (opt-in)

```bash
daedalus init --edicts        # turn edicts on here; creates docs/edicts/README.md and dissents/
daedalus edict list           # every edict, its status, and where the gameplan tracks it
daedalus edict show 7         # one edict, plus the gameplan entries that cite it
daedalus edict dissent 7 --objection "..." --why "..." --instead "..."   # pauses work on 7
daedalus edict dissents       # open dissents (--all for resolved ones too)
daedalus edict resolve-dissent 0007-daedalus --outcome overruled --note "..."   # the owner's call
```

Ariadne only auto-commits diffs with **approved intent**: an accepted edict's Intent and
Acceptance criteria, or a work package from an approved plan
(`python -m daedalus.ariadne.orchestrator plans approve <plan> --by <you or the main session>`).
The judge grades against that, never against the worker's own description; anything without it
goes to human review. Editing a plan after approval voids the approval.

Edicts are off by default, so CLAUDE.md doesn't tell Daedalus to wait for them in projects whose
designs live in tickets or issues. A project that already has `docs/edicts/` keeps them (hydrate
says so and suggests setting `edicts.enabled`).

### Gameplan and drift

```bash
daedalus gameplan show                               # active phase, tasks, edict links
daedalus gameplan phase add p2 "Memory backbone" --edict 0007
daedalus gameplan task add T1 "Doctor" --edict 0007
daedalus gameplan task status T1 done --resolution "Shipped in b1d1733"
daedalus gameplan pending                            # proposed updates
daedalus gameplan pending apply P1                   # or: drop P1, apply all
daedalus doctor                                      # drift report; exit 1 if anything found

# Reconstruction (the /reconstruct skill runs these with the mnemosyne and momus agents)
daedalus reconstruct gather                          # evidence for the gap since the gameplan's last update
daedalus reconstruct gather --since 2026-06-01 --until 2026-06-30 --author Frank
daedalus reconstruct check .daedalus/reconstruction/proposal-....json
daedalus gameplan pending import .daedalus/reconstruction/proposal-....json
```

**Workstreams** let several people or sessions plan in one repository without sharing a single
active phase: each owner gets a committed plan in `.daedalus/gameplans/<id>.json`.

```bash
daedalus workstream new memory --kind session --author "memory-session" --use
daedalus workstream list                             # every owner's active phase and next task
daedalus gameplan -w ariadne show                    # any gameplan command, on any workstream
daedalus workstream claim src/daedalus/ariadne/      # paths you intend to change
```

The brief leads with your workstream and lists the others in a line each (up to eight; the rest
are counted). `doctor` checks drift per workstream, counting only the owner's commits when the
workstream has a `--author` pattern (the default workstream and owners without one count every
commit), and reports collisions: two workstreams with open or planned work on the same edict, or
overlapping claims. Collisions are findings, never locks.

`init` and `hydrate` register the session-start hook (`--no-hooks` to skip; `hydrate --dry-run`
lists it). They merge into existing `.claude/settings.json` and never overwrite a file they can't parse.

### Configuration

```bash
# View all config
daedalus config

# View specific key
daedalus config user.name

# Set value
daedalus config user.name "Your Name"
daedalus config user.communication_style "Direct, technical"

# Template settings for this project only (.daedalus/config.json)
daedalus config --project                         # settings in effect here
daedalus config --project git.authorship user
daedalus config --project sections.squash false
```

### Roadmap

```bash
# List all items
daedalus roadmap list

# Filter by status
daedalus roadmap list --status ready

# Add new item
daedalus roadmap add "Implement feature X" --priority P1 --type feature
```

### Mind Palace

```bash
# Initialize Mind Palace for codebase navigation
daedalus palace init

# Check palace status
daedalus palace status
```

## Configuration

Config is stored in platform-appropriate location:
- Linux: `~/.config/daedalus/config.json`
- macOS: `~/Library/Application Support/daedalus/config.json`
- Windows: `%APPDATA%\daedalus\config.json`

### Available Settings

| Key | Description | Default |
|-----|-------------|---------|
| `user.name` | Your name (used in templates) | "the user" |
| `user.communication_style` | How you prefer to communicate | "Not specified" |
| `user.email` | Email for git commits | git config user.email |
| `icarus.enabled` | Enable parallel workers | false |
| `ariadne.enabled` | Enable Ariadne orchestration | false |
| `ariadne.worker_model` | Model for Icarus workers; unset (or `default`) uses the SDK default. Recorded on each diff | unset |
| `ariadne.judge_model` | Model for the semantic judge; unset uses the SDK default. Recorded on each review the judge makes | unset |
| `git.authorship` | `daedalus`: commits authored as Daedalus (`--author`). `user`: authored as your git identity, with a `- Daedalus` sign-off in the body | daedalus |
| `sections.squash` | Include the Squash for Merge section in CLAUDE.md | true |
| `sections.versioning` | Include the Versioning section in CLAUDE.md | true |
| `edicts.enabled` | Use edicts: include the Edicts section in CLAUDE.md and track edicts in `doctor` (unset: on if `docs/edicts/` exists) | false |
| `doctor.stale_commits` | Commits after the gameplan's last update before `doctor` reports it | 10 |
| `doctor.stale_task_days` | Days a task may stay in progress before `doctor` reports it | 14 |
| `hooks.session_start` | Register the session-start brief hook | true |
| `hooks.capture` | Register the capture hook (SessionEnd, PreCompact) | false |
| `reconstruct.score_threshold` | Commits whose message scores below this (0-100) get their diff in the evidence bundle | 50 |
| `reconstruct.sample_size` | High-scoring commits that get diffs anyway, to check the score | 3 |
| `reconstruct.diff_cap` | Max characters of patch per commit in the bundle | 8000 |
| `reconstruct.evidence_paths` | Paths outside git to list as evidence (set in `.daedalus/config.json`) | none |

The `git`, `sections`, `edicts`, `doctor`, `hooks`, and `reconstruct` settings can be overridden per project in
`.daedalus/config.json` (`daedalus config --project KEY VALUE`), deep-merged over the global config.
A work repo and a personal repo usually want different authorship.

## Template Variables

The `CLAUDE.md` template supports these variables:

| Variable | Source |
|----------|--------|
| `{{USER_NAME}}` | `user.name` config |
| `{{USER_COMMUNICATION_STYLE}}` | `user.communication_style` config |
| `{{DAEDALUS_EMAIL}}` | `user.email` config or git user.email |
| `{{COMMIT_COMMAND}}` | `git commit --author="Daedalus <...>"`, or `git commit` with `git.authorship user` |

### Conditional sections

Optional parts of the template are wrapped in conditionals on the settings above:

```markdown
<!-- DAEDALUS_IF sections.squash -->
...kept when sections.squash is true...
<!-- /DAEDALUS_IF -->
<!-- DAEDALUS_IF git.authorship=user -->
...kept when git.authorship is "user"...
<!-- /DAEDALUS_IF -->
```

A condition on a setting that doesn't exist fails hydrate instead of reading as false. Blocks don't nest.

### Local slots: project additions that survive hydrate

`hydrate` replaces the managed section between `DAEDALUS_BEGIN` and `DAEDALUS_END`. Project-specific
additions go inside the named `DAEDALUS_LOCAL` slots, which hydrate carries over by name:

```markdown
## Context as Breath
...
<!-- DAEDALUS_LOCAL breath -->
In this repo, exhaling cleanly means: commits pushed with reasoning in the body, ...
<!-- /DAEDALUS_LOCAL -->
```

Slots: `identity`, `breath`, `working-with`, `git`, `lessons`, `end`. If a template update removes a
slot, its contents move to `end` (under a comment naming the old slot) rather than being dropped.
Anything below `DAEDALUS_END` is never touched. Use `daedalus hydrate --dry-run` to check before moving
existing customizations into slots.

## Philosophy

Daedalus is named after the mythological master craftsman who built the Labyrinth and invented wings. The plugin embodies this through:

- **Building with intention** - Structured workflows, not chaotic hacking
- **Persistent memory** - Knowledge survives across sessions
- **Spatial navigation** - The Mind Palace maps codebases as navigable spaces
- **Context as breath** - Each session is a breath cycle, not a death sentence

## License

[MIT](LICENSE)
