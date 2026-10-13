# Daedalus

**Claude Code that remembers.** Every Claude Code session normally starts from zero: no memory of yesterday's decisions, last week's architecture discussion, or what was half-finished when the context ran out. Daedalus gives your project a persistent working memory, a plan that survives context compaction, and a consistent collaborator identity, so each session picks up where the last one left off.

It's a Claude Code plugin plus a small CLI. Everything it keeps is plain files in your repo.

## At a glance

The pieces are named after the Labyrinth myth. Here's what each one actually does:

| Name | What it is | Status |
|------|-----------|--------|
| **Daedalus** | The collaborator identity Claude adopts, plus the memory files and workflow it follows | Core |
| **Memory** | Session summaries, decisions, and a project map in `.daedalus/` | Core |
| **Roadmap & Gameplan** | File-based task tracking, and a phase plan that tells a fresh session what to do next | Core |
| **Edicts** | Design decisions handed to Daedalus as reviewed docs in `docs/edicts/` ([how they work](docs/edicts/README.md)) | New |
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

### Project Structure

After `daedalus init`, your project gets:

```
.daedalus/
  session-summaries.md   # What happened in previous sessions
  project-map.md         # Architecture understanding
  decisions.md           # Key decisions with rationale
  observations.json      # Self-observations and growth edges
  roadmap/
    index.json           # Project tasks and priorities

.claude/agents/
  memory.md              # Memory retrieval agent
  labyrinth.md           # Mind Palace navigation
  theseus.md             # Code complexity analysis
  roadmap.md             # Project management
  docs.md                # Documentation exploration
  test-runner.md         # Test generation
  momus.md               # Claim and result critic
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

# Update templates and agents (after plugin updates)
daedalus hydrate

# See what hydrate would change, without writing anything
daedalus hydrate --dry-run
```

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
| `git.authorship` | `daedalus`: commits authored as Daedalus (`--author`). `user`: authored as your git identity, with a `- Daedalus` sign-off in the body | daedalus |
| `sections.squash` | Include the Squash for Merge section in CLAUDE.md | true |
| `sections.versioning` | Include the Versioning section in CLAUDE.md | true |

The `git` and `sections` settings can be overridden per project in `.daedalus/config.json`
(`daedalus config --project KEY VALUE`), deep-merged over the global config. A work repo and a
personal repo usually want different authorship.

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
