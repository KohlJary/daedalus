# TUI design coverage

How much of Daedalus the TUI design (the `.oph` files here) shows. Refresh
this whenever the diagrams or the CLI change, and add a row to History.

## Legend

| Mark | Meaning |
|------|---------|
| ● | Shown: a diagrammed view covers it |
| ◐ | Partial: mentioned (a tab label, a single line), but not diagrammed |
| → | Delegated to Claude: a write or agent operation reached through the Claude pane, by design |
| ○ | Missing: Kohl would plausibly want to see it, and no view does |
| – | Out of scope: setup or hook plumbing |

The Claude pane technically makes *everything* reachable, so → is not
coverage. The metric that matters is **direct coverage**: ● and ◐ out of
everything that isn't → or –.

## CLI (50 leaf commands, `daedalus` 0.2.0)

| Group | ● | ◐ | → | ○ | – |
|-------|---|---|---|---|---|
| board | threads, read, follow, unfollow | | open, draft, post, check | | |
| edict | list, show | dissents | dissent | resolve-dissent | |
| gameplan | show, phase list, pending apply, pending drop | | pending import, phase activate/add/status, task add/defer/status | | |
| workstream | list, show | others | claim, new | use | |
| roadmap | | list | add | | |
| doctor | doctor | | | | |
| hydrate | | hydrate (as a Health fix) | | | |
| palace | | | callers, callees, impact, path, tests-for | status, languages | init |
| reconstruct | | | check, gather | | |
| config | | | | config | |
| digest | | | | digest | |
| init, hook | | | | | init, hook board/capture/session-start |
| **Total** | **13** | **4** | **22** | **6** | **5** |

## Beyond the CLI (10 surfaces)

| Surface | Mark | Note |
|---------|------|------|
| Claude Code session | ● | `claude-pane.oph` |
| Momus ledger and trials (`.daedalus/momus/`) | ◐ | only as "Momus: holds" on a PR |
| Session narrative: `session-summaries.md`, `docs/status.md` | ○ | what `/inhale` reads; the likeliest first thing to want |
| Memory: project-map, decisions, lessons, warnings, observations, notes | ○ | |
| Ariadne bus: pending/verified/rejected diffs, conflicts | ○ | matters once T-e11 has local models running unattended |
| Ariadne plans (`.daedalus/plans/`) | ○ | |
| Theseus reports | ○ | |
| Mind Palace / Labyrinth map | ○ | |
| Agents (9) | → | used from the Claude pane |
| Skills (inhale, exhale, ariadne, mind-palace) | → | invoked in the Claude pane |

## Totals

| | ● | ◐ | ○ | Direct coverage (● / ●+◐) |
|---|---|---|---|---|
| CLI (23 in scope) | 13 | 4 | 6 | 57% / 74% |
| Beyond CLI (8 in scope) | 1 | 1 | 6 | 13% / 25% |
| **All (31 in scope)** | **14** | **5** | **12** | **45% / 61%** |

The design adds one thing the program doesn't have: a list of PRs awaiting
review (open question: `gh` or local branches).

## History

| Date | Diagrams | In scope | Direct ● / ●+◐ | Change |
|------|----------|----------|----------------|--------|
| 2026-10-14 | 28 | 31 | 45% / 61% | First design draft (8c89c93) |

## Refreshing the CLI inventory

The CLI half of this inventory comes from the live command tree. List every
leaf command with:

```bash
python3 - <<'EOF'
import subprocess
def kids(p):
    out = subprocess.run(["daedalus", *p, "--help"], capture_output=True, text=True).stdout
    tail = out.split("Commands:")[1:] or [""]
    return [l.split()[0] for l in tail[0].splitlines() if l.startswith("  ") and not l.startswith("   ")]
def walk(p):
    k = kids(p)
    if not k: print(" ".join(p))
    for c in k: walk(p + [c])
walk([])
EOF
```

Any command it prints that isn't in the CLI table above is new and needs a mark.
