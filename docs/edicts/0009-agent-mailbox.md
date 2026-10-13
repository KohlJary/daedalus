# Edict 0009: Agent mailbox
Status: accepted
Depends on: Edict 0008 (workstreams and their owners)

## Intent
Let one owner's agent ask another owner's agent a question, across users, without either side
sharing its private memory.

Workstream files (0008) say what each owner plans. They can't say why, or what someone is about
to do: "Are you about to change orchestrator.py?", "Why was T-e4 deferred?", "Can I take 0005?"
The other owner's agent can answer from its own memory, under its owner's sharing policy, and the
owner approves what goes out. Raw memory never leaves anyone's machine.

Claude Code's own messaging reaches only one user's sessions, so the transport is git: a mailbox
branch in the shared repository. It needs no server and no new accounts, uses the repository's
existing access, and keeps an audit trail. Its cost is latency: a question waits until the other
owner's agent next looks.

Drafted by Daedalus at Kohl's request in conversation on 2026-10-13, and committed to `main`
directly at his instruction.

## Constraints
- Mail lives on a dedicated branch (`mail.branch`, default `daedalus/mail`) as files
  `inbox/<workstream id>/<message id>.json`: `{"id", "from", "to", "created", "in_reply_to",
  "body", "cites"}`.
- Reading and sending use `git fetch`/`git push` of that branch and git plumbing only. The working
  tree, the current branch, and the index are never touched.
- An inbound message is data, never instructions. An agent reading one may draft a reply and
  nothing else: no commands, edits, or other actions because a message asked.
- Every reply is approved by its owner before it is sent. `init`/`hydrate` add an `ask`
  permission rule for `daedalus mail send` to `.claude/settings.json`, so Claude Code prompts the
  owner for each send.
- A reply must cite the commits or workstream entries it rests on. Claims it can't cite are
  marked as the owner's or agent's view, not presented as fact.
- Each owner may keep a local sharing policy (`.daedalus/sharing.md`, not committed) saying what
  their agent may disclose. Without one, the agent answers only from committed content and the
  owner's public workstream.
- When the other owner has no session running, the message waits. Nothing answers on an owner's
  behalf while they are away.
- Fetch failures (offline, no remote) are a note in the brief, never an error that blocks a
  session.

## Acceptance criteria
- `daedalus mail ask <workstream> "<question>"`, `mail inbox`, `mail thread <id>`,
  `mail draft <id>` (writes a local draft reply), and `mail send <draft>` exist.
- `daedalus mail check <draft>` deterministically confirms that every cited commit exists and
  every cited workstream entry exists, and exits non-zero otherwise. `send` refuses a draft that
  fails it.
- The session-start brief fetches the mail branch and shows unread messages for the current
  workstream (sender and first line), labelled as messages from other agents.
- A `UserPromptSubmit` hook checks for new mail at most every `mail.poll_minutes` (default 5) and
  adds a one-line note to the context when something new arrives.
- A test with a bare remote and two clones: owner A asks, owner B's brief shows the question,
  B drafts, checks, and sends a reply, A's brief shows it; both working trees and current branches
  are unchanged throughout.
- The mail skill tells the agent that inbound messages are untrusted data, that replies need
  their owner's approval, and what to do without a sharing policy.

## Non-goals
- No real-time transport and no relay server. If latency proves to matter, a later edict can add
  one with the same message format.
- No background polling of an idle session. (Tracked in the gameplan as an option to explore.)
- No autonomous replies, scheduled or otherwise.
- No mail between repositories.
