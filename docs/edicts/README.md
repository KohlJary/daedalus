# Edicts

An edict is a design decision handed down to Daedalus to build. Designs are
worked out in conversation, written up as an edict, and pushed here. Daedalus
picks up `accepted` edicts and implements them.

Edicts are also the source of truth for intent: Ariadne's semantic judge grades
diffs against an edict's acceptance criteria, not against a worker's own
description of what it did.

## Format

File: `docs/edicts/NNNN-short-slug.md`

```markdown
# Edict NNNN: Title
Status: proposed | accepted | done
Depends on: (optional) branches, edicts, or features this needs first

## Intent
What this is for, in a few sentences.

## Constraints
Rules the implementation must respect.

## Acceptance criteria
Checkable statements. This is what the judge reviews against.

## Non-goals
What this deliberately does not do.

## Amendments
(Only once amended.) Date, what changed, why.
```

## Lifecycle

- **proposed**: written, not yet approved for work
- **accepted**: Kohl has signed off; Daedalus may build it
- **done**: all diffs for it have merged

Only Kohl moves an edict to `accepted`. Daedalus does not write or accept its
own edicts — that would have the judge grading Daedalus against Daedalus.

## Flow: merging is signing off

New edicts arrive as pull requests, written with `Status: accepted`. The PR is
the proposal; **merging it to `main` is Kohl's sign-off.** Nothing on a branch
is actionable.

Daedalus builds only edicts that are on `main` with `Status: accepted`. An
edict on `main` marked `proposed` is still waiting (flip it in a PR to accept).

The full loop:

1. Design is worked out in conversation.
2. The edict is opened as a PR; Kohl reviews and merges.
3. Daedalus builds it on a branch and opens a PR whose body says
   `Implements edict NNNN`. CI must pass.
4. That PR can be reviewed against the edict's acceptance criteria from chat
   before Kohl merges.
5. When everything for the edict has merged, its status moves to `done`.

## Amendments

An accepted or proposed edict can change, but only the way it was made:

- **Kohl initiates, Daedalus may draft.** Daedalus changes an edict's text
  only when Kohl asks for it in conversation. The PR quotes the request and
  changes only what was asked.
- **Merging is acceptance**, as for a new edict.
- **The edict records its history** in an `Amendments` section: date, what
  changed, and why. The judge grades against the current text; the log says
  when the criteria moved.
- **Daedalus's own objections are dissents, not amendments.** If Daedalus
  thinks an edict is wrong, it writes a dissent and stops. Daedalus never
  edits criteria it will be graded against on its own initiative.
- The only status change Daedalus makes is `accepted` to `done`.

## Status handoff

Each fact lives in one place:

- **Edicts** carry designs: what to build and why (chat to code).
- **The gameplan** (`.daedalus/roadmap/gameplan.json`, committed) carries progress: which edicts
  are built, what is in flight, what is next (code to chat). Phases and tasks cite edicts with an
  `edict` field; `daedalus doctor` flags accepted edicts nothing in the gameplan references.
- **`docs/status.md`** carries the narrative: a short note on the last session, open dissents, and
  anything the gameplan can't say. It does not restate phases, tasks, or which edicts are built.

Daedalus updates the status note at the end of each working session. Claude in chat reads the
gameplan and the note to pick up where it stopped.
