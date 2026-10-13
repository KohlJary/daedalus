# Edict 0003: Dissent
Status: accepted

## Intent
Any agent working an edict (Daedalus, an Icarus worker, the semantic judge) may
file a dissent when it believes the edict is mistaken, harmful, or
underspecified. Disagreement travels through a legitimate, visible channel
instead of surfacing as silent noncompliance or quiet drift from spec.

Agents cannot write or accept edicts (see `README.md`). Dissent is the
counterpart to that rule: no pen, but a voice.

## Constraints
- Dissents live in `docs/edicts/dissents/NNNN-<agent>.md`, where `NNNN` is the
  edict they concern.
- A dissent states: what it objects to, why, and what it would do instead.
- Filing a dissent pauses work on that edict. It never cancels, edits, or
  rewrites the edict.
- Only Kohl resolves a dissent: amend the edict, overrule the dissent, or the
  agent withdraws it.
- Resolved dissents, including overruled ones, stay on record with the
  resolution noted.

## Acceptance criteria
- `daedalus edict dissent <id>` files a dissent; `daedalus edict dissents`
  lists open ones; Kohl can resolve one with a recorded outcome.
- An edict with an open dissent cannot be dispatched to workers.
- The semantic judge may cite an open dissent as grounds for `NEEDS_HUMAN`.
- Dissent history is preserved; nothing is deleted on resolution.

## Non-goals
- No veto. Dissent pauses; it doesn't decide.
- No agent-to-agent negotiation. Dissent goes to the human.
