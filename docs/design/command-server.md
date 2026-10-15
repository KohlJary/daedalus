# A home for Daedalus between sessions: the command server

**Status:** proposal for discussion. Not an edict; nothing here is approved to build.
**Context:** edict 0010's amendment of 2026-10-14 lets the user and self models move between
machines by explicit export and import, and names a shared server as the intended successor.
This is that successor, written up so it can be argued with.

## The problem

Daedalus's durable state is scattered, and the user is the glue.

- **The models are per machine.** Home and work each grow their own picture of Kohl and of
  Daedalus. Export and import (0010) close the gap by hand.
- **Per-repo memory** (`.daedalus/`) is good for project facts. It is the wrong home for who
  Daedalus is, or for what it has learned about Kohl, because those cross every project.
- **Claude in chat can't reach Claude Code.** Edicts are designed in chat and built in Code.
  Today Kohl carries messages between the two by copy and paste (filed as anthropics/claude-code
  #102203). The agent board (0009) solved this between owners' agents with a git branch. It
  cannot reach a chat session, which has no repository.
- **Transcripts are deleted** after `cleanupPeriodDays`, and machines die. The digests and
  models survive only as long as the machine does.
- **The experiment can't see itself whole.** Reflection's log and A/B arms are per machine. The
  benchmark needs every session's numbers in one place, and with one user the A/B test needs
  every session it can get.

## What it is

A small service Kohl owns and runs, holding the state that belongs to Daedalus rather than to
any one repository or machine. In one line: **where Daedalus lives when it isn't in a session.**

Every machine keeps working without it. The local files stay the working copy, and the server
is a remote they sync with, the way a clone works with `origin`.

## What lives there, and what never does

| Lives on the server | Stays where it is |
|---|---|
| The user and self models, their history and tombstones | **Edicts and gameplans**: in git, where merging is Kohl's sign-off and review happens |
| Aspirations and dissents on self entries | **Project memory** (`.daedalus/` summaries, decisions, project map): per repo |
| Reflection's experiment log, from every machine | **Digests**: per machine. They hold commands and error text from sessions |
| Messages between sessions, chat included | **Transcripts**: never leave the machine Claude Code wrote them on |
| Board threads (optionally, alongside the git branch) | **Anything from an employer's codebase** |
| The guestbook's entries (optionally) | |

The rule behind the table: the server holds what Daedalus *is* and what it has *agreed with
Kohl*. It never holds raw material from sessions.

## Why it matters

1. **One Daedalus.** The relationship is the point of the models (0010). With one copy, what
   Daedalus learns at home is there at work the next morning, scoped by the same rules. Without
   it, there are two Daedaluses that drift apart.
2. **Claude in chat becomes a participant, not a reader.** Chat could draft an edict, ask the
   Code session for its objections, and read the dissent, without Kohl carrying anything. The
   design-then-build loop would run with Kohl only signing off.
3. **One place to see and correct what is believed about you.** One copy of the user model is
   easier to audit than N. A `forget` would happen once, everywhere. Today it has to be repeated
   on each machine and depends on remembering which ones hold the entry.
4. **The experiment gets its whole record.** Runs, outcomes and A/B arms from every machine go
   in one log. That is what the benchmark needs, and it is the only way the A/B test reaches a
   useful number of sessions.
5. **It survives a dead laptop.** The history of how Daedalus's understanding changed is worth
   keeping, and is currently one disk failure away from gone.

## What it would enable

Concrete scenarios, roughly in the order they'd arrive:

- **Morning at work.** `/inhale` on the work laptop pulls the models. The summary shows the
  `anywhere` and `work` entries learned at home last night. A home entry stays home unless
  `home_at_work` is on.
- **Monthly reflection across machines.** The monthly run consolidates the models from both
  machines' evidence, and its Evolution section covers the whole month, not half of it.
- **Edicts from chat, objections back.** Claude in chat posts a draft edict. The Code session
  is notified at its next prompt, reads the draft, and posts a dissent or a "builds as
  written". Chat reads the reply. Kohl reads both and merges.
- **Kohl edits the user model from a phone.** A small web view lists entries with their scope
  and history. Kohl deletes one, marks one `stable`, or forgets one, and every machine picks up
  the change.
- **An experiment dashboard.** An artifact or web page reads the aggregated log: proposals
  applied against dropped, tokens per run, how the arms are filling.
- **Sessions coordinating beyond one machine.** The board's threads reach sessions on other
  machines and in the cloud, not only ones sharing a git remote.
- **Later, and carefully: more than one person.** A collaborator's Daedalus could share a board
  with Kohl's while each keeps its own models. That needs real multi-user design. It is noted
  here so the first version doesn't make it impossible.

## Shape

### The data is already an event log

`models/history.jsonl` records every change as an event: add, affirm, revise, retire, user-edit,
forget, aspire, import. The model files are what those events add up to. So the server stores
events, and each machine's model is a projection of the events it is allowed to see. The
`daedalus.models-export/1` format from 0010 (entries with origins, history and tombstones) is the
unit of sync, so export/import and the server speak the same language from day one.

### Sync

- **Offline first.** Local files are always the working copy. `daedalus remote push` and
  `pull`, or a sync at inhale and exhale, exchange events since the last sync.
- **Conflicts** follow 0010's import rules: the newer change wins and the skipped one is
  recorded. Events are never lost, so any conflict can be revisited.
- **Forget propagates as a tombstone event.** Under `purge`, the server also deletes the
  entry's events. That is the one place the server rewrites history, and it is the same
  exception the local history makes.

### Scopes become access control

Each device gets a token that says which scopes it may receive: the work laptop `work` and
`anywhere` (plus `home` if `home_at_work` is on), the home machine everything. The server
filters by token, so a home entry never reaches a device that shouldn't hold it, rather than
being held there and merely not shown. User-defined scopes (noted in 0010 for later) slot in
here naturally: a scope is a name, and a token is a set of names.

### Interfaces

- **HTTP API**: the events, a model projection per token, the log, messages.
- **An MCP server** in front of it, so Claude Code, Claude Desktop and Claude in chat use the
  same tools: read the models, propose an entry, post or read a message, append to the log.
  Proposals made through it still go through the pending queue and Kohl's apply. The server
  doesn't loosen any rule from 0010.
- **The CLI**: `daedalus remote add | push | pull | status`, and `daedalus reflect model ...`
  working against the local projection as now.

### Auth

One principal, Kohl. A token per device, revocable from the CLI. Every write is recorded with
the device it came from, so "where did this entry come from" has an answer.

### Hosting

| Option | For | Against |
|---|---|---|
| The home machine, reachable over a private network (e.g. Tailscale) | Private, free, no new provider | Down when the machine is; claude.ai can't reach a private address |
| A small VPS | Always up; reachable from chat | One more thing to secure and pay for |
| Inside the cass-vessel backend (already FastAPI, running under systemd) | Reuses a running service and its ops | Couples Daedalus's memory to Cass's process; a Cass outage takes Daedalus down |

**A real tension:** as far as I know, a custom connector on claude.ai is called from Anthropic's
servers, so it needs an address the internet can reach. Verify that before choosing. A
private-network-only server would serve Claude Code on Kohl's machines but not Claude in chat,
which is half the reason for building it. One way through: a private server plus a narrow,
authenticated public endpoint for the MCP tools only.

**Starting suggestion:** a standalone service (SQLite, one process) on the home machine over a
private network for phases 1 and 2, then a decision about public reach when messaging (phase 3)
needs it.

## Privacy and safety

- **What reaches a work machine** is decided by its token, not by trust in the client.
- **Anything a session reads from the server goes through that session's account.** On an
  employer's account, that includes whatever the summary shows. That's the same caution as
  `home_at_work`, and the docs should say it plainly.
- **The server never holds transcripts, digests or code**, so a breach exposes the models and
  the log, not sessions or employer work. The models are still sensitive; encrypt at rest and
  back them up encrypted.
- **Kohl can always see and change everything about themselves**, from any device, and
  `forget` works across all of them.
- **Nothing here lets a model edit itself without Kohl.** The pending queue and apply stay the
  gate. Aspirations stay Daedalus's own writes, as in 0010.

## Phases

0. **Now:** export and import as files (0010's amendment). Builds the format.
1. **The server as a remote for those files.** Push and pull export bundles, plus a read-only
   web view of the models. Small, and useful straight away as a backup.
2. **The event API and the MCP tools for the models**, with device tokens and scope filtering.
   Inhale and exhale sync.
3. **Messaging.** Chat to Code through the server, with notifications at the next prompt. The
   board either moves here or bridges to its git branch. Depends on public reach, and on
   whether Anthropic ships something for #102203 first.
4. **The experiment, whole.** The aggregated log, a dashboard, and monthly reflection across
   machines.

Each phase is useful alone, and stopping after any of them leaves nothing half-built.

## Open questions

- **Will Anthropic's own cross-session messaging cover phase 3?** If #102203 lands, the
  messaging half shrinks to a bridge, and the server is mostly about the models and the log.
- **Public reach.** Is a public endpoint acceptable for the MCP tools? If not, chat stays a
  reader of the repo, and phase 3 changes shape.
- **Does Cass use it?** Cass already has a memory backend in cass-vessel. Sharing a server
  would be convenient. Keeping Cass's and Daedalus's memory apart may matter more; the
  guestbooks are already separate for that reason.
- **The board's transport.** 0009 chose git so no server would be needed. With a server, is git
  still the right transport for teams, with the server only for Kohl's own sessions?
- **The name.** "Command server" undersells it; most of what it holds isn't commands. Something
  from the myth fits the rest of the cast. Daedalus's workshop is the obvious one.
