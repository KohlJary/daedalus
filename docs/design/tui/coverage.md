# TUI design coverage

How much of Daedalus the TUI design (the `.oph` files here) shows. Refresh
this whenever the diagrams or the CLI change, and add a row to History.

## Legend

| Mark | Meaning |
|------|---------|
| ● | Shown: a diagrammed view covers it |
| ◐ | Partial: mentioned (a tab label, a single line), but not diagrammed |
| → | Delegated to Claude: a write or agent operation reached through the Claude pane, by design |
| ○ | Missing: the owner would plausibly want to see it, and no view does |
| – | Out of scope: setup or hook plumbing |

The Claude pane technically makes *everything* reachable, so → is not
coverage. The metric that matters is **direct coverage**: ● and ◐ out of
everything that isn't → or –.

## What ships in edict 0012 v1

The shell (NeedsYou, Gameplan, Health, the Claude pane) and the expanded
screens: NeedsYou, Gameplan (plan, workstreams, roadmap), Health (with the
`hydrate`/`init` fix allowlist), Edicts (edicts and dissents), Story, Board,
Config, Sources, Reflection (due, reports, user model, self model,
experiment), Dream (`D`: dreams, picks, themes, due), and the plugin menu (`m`). Every panel has an Explain card on
`?`. The marks below are what that build shows, not what the diagrams draw.

## CLI (92 leaf commands, `daedalus` 0.2.0 plus edicts 0011-0013)

| Group | ● | ◐ | → | ○ | – |
|-------|---|---|---|---|---|
| board | threads, read, follow, unfollow | | open, draft, post, check | | |
| edict | list, show, dissents | | dissent | resolve-dissent | |
| gameplan | show, phase list, pending apply, pending drop | | pending import, phase activate/add/status, task add/defer/status | | |
| workstream | list, show | others | claim, new | use | |
| roadmap | list | show | add | | |
| doctor | doctor | | | | |
| hydrate | hydrate (a Health fix, after a confirm) | | | | |
| palace | | | callers, callees, dispatch, impact, path, tests-for | status, languages | init |
| reconstruct | | | check, gather | | |
| config | config | | | | |
| source | list, status | | sync | | login |
| reflect | due, digest, runner, log export, pending apply, pending drop, model history, model edit, model delete, model forget, model stable | arm | bundle, check, render, done, pending import, model aspire, log correct | | tick, inhale |
| dream | show, due | log, review show | start, prompt, turn, write, done, bundle, keep, review bundle, review record | seeds | |
| digest (Wonderland runs) | | | | digest | |
| init, hook, tui | | | | tui sends | init, hook board/capture/session-start, tui |
| **Total** | **32** | **5** | **40** | **7** | **9** |

Notes on the marks:
- `dream` (edict 0013, merged after the TUI was designed): the steps /dream drives are → (Claude runs them).
  The Dream screen (`D`, `dream.oph`) shows `show` (Dreams) and `due` (Due, computed without writing
  due.json) as ●. `log` is ◐: the Due tab shows the experiment's totals across every dream and points
  to `daedalus dream log` for the per-mode breakdown. `review show` is ◐: the Themes tab lists the
  review's theme registry, not the rendered review. A dream's seeds are still only the CLI's (○). No
  tab, Due included, names or counts a dream's mode: a per-mode figure that moves as picks are applied
  or built would let a reader attribute a dream's mode. Syncing picks (`source sync dream`) is handed
  to Claude.
- `init` stays –: it's setup, though Health can run it as an allowlisted fix.
- `tui sends` is ○: the send-form log's counts are only in the CLI; the TUI shows the setting (Config), not the
  counts.
- `source sync` is →: `sources.oph` draws `r sync now`, but syncing isn't one
  of edict 0012's v1 writes, so the Sources screen hands it to Claude.
- `reflect arm` is ◐: the Experiment tab shows the session's arm and the
  counts; drawing an arm happens at inhale, not in the TUI.
- `roadmap show` is ◐: the Gameplan screen's Roadmap tab lists items; one
  item's full record is still the CLI's.
- The group commands that also run alone (`gameplan pending`, `reflect log`,
  `reflect model`, `reflect pending`) aren't counted separately; their
  views are the ● rows above.

## Beyond the CLI (13 surfaces)

| Surface | Mark | Note |
|---------|------|------|
| Claude Code session | ● | `claude-pane.oph` |
| Momus ledger and trials (`.daedalus/momus/`) | ◐ | only as "Momus: holds" on a PR and on a reflection report |
| Session narrative: `session-summaries.md`, `docs/status.md` | ● | Story: Now and Sessions |
| Decisions (`decisions.md`) | ● | Story: Decisions |
| Lessons, warnings, project-map, observations, notes | ◐ | lessons, warnings and map are Story tabs; observations and notes are absent |
| Reflection reports (`.daedalus/reflection/reports/`) | ● | Reflection: Reports (the rendered Markdown; citations don't open their event yet) |
| User and self models (`~/.config/daedalus/models/`) | ● | Reflection: User model, Self model, with history and self-entry dissents |
| Ariadne bus: pending/verified/rejected diffs, conflicts | ○ | the design's AR kind in NeedsYou didn't ship in v1; a non-goal of 0012 |
| Ariadne plans (`.daedalus/plans/`) | ○ | non-goal of 0012 |
| Theseus reports | ○ | non-goal of 0012 |
| Mind Palace / Labyrinth map | ○ | non-goal of 0012 |
| Agents (10, with delphi) | → | used from the Claude pane |
| Skills (inhale, exhale, reflect, ariadne, mind-palace) | → | invoked in the Claude pane |

## Totals

| | ● | ◐ | ○ | Direct coverage (● / ●+◐) |
|---|---|---|---|---|
| CLI (44 in scope) | 32 | 5 | 7 | 73% / 84% |
| Beyond CLI (11 in scope) | 5 | 2 | 4 | 45% / 64% |
| **All (55 in scope)** | **37** | **7** | **11** | **67% / 80%** |

## Legibility

The goal is a TUI someone else can use, so coverage alone isn't enough: a
view a newcomer can't interpret doesn't count for much. The second measure is
how many concepts have an Explain card in `glossary.md`.

- **Carded (27):** gameplan, roadmap, source, pending proposal, edict,
  dissent, workstream, board, doctor/drift, story, Momus, Ariadne, Mind
  Palace, Theseus, Claude pane, reflection, digest, due, delphi, user model,
  self model, machine: employer, config, A/B experiment, TUI plugin, dream, send form.
- **No card yet:** the agent roster (memory, docs, test-runner and the rest),
  hooks, init/hydrate, runners, citations.

## Gaps left for a later edict

- **Ariadne, Theseus, Mind Palace:** no views (0012's non-goals). NeedsYou's
  AR kind, drawn for unattended Ariadne diffs, isn't built.
- **Reflection citations:** a report is shown as rendered Markdown; following
  a citation to its event (`enter` in the diagram) isn't built.
- **`edict resolve-dissent`, `workstream use`, `palace status/languages`:** no
  view and no hand-off.
- **Plugins:** a plugin's NeedsYou kind shows its own `detail()` and the
  `actions()` it declares, in the key row (one protocol: `daedalus.tui.plugin`).
  Each action runs `run_action` only after the shared confirm, which names the
  plugin and the action, gets a `y`; undeclared keys say "no such action for
  this kind". The TUI's own writes are still exactly 0012's list.

## History

| Date | Diagrams | In scope | Direct ● / ●+◐ | Carded concepts | Change |
|------|----------|----------|----------------|-----------------|--------|
| 2026-10-14 | 28 | 31 | 45% / 61% | 0 | First design draft (8c89c93) |
| 2026-10-14 | 34 | 32 | 50% / 69% | 13 | Newcomer goal: Story, Explain, first run, glossary |
| 2026-10-14 | 36 | 32 | 50% / 69% | 14 | Extensibility: Sources screen, tracker-import proposal; roadmap carded as intake |
| 2026-10-14 | 39 | 32 | 53% / 72% | 14 | Config screen: layers, edit modal, secrets in the keyring |
| 2026-10-14 | 48 | 46 (incl. #38, #39) | 67% / 83% | 21 | Reflection screen; RF and AR kinds in NeedsYou |
| 2026-10-15 | 48 | 49 | 71% / 82% | 25 | What edict 0012 v1 ships (not just designs): reflection and source commands counted, AR kind not built, plugin menu, A/B experiment and TUI plugin cards |
| 2026-10-15 | 48 | 54 | 65% / 74% | 25 | Edict 0013 (dreaming) merged before the TUI: 14 `dream` commands, 9 driven through Claude (→), 5 not visible (○): no Dream screen in v1 |
| 2026-10-15 | 54 | 54 | 69% / 81% | 26 | Dream screen (`dream.oph`, `D`): dreams, picks with their roadmap status, themes, due; `dream show`, `due` ●, `log` and `review show` ◐ (Due shows totals only, no per-mode lines); Dream card |
| 2026-10-15 | 54 | 55 | 67% / 80% | 27 | Send form (dream pick p2): `tui.send_form`, a Send form card, and `tui sends` (○: counts only in the CLI) |

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
