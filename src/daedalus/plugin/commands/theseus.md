---
description: Navigate the labyrinth - analyze code health, slay complexity monsters, detect orphans, trace impact
---

Theseus navigates the codebase labyrinth to identify refactoring opportunities, complexity beasts, and orphan code.

## Usage

### Basic Analysis
- `/theseus <file>` - Analyze a single file
- `/theseus backend/` - Scan a directory
- `/theseus report` - Generate full health report

### Ghost Hunting (Orphan Detection)
- `/theseus ghosts` - Find orphan code in current project
- `/theseus ghosts backend/` - Find orphans in specific directory

### Impact Analysis
- `/theseus impact <function>` - Show what's affected if function changes
- `/theseus slice <function>` - Extract causal slice (callers + callees)
- `/theseus paths <from> <to>` - Find call paths between functions

## What Theseus Does

Theseus analyzes Python files for:
- **Size thresholds**: Lines, functions, classes, imports
- **Complexity**: Cyclomatic complexity, nesting depth
- **Extraction opportunities**: Classes/functions that should be in their own modules
- **Orphan code**: Functions never called (dead code)
- **Impact radius**: What's affected when code changes

## Monster Types

| Monster | What | Detection |
|---------|------|-----------|
| HYDRA | High coupling | >15 imports, >6 params |
| SPIDER | Deep nesting | >4 levels, complexity >15 |
| MINOTAUR | God function | >50 lines, multiple concerns |
| CERBERUS | Multiple entry points | Large switch/match |
| CHIMERA | Mixed abstractions | SQL + business logic |
| GHOST | Orphan code | Zero callers |

## Example Commands

### File Analysis
```bash
# Analyze a specific file
python -m backend.refactor_scout analyze backend/main_sdk.py

# Generate report for directory
python -m backend.refactor_scout report backend/
```

### Orphan Detection (Ghosts)
```python
from pathlib import Path
from daedalus.labyrinth import detect_orphans, format_orphan_report

summary = detect_orphans(Path("backend/"))
print(format_orphan_report(summary))

# Results:
# HIGH CONFIDENCE: Likely dead code
# MEDIUM CONFIDENCE: May be called dynamically
# Framework entry points auto-filtered
```

### Impact Analysis
```python
from pathlib import Path
from daedalus.labyrinth import CallGraph, ImpactAnalysis, load_graph

# Load or build call graph
graph = CallGraph.from_project(Path("backend/"))
impact = ImpactAnalysis(graph)

# What's affected if we change this function?
result = impact.callers("memory.add_message", max_depth=3)
print(result.summary())
# Shows all transitive callers up to 3 levels

# What does this function depend on?
deps = impact.callees("memory.add_message", max_depth=3)
```

### Causal Slice
```python
from pathlib import Path
from daedalus.labyrinth import CausalSlicer

slicer = CausalSlicer(Path("backend/"))

# Extract everything causally related to a function
# backward_depth = how far to trace callers
# forward_depth = how far to trace callees
bundle = slicer.extract("memory.add_message", backward_depth=3, forward_depth=2)

# Get affected files
print(bundle.affected_files)  # {'memory.py', 'conversations.py', ...}

# Get as context for focused review
context = bundle.to_context()
```

### Path Finding
```python
from daedalus.labyrinth import CallGraph

graph = CallGraph.from_project(Path("backend/"))
paths = graph.find_paths("api.send_message", "memory.store")
print(f"Found {len(paths.paths)} paths, shortest: {paths.shortest_length} hops")
```

## Extraction Commands

If Theseus identifies extraction opportunities:

```bash
# Extract a class to its own file
python -m backend.refactor_scout extract-class <source> <ClassName> --branch --commit

# Extract functions to a new module
python -m backend.refactor_scout extract-functions <source> func1,func2 -o <target> --branch --commit
```

The `--branch` flag creates a refactor branch, `--commit` commits the extraction.

## Interpreting Results

- **CRITICAL**: File significantly exceeds thresholds, should be refactored before adding more code
- **WARNING**: File is getting large, consider cleanup
- **HEALTHY**: File is within acceptable limits

Focus on high-priority extraction opportunities first - these provide the most benefit.

## When to Use Impact Analysis

Before modifying core functions:
1. Run `/theseus impact <function>` to see blast radius
2. Review affected code paths
3. Update tests for affected areas
4. Consider if change warrants feature flag

For safe refactoring:
1. Run `/theseus slice <function>` to get full context
2. Understand all callers and callees
3. Ensure tests cover the slice
4. Make changes within understood boundaries
