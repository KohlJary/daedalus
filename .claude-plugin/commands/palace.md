---
allowed-tools: Read, Glob, Grep, Bash(daedalus palace:*)
description: Navigate the Mind Palace - call-graph queries, keeper entities, architecture, drift
---

# Mind Palace Navigation

Two kinds of codebase knowledge:

- **How code connects** (no palace needed): the call-graph CLI, built from source on every call.
- **Why it's built that way, and what bites** (needs a palace): keeper entities with HOW / WHY / WATCH_OUT topics, in `.mind-palace/`.

## Usage

### `/palace callers <symbol>`, `/palace impact <symbol>`, `/palace path <a> <b>`, `/palace tests-for`
Run the matching CLI command and summarize:
- `daedalus palace callers <symbol>` / `daedalus palace callees <symbol>`
- `daedalus palace impact <symbol> --tests` (what a change affects, and which tests reach it)
- `daedalus palace path <a> <b>` (call paths, shortest first)
- `daedalus palace tests-for --diff` (tests to run for the working tree's changes)

A symbol can be `Class.method`, module-qualified, or a simple name; ambiguous names list their candidates. Test lists are a superset (calls through objects link every same-named definition); when nothing is found, say to run the full suite.

### `/palace` - Show available entities
List the keeper entities in `.mind-palace/palace.yaml`. If there is no palace, say so and suggest `daedalus palace init` (the call-graph commands above still work).

### `/palace ask <Entity> about <topic>` - Query an entity
1. Read `.mind-palace/entities/<entity>.yaml` (slug or lowercase name)
2. Find the topic in `topics` (partial match OK)
3. Show its `how`, `why`, and `watch_out`
4. If the topic isn't found, list the entity's topics

### `/palace topics <Entity>`
List the topic names in `.mind-palace/entities/<entity>.yaml`.

### `/palace find <keyword>`
Grep `.mind-palace/entities/*.yaml` for the keyword and report which entities mention it, in what context.

### `/palace go <path>`
Navigate by slug path `{region}/{building}/{room}` (e.g. `server/storage/storage-save-record`), or a room slug alone to search all sub-palaces.

## Entity YAML Format

```yaml
name: StorageKeeper
slug: storagekeeper
location: server/storage/
role: "Guardian of persistence..."
topics:
  - name: write path
    how: "..."
    why: "..."
    watch_out: "..."
```

## File Locations

- `.mind-palace/palace.yaml` - Palace index (entity list)
- `.mind-palace/entities/*.yaml` - Entity definitions with topics
- `<dir>/.mind-palace/` - Optional sub-palaces for major directories
