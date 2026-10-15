"""
Dreaming (edict 0013): a protected phase where Daedalus generates widely, judged only afterwards and
only by the owner.

One night's dream is three steps, each with its own output, under `.daedalus/dreams/<id>/`:
- **seeds** (`seeds.json`): chosen deterministically by readiness (seeds.py);
- **the dream** (`dream.md`): written hot by Morpheus, in `list` or `narrative` mode, or by a plain
  agent with no dream frame (`plain`, the no-dream arm);
- **the waking pass** (`waking.md`): a cold agent that did not dream lists the ideas and picks three to
  five.

The only way a dream reaches the plan is the `dream` source (sources/dream.py): picks, and themes that
recur across dreams (review.py), arrive as roadmap proposals the owner applies or drops. A dream is never
evidence: reflection can't cite one, and the models never take an entry from one.

Nothing here is imported by hooks; the inhale brief reads `.daedalus/dreams/due.json` as raw JSON.
"""
