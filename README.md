# Daedalus

A Claude Code plugin for structured development workflows. Provides persistent memory, Mind Palace codebase navigation, and project management tools.

## Installation

```bash
pip install daedalus
```

For Icarus parallel workers (optional):
```bash
pip install daedalus[sdk]
```

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

## CLI Commands

### Project Setup

```bash
# Initialize Daedalus in current directory
daedalus init

# Update templates and agents (after plugin updates)
daedalus hydrate
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

## Template Variables

The `CLAUDE.md` template supports these variables:

| Variable | Source |
|----------|--------|
| `{{USER_NAME}}` | `user.name` config |
| `{{USER_COMMUNICATION_STYLE}}` | `user.communication_style` config |
| `{{DAEDALUS_EMAIL}}` | `user.email` config or git user.email |

## Philosophy

Daedalus is named after the mythological master craftsman who built the Labyrinth and invented wings. The plugin embodies this through:

- **Building with intention** - Structured workflows, not chaotic hacking
- **Persistent memory** - Knowledge survives across sessions
- **Spatial navigation** - The Mind Palace maps codebases as navigable spaces
- **Context as breath** - Each session is a breath cycle, not a death sentence

## License

[Hippocratic License 3.0](https://firstdonoharm.dev/) - Software that can't be used to harm people.
