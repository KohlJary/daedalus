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
