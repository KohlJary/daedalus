---
name: ariadne
description: Query Ariadne orchestration layer - check diff status, conflicts, and verification results for parallel worker coordination.
allowed-tools: Bash, Read
---

# Ariadne Orchestration

Query the Ariadne bus for parallel worker coordination status.

## Quick Reference

**Check status**: `ariadne status`
**List pending diffs**: `ariadne diffs pending`
**List conflicts**: `ariadne conflicts`
**Process diffs**: `ariadne process`

## Bus Location

`/tmp/ariadne-bus/`

```
diffs/pending/    - Awaiting verification
diffs/verified/   - Passed checks, ready for merge
diffs/rejected/   - Failed verification
conflicts/        - Detected conflicts
merges/           - Merge resolutions
commits/          - Ready for atomic commit
```

## Status Output

```json
{
  "initialized": true,
  "diffs": {
    "pending": 2,
    "verified": 1,
    "rejected": 0
  },
  "conflicts": {
    "total": 1,
    "unresolved": 1
  },
  "merges": 0,
  "commits_ready": 0
}
```

## Diff Fields

Each diff JSON contains:
- `id`: Unique diff identifier
- `work_id`: Original work package ID
- `instance_id`: Icarus worker that created it
- `description`: What this diff does
- `status`: pending, verifying, verified, rejected, merged
- `files_added`, `files_modified`, `files_deleted`: Affected files
- `line_changes`: Line ranges modified per file
- `causal_chain`: Affected functions/modules for verification
- `verification_result`: Type check, lint, test outcomes

## Conflict Fields

- `id`: Conflict identifier
- `diff_a_id`, `diff_b_id`: The conflicting diffs
- `conflict_type`: FILE_OVERLAP, LINE_OVERLAP, SEMANTIC
- `affected_files`: Files with conflicts
- `affected_lines`: Specific line ranges
- `suggested_strategy`: SEQUENTIAL, INTERLEAVE, ESCALATE, REJECT

## Common Tasks

**Initialize the bus** (if not done):
```bash
ariadne init
```

**View a specific diff**:
```bash
cat /tmp/ariadne-bus/diffs/pending/<id>.json | jq .
```

**Process with auto-commit**:
```bash
ariadne process --auto-commit
```

**Run as daemon**:
```bash
ariadne daemon --interval 5 --auto-commit
```

## Integration

Workers submit to Ariadne with:
```bash
icarus-worker --ariadne --prompt "..."
```

This generates a diff, extracts causal chain, and submits to the bus instead of committing directly.
