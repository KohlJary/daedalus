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
- **Outward-facing changes always ask.** A write-back is a proposal. Applying it makes the call to
  the outside system, and dropping it discards it. No setting turns write-backs into automatic
  writes.
- **Conflicts are configurable per source.** `sources.<name>.on_conflict` takes one of three values:
  - `propose` (default): the difference becomes a `roadmap-update` proposal;
  - `source`: the outside value is applied automatically and recorded;
  - `local`: the outside change is ignored and recorded.
  Even under `source`, a sync never overwrites a task's resolution or anything the mapping doesn't
  own.
- **The roadmap is committed.** Phases reference roadmap items (`roadmapItems`), so
  `.daedalus/roadmap/index.json` is committed alongside the gameplan, and `init` and `hydrate` stop
  ignoring it. Each item records its origin: `{"source", "external_id", "url"}`, or
  `{"source": "local"}`.
- **Plugins register through Python entry points** in the group `daedalus.sources`. First-party
  sources register the same way as third-party ones. A source declares:
  - its config schema, with a description, type and default for each key;
  - its default mapping;
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

## Acceptance criteria
- `daedalus source list`, `daedalus source sync [<name>]` and `daedalus source status` exist.
  `status` shows each source's last sync, item count and health.
- `daedalus roadmap list` shows each item's origin. `daedalus roadmap show <id>` shows the item and
  the phases and tasks that reference it.
- An ADO source ships in the package. Given organization, project and a query (default: open work
  items assigned to the user in the current iteration), it produces the default mapping's
  proposals. Its tests run against recorded API responses, with no network.
- A GitHub Issues source ships in the package. With no configuration in a repository whose `origin`
  is on GitHub, it syncs that repository's open issues, assigned to the user by default. Its
  write-back closes the issue and, with `write_back_comment: true`, posts the resolution as a
  comment. Its tests run against recorded API responses, with no network.
- Syncing twice with no outside change adds no proposals: proposals are keyed by source and
  external id.
- Each `on_conflict` value has a test showing what happens when an item changed on both sides.
- Marking a task done whose roadmap item came from a write-back-capable source creates a
  `write-back` proposal. Applying it calls the source, which is mocked in tests. Dropping it calls
  nothing.
- Write-back content defaults to the state change. `sources.<name>.write_back_comment: true` also
  posts the task's resolution as a comment.
- `doctor` reports a source that can't authenticate or reach its server, and drift between a source
  and the gameplan: an item closed outside but open here, or done here with no write-back applied
  or dropped.
- A source in a separate test package registers through the entry point and syncs without changes
  to Daedalus. This test shows that a Jira source could be written outside Daedalus.
- Glossary entries for Roadmap and Source match the behaviour that ships.

## Non-goals
- No Jira source ships in this edict. The interface only has to make one possible.
- Outside items never become edicts. Edicts stay the owner's design decisions.
- No sync of fields beyond what the mapping owns: no assignees, estimates or custom fields in v1.
- No background or scheduled sync, and no automatic write-back.
- No TUI work. The Sources screen belongs to edict 0012.
