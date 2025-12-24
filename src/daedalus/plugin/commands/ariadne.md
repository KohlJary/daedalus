---
description: Query Ariadne orchestration - plan features, track progress, manage diffs, resolve conflicts
---

Ariadne is the orchestration layer for parallel Icarus workers. She holds the thread through the labyrinth - from feature design to atomic commits.

## Usage

### Planning
- `/ariadne plan <feature>` - Create implementation plan for a feature
- `/ariadne plans` - List active implementation plans
- `/ariadne approve <plan-id>` - Approve a plan for dispatch
- `/ariadne progress [plan-id]` - Show feature progress

### Dispatch
- `/ariadne dispatch <plan-id>` - Dispatch ready work packages
- `/ariadne workers` - Show active Icarus workers

### Diffs
- `/ariadne` or `/ariadne status` - Show current orchestration status
- `/ariadne diffs` - List pending diffs awaiting verification
- `/ariadne conflicts` - Show detected conflicts needing resolution
- `/ariadne process` - Process all pending diffs (verify, detect conflicts)
- `/ariadne commit` - Create atomic commit from verified diffs

## Commands

### Status

Show overall orchestration status:

```bash
ariadne status
```

### List Diffs

Show pending diffs:

```bash
ariadne diffs pending
```

Show verified diffs ready for merge:

```bash
ariadne diffs verified
```

### Show Conflicts

List conflicts between diffs:

```bash
ariadne conflicts
```

### Process Diffs

Run verification on all pending diffs:

```bash
ariadne process
```

With auto-commit:

```bash
ariadne process --auto-commit
```

### Initialize

If not yet initialized:

```bash
ariadne init
```

## What Ariadne Does

1. **Plans features** converting requests into work packages with dependencies
2. **Dispatches work** sending packages to Icarus workers respecting dependencies
3. **Tracks progress** updating roadmap items as work completes
4. **Collects diffs** from workers instead of letting them commit
5. **Detects conflicts** between parallel changes (file-level, line-level)
6. **Verifies changes** using causal slicing (fast, targeted checks)
7. **Merges atomically** combining verified diffs into clean commits

## Autonomy Levels

- **supervised**: All plans require approval before dispatch
- **hybrid** (default): Small tasks auto-dispatch, larger ones need approval
- **full**: Fully autonomous operation

Configure via `daedalus config ariadne.autonomy <level>`

## Conflict Types

- **FILE_OVERLAP**: Same file modified by multiple workers
- **LINE_OVERLAP**: Same lines modified (needs manual resolution)
- **SEMANTIC**: Delete/modify conflict

## The Thread

Ariadne gave Theseus the thread that guided him through the Labyrinth to slay the Minotaur. Here, she coordinates parallel workers so their changes don't collide.
