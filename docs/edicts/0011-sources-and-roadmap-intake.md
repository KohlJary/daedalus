# Edict 0011: Sources and roadmap intake
Status: accepted
Depends on: Edict 0007 (gameplan, pending proposals, doctor); Edict 0008 (workstreams)

## Intent
Let work arrive from wherever a team already tracks it, such as Azure DevOps, Jira or GitHub
Issues, and flow into Daedalus's plan without anyone retyping it and without the plan changing
behind its owner's back.

This gives the roadmap a job it doesn't have today. **The roadmap is intake**: everything that has
been asked for, from any source, including ideas and bugs typed in locally. **The gameplan is the
plan**: phases pull roadmap items in and break them into tasks. A **source** is a plugin that
connects one outside tracker to the roadmap and gameplan. It brings items in as pending proposals,
and when work is done here it proposes the matching update back out.

Kohl uses ADO at work and GitHub for personal work, and wants items from both to become gameplans,
along with everything that follows from that. So both ship as first-party sources. Another user
will bring Jira, so the source interface is a plugin seam, not something specific to either.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-14. Design notes:
`docs/design/tui/README.md` (Extensibility), `docs/design/tui/sources.oph`.

## Constraints
- **Nothing writes the gameplan or roadmap unreviewed by default.** A sync produces pending
  proposals (the existing `daedalus gameplan pending` mechanism), which the owner applies or drops.
  New proposal kinds join `task-status`, `new-phase` and `roadmap-status`: `roadmap-new` (a new
  intake item), `roadmap-update` (an outside change to an existing item) and `write-back` (an
  outward update).
- **Proposal keys and idempotency.**
  - Keys: `roadmap-new` and `roadmap-update` are keyed `src:{source}:{external_id}`. `write-back`
    is keyed `wb:{source}:{external_id}:{task}`.
  - A re-sync skips any external id already in the roadmap index, or already pending in any
    workstream.
  - A changed `roadmap-update` replaces the pending one. The current replace-only-with-new-commits
    rule applies only to kinds that carry commits.
  - `PROPOSAL_KINDS`, `proposal_key`, `describe_proposal` and `apply_pending` handle every kind
    explicitly. An unknown kind raises; it never falls through to `set_task_status`.
- **Tasks trace back to their source.**
  - A task created from a source carries `origin: {source, external_id, url}` and
    `roadmapItem: <id>`.
  - Setting such a task to done creates a `write-back` proposal when the task has an origin, or when
    its `roadmapItem` has one. A task with neither never writes back, even if its phase references
    sourced items.
- **Outward-facing changes always ask.** A write-back is a proposal. Applying it makes the call to
  the outside system, and dropping it discards it. No setting turns write-backs into automatic
  writes.
- **Conflicts are configurable per source.** `sources.<name>.on_conflict` takes one of three values:
  - `propose` (default): the difference becomes a `roadmap-update` proposal;
  - `source`: the outside value is applied automatically and recorded;
  - `local`: the outside change is ignored and recorded.
  Even under `source`, a sync never overwrites a task's resolution or anything the mapping doesn't
  own.
- **A conflict is measured against the last sync.**
  - Each sourced roadmap item stores `synced: {fields, remote_updated}`: the owned fields as the
    last sync saw them.
  - A conflict means both the local value and the remote value differ from that baseline. A change
    on one side only is an ordinary update.
  - Each mapping lists the fields it owns, and a state map from the tracker's states to roadmap
    statuses (`backlog`, `ready`, `in_progress`, `review`, `done`).
- **The roadmap is committed.** Phases reference roadmap items (`roadmapItems`), so
  `.daedalus/roadmap/index.json` is committed alongside the gameplan. Each item records its origin:
  `{"source", "external_id", "url"}`, or `{"source": "local"}`.
  - The gitignore blocks that `init` and `hydrate` write gain `!.daedalus/roadmap/index.json`.
  - `_ensure_gameplan_tracked` checks the index too, and adds the negation to a project whose
    existing block lacks it.
  - Pending-proposal files stay ignored.
- **One config schema, built here.**
  - `config_schema.py` is a single registry of key, type, default, description and choices.
  - Core keys register from the existing dataclasses and `SETTING_CHOICES`. Each source registers
    its own keys from its entry point.
  - A free-form `sources: {name: {...}}` group joins the config and can be overridden per project.
  - `daedalus config` validates against the registry.
  - Edict 0012's config screen uses this same registry; it is not built twice.
- **Plugins register through Python entry points** in the group `daedalus.sources`. First-party
  sources register the same way as third-party ones. A source declares:
  - its config schema, with a description, type and default for each key;
  - its default mapping (owned fields, kind mapping, state map);
  - whether it supports write-back.
- **Mapping is per source and configurable.** The ADO default:
  - Epic or Feature → `new-phase` proposal;
  - User Story or Bug → `roadmap-new` item;
  - Task → a task in the phase that references its parent's roadmap item.

  The GitHub Issues default:
  - Milestone → `new-phase` proposal;
  - Issue → `roadmap-new` item;
  - sub-issue → a task in the phase that references its parent's roadmap item.

  On GitHub, pull requests are not intake: they are work already in flight.
- **Credentials never live in the repo or in a config file.** They come from the system keyring, or
  from an environment variable named in config. The GitHub source can also use the token of an
  authenticated `gh` CLI, and its repository defaults to the project's `origin` remote.
- **Sync is deterministic and on demand.** There are no model calls in sync, and no background
  daemon. Hooks don't touch the network, so the session-start brief shows each source's last sync
  time and nothing more.
- **A source failure is never fatal.** Auth and network errors become `doctor` findings, and the
  rest of Daedalus works as before.
- **Workstreams apply.** A sync writes proposals for the current workstream unless `--workstream`
  names another.
- **Tests never reach a live service.** Tests run with sockets disabled, `GH_TOKEN` and
  `GITHUB_TOKEN` blanked, the keyring monkeypatched, and `gh` stubbed. API fixtures are written by
  hand to the documented API shapes. Each one is labelled `synthetic` in the file, with the doc
  URL it follows. Neither source is claimed to work live until someone has run it live.

## Acceptance criteria
- `daedalus source list`, `daedalus source sync [<name>]` and `daedalus source status` exist.
  `status` shows each source's last sync, item count and health. Health is one of `ok`,
  `unverified`, `never-synced`, `auth-failed` or `unreachable`.
- `daedalus roadmap list` shows each item's origin. `daedalus roadmap show <id>` prints the item (with
  origin and sync baseline), then the phases that list it, then the tasks whose `roadmapItem` is it.
- `daedalus source sync --dry-run` prints the proposals a sync would make and writes nothing.
  The first live run of each source is the owner's, with `--dry-run`.
- An ADO source ships in the package. Given organization, project and a query (default: open work
  items assigned to the user in the current iteration, using WIQL's `@Me` and `@CurrentIteration`),
  it produces the default mapping's proposals against synthetic fixtures. Kohl finishes and
  verifies it live on the work machine. Until then `source status` reports it as `unverified`.
- A GitHub Issues source ships in the package. With no configuration in a repository whose `origin`
  is on GitHub, it syncs that repository's open issues, assigned to the user by default. Its
  write-back closes the issue and, with `write_back_comment: true`, posts the resolution as a
  comment. Its tests run against synthetic fixtures.
- Syncing twice with no outside change adds no proposals. Syncing again after the proposals are
  applied adds none either. An unknown proposal kind raises in `apply_pending`, and a test checks
  this.
- Each `on_conflict` value has a test showing what happens when an item changed on both sides.
- Marking a task done whose roadmap item came from a write-back-capable source creates a
  `write-back` proposal. Applying it calls the source, which is mocked in tests. Dropping it calls
  nothing.
- Write-back content defaults to the state change. `sources.<name>.write_back_comment: true` also
  posts the task's resolution as a comment.
- `doctor` reports:
  - a source that can't authenticate or reach its server, from its last sync;
  - drift: an item whose last-synced remote state is closed but which is open here;
  - a task that is done but whose write-back is neither pending nor recorded. Applying or dropping a
    write-back records `synced.write_back: applied | dropped` on the item, so a drop stays visible.
  Source checks are added as their own function after `run_checks`.
- A source in a separate test package registers through the entry point and syncs without changes
  to Daedalus. This test shows that a Jira source could be written outside Daedalus.
- `daedalus config sources.github.on_conflict local` is accepted, and an invalid value is
  rejected with the allowed choices. Every core config key has a description in the registry, and
  a test checks this.
- `docs/design/tui/glossary.md`'s Roadmap and Source cards name the `roadmap` and `source`
  commands that ship, and a test greps for them.

## Non-goals
- No Jira source ships in this edict. The interface only has to make one possible.
- Outside items never become edicts. Edicts stay the owner's design decisions.
- No sync of fields beyond what the mapping owns: no assignees, estimates or custom fields in v1.
- No background or scheduled sync, and no automatic write-back.
- No TUI work. The Sources screen belongs to edict 0012.

## Amendments
- **2026-10-14:** made buildable from Momus's readiness review
  (`.daedalus/momus/trials/2026-10-14-edicts-0011-0012-readiness.md`):
  - tasks trace back to their source (F1);
  - proposal keys, re-sync idempotency, and unknown kinds that raise (F2);
  - a config schema registry with a `sources` group, built here and shared with 0012 (F3);
  - synthetic, labelled fixtures, `--dry-run`, and the ADO source finished and verified live by
    Kohl on the work machine (F4);
  - the gitignore migration (F7);
  - a sync baseline, owned fields and state maps for conflicts (F8);
  - doctor, status, `roadmap show` and glossary criteria made checkable (F9);
  - test isolation from live services (F13).
  Kohl approved Momus's fixes, folding the schema into 0011, in conversation.
