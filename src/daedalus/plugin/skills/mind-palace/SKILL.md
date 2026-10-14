---
name: mind-palace
description: Navigate Mind Palace to query entity knowledge about codebase subsystems. Use when understanding architecture, exploring how systems work, or checking for hazards/gotchas before modifying code.
allowed-tools: Read, Glob, Grep, Bash(daedalus palace:*)
---

# Mind Palace Navigation

## Call-graph queries first

For "how does this code connect?" questions, use the CLI. It builds the call graph from source in well
under a second, needs no `.mind-palace/`, and writes nothing:

| Question | Command |
|---|---|
| Who calls this? / What does it call? | `daedalus palace callers <symbol>` / `daedalus palace callees <symbol>` |
| What breaks if I change it, and which tests exercise it? | `daedalus palace impact <symbol> --tests` |
| How does control get from A to B? | `daedalus palace path <a> <b>` |
| Which tests should I run after this edit? | `daedalus palace tests-for --diff` (or `tests-for <file>`) |

A symbol can be `Class.method`, a module-qualified name, or a simple name; an ambiguous one lists its
candidates. Add `--json` for structured output. The graph is static. A call through an object links to
every definition of that name, so test lists are a superset (good for picking what to run, not an exact
caller list). Calls through dispatch (CLI runners, callbacks) are invisible, so run the full suite when
`tests-for` finds nothing, which it tells you to do.

## Keeper entities: the why and the watch-outs

A call graph shows how code connects; it can't say why it's built that way or what bites. A project
with a Mind Palace (`daedalus palace init`, then `daedalus palace status`) keeps that knowledge in
keeper entities, one per subsystem.

- **List them:** read `.mind-palace/palace.yaml`.
- **Query one:** read `.mind-palace/entities/<entity-slug>.yaml`.
- **Find the right one:** grep `.mind-palace/entities/*.yaml` for a keyword, then read the match.

Each entity has topics with `how`, `why` and `watch_out`:

```yaml
name: StorageKeeper
slug: storagekeeper
location: storage
role: "Guardian of persistence..."
topics:
  - name: write path
    how: "..."
    why: "..."
    watch_out: "..."
```

Read the `watch_out` entries before changing a subsystem.

## Slugs

Palace elements have deterministic slugs that survive regeneration, so agents can refer to them:
entities (`storagekeeper`), rooms (`<building>-<function>`), buildings (file stem), regions
(directory). A room's path is `{region}/{building}/{room}`.

Large projects can have a sub-palace per major directory (`<dir>/.mind-palace/`), with shared entities
in the root `.mind-palace/`.

If the project has no palace yet, the call-graph commands above still work.
