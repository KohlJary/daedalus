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
| config | config | | | | |
| digest | | | | digest | |
| init, hook | | | | | init, hook board/capture/session-start |
| **Total** | **14** | **4** | **22** | **5** | **5** |

## Beyond the CLI (11 surfaces)

| Surface | Mark | Note |
|---------|------|------|
| Claude Code session | ● | `claude-pane.oph` |
| Momus ledger and trials (`.daedalus/momus/`) | ◐ | only as "Momus: holds" on a PR |
| Session narrative: `session-summaries.md`, `docs/status.md` | ● | `story.oph` Now and Sessions |
| Decisions (`decisions.md`) | ● | `story.oph` Decisions |
| Lessons, warnings, project-map, observations, notes | ◐ | lessons, warnings and map are tab labels that share a diagrammed shape; observations and notes are absent |
| Ariadne bus: pending/verified/rejected diffs, conflicts | ○ | matters once T-e11 has local models running unattended |
| Ariadne plans (`.daedalus/plans/`) | ○ | |
| Theseus reports | ○ | |
| Mind Palace / Labyrinth map | ○ | |
| Agents (9) | → | used from the Claude pane |
| Skills (inhale, exhale, ariadne, mind-palace) | → | invoked in the Claude pane |

## Totals

| | ● | ◐ | ○ | Direct coverage (● / ●+◐) |
|---|---|---|---|---|
| CLI (23 in scope) | 14 | 4 | 5 | 61% / 78% |
| Beyond CLI (9 in scope) | 3 | 2 | 4 | 33% / 56% |
| **All (32 in scope)** | **17** | **6** | **9** | **53% / 72%** |

## Legibility

The goal is a TUI someone else can use, so coverage alone isn't enough: a
view a newcomer can't interpret doesn't count for much. The second measure is
how many concepts have an Explain card in `glossary.md`.

- **Carded (14):** gameplan, roadmap, pending proposal, edict, dissent,
  workstream, board, doctor/drift, story, Momus, Ariadne, Mind Palace, Theseus,
  Claude pane. (Source has a card too, but it's planned, so it isn't counted.)
- **No card yet:** the agent roster (memory, docs, test-runner and the rest), hooks, init/hydrate.

The design adds things the program doesn't have yet:
- a list of PRs awaiting review (open question: `gh` or local branches);
- source plugins (ADO, Jira, …) feeding pending proposals; see README,
  Extensibility. These are counted once they exist in core.

## Incoming: open PRs #38 and #39

These aren't on main yet. The design already covers them, so the numbers below
are what coverage becomes once both merge.

**#39, reflection (edict 0010)**, adds 20 CLI leaves, 11 config keys
(`reflection.*` and `machine.employer`), the `delphi` agent, the `reflect`
skill, and seven kinds of file.

| Mark | Commands |
|------|----------|
| ● | reflect due, digest, runner, arm, log export, pending apply, pending drop, model history, model edit, model delete, model forget, model stable |
| → | reflect bundle, check, render, done (delphi's pipeline), pending import, model aspire |
| – | reflect tick (timer), reflect inhale (skill plumbing) |

**#38, Palace and Ariadne beyond Python**, adds no commands. It adds:
- two config keys (`ariadne.build_gate` and `ariadne.test_cmds`);
- more languages behind the existing `palace` commands;
- one new outcome: a diff whose tests ran nothing goes to review. That
  outcome is NeedsYou's new **AR** kind, which takes the Ariadne bus from ○
  to ◐.

**New surfaces beyond the CLI:** reflection reports ● and the user and self
models ●; `delphi` → and the `reflect` skill →.

| | ● | ◐ | ○ | Direct coverage (● / ●+◐) |
|---|---|---|---|---|
| CLI (35 of 70 in scope) | 26 | 4 | 5 | 74% / 86% |
| Beyond CLI (11 in scope) | 5 | 3 | 3 | 45% / 73% |
| **All (46 in scope)** | **31** | **7** | **8** | **67% / 83%** |

**Legibility:** #39 brings more vocabulary than any other feature. Cards
added for reflection, digest, due, delphi, the user model, the self model
(behavior, interpretation, stance, aspiration) and `machine.employer`. Still
missing: runners, citations, the A/B experiment.

**Writes:** the Models tab's edit, stable, forget and delete, plus digest-now
and log export, are writes outside edict 0012's four kinds. They are the
user's own calls about their own data, so they arguably belong in the TUI, but
adding them needs an amendment to 0012.

## History

| Date | Diagrams | In scope | Direct ● / ●+◐ | Carded concepts | Change |
|------|----------|----------|----------------|-----------------|--------|
| 2026-10-14 | 28 | 31 | 45% / 61% | 0 | First design draft (8c89c93) |
| 2026-10-14 | 34 | 32 | 50% / 69% | 13 | Newcomer goal: Story, Explain, first run, glossary |
| 2026-10-14 | 36 | 32 | 50% / 69% | 14 | Extensibility: Sources screen, tracker-import proposal; roadmap carded as intake |
| 2026-10-14 | 39 | 32 | 53% / 72% | 14 | Config screen: layers, edit modal, secrets in the keyring |
| 2026-10-14 | 48 | 46 (incl. #38, #39) | 67% / 83% | 21 | Reflection screen; RF and AR kinds in NeedsYou |

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
