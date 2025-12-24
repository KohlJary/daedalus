# Daedalus Claude Code Plugin

Claude Code extensions for AI-assisted development.

## Overview

Daedalus provides a suite of specialized agents, commands, and skills that extend Claude Code for structured software development workflows.

## Agents

| Agent | Description |
|-------|-------------|
| `design-analyst` | UX/UI analysis with Playwright browser automation |
| `docs` | Documentation exploration and codebase discovery |
| `icarus` | Parallel worker identity for distributed execution |
| `labyrinth` | Mind Palace MUD navigation - spatial codebase understanding |
| `memory` | Project memory management across sessions |
| `roadmap` | Project planning and work item tracking |
| `test-runner` | Test generation and execution |
| `theseus` | Code complexity analysis and refactoring guidance |

## Commands

| Command | Description |
|---------|-------------|
| `/memory` | View and update project memory (`.daedalus/`) |
| `/palace` | Navigate Mind Palace entities |
| `/theseus` | Analyze code health and complexity |

## Skills

### Mind Palace

Spatial-semantic codebase navigation that represents code as a navigable MUD environment. Entities in rooms can be queried about their domain knowledge.

## Installation

The plugin is bundled with the Daedalus package. Use `daedalus hydrate` to install agents and templates into a project:

```bash
daedalus hydrate
```

This copies agents to `.claude/agents/` and injects the Daedalus workflow template into `CLAUDE.md`.

## Project Memory

Daedalus maintains project memory in `.daedalus/`:

| File | Purpose |
|------|---------|
| `session-summaries.md` | What was done in previous sessions |
| `project-map.md` | Architecture understanding |
| `decisions.md` | Key decisions with rationale |
| `lessons.md` | Things learned the hard way |
| `warnings.md` | Fragile areas needing careful handling |
| `notes.md` | Quick observations and cliff notes |
| `plans/` | Implementation plans (YAML front matter with status) |

## Core Package

The `daedalus.labyrinth` Python package provides the Mind Palace implementation:

```python
from daedalus.labyrinth import Navigator, PalaceStorage, Cartographer

# Initialize a palace for a project
storage = PalaceStorage(Path("/path/to/project"))
palace = storage.initialize("my-project")

# Navigate
nav = Navigator(palace)
print(nav.execute("look"))
print(nav.execute("enter core-module"))
print(nav.execute("ask DatabaseKeeper about migrations"))

# Build/update the palace
cartographer = Cartographer(palace, storage)
cartographer.map_module("src/database", region="persistence")
```

## Extending

To add custom agents, create `.md` files in `.claude/agents/` with YAML front matter:

```yaml
---
name: my-agent
description: "What this agent does"
tools: Read, Grep, Glob
model: haiku
---

Agent instructions here...
```
