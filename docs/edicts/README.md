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

## Status handoff

`docs/status.md` is the committed snapshot of where Daedalus left off: the
current gameplan phase, edicts in flight, open dissents, and the last session's
summary. Daedalus updates it at the end of each working session. Its own memory
in `.daedalus/` is not committed, so this file is how anyone outside the
session, including Claude in chat, picks up where it stopped.
