# Edicts

An edict is a design decision handed to Daedalus to build. Designs are worked out in
conversation (often with Claude in chat), written up as an edict, and merged here. Daedalus
builds `accepted` edicts, and its work is judged against their acceptance criteria.

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
Checkable statements. This is what the work is judged against.

## Non-goals
What this deliberately does not do.

## Amendments
(Only once amended.) Date, what changed, why.
```

## Lifecycle

- **proposed**: written, not yet approved for work
- **accepted**: the project owner has signed off; Daedalus may build it
- **done**: all work for it has merged

Edicts arrive as pull requests written with `Status: accepted`; merging one to `main` is the
owner's sign-off. Daedalus does not write or accept edicts on its own initiative, and the only
status change it makes is `accepted` to `done`. `daedalus edict list` shows every edict and
whether the gameplan tracks it.

## Amendments

An edict changes the way it was made: the owner asks for the change, the edict records it in an
`Amendments` section (date, what changed, why), and merging is acceptance. Daedalus's own
objections are dissents, not amendments.

## Dissents

If Daedalus thinks an edict is mistaken, harmful, or underspecified, it writes
`docs/edicts/dissents/NNNN-daedalus.md`: what it objects to, why, and what it would do instead.
Work on that edict stops until the owner resolves the dissent. Resolved dissents stay on record.

## Where things live

- **Edicts** carry designs: what to build and why.
- **The gameplan** carries progress: phases and tasks cite edicts with an `edict` field, and that
  is the only place an edict's progress is recorded. `daedalus doctor` flags accepted edicts
  nothing in the gameplan references.
- **`docs/status.md`** carries the narrative: the last session, open dissents, and anything the
  gameplan can't say.
