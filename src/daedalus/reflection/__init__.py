"""
Reflection over Claude Code session logs (edict 0010).

Claude Code writes a transcript of every session and deletes it after `cleanupPeriodDays`. This
package turns them into something that lasts and can be learned from:

1. Digests (deterministic, no model calls): one JSON summary per session, with citable event
   UUIDs behind every count (`digest`). `tick` digests every project and updates what is due.
2. Due state (`due`): which daily, weekly and monthly reflections are due. Only periods with
   sessions are ever due; small days roll into the week; higher levels absorb lower ones.
3. Reflection (model-written, by the `delphi` agent): reports with findings and proposals, which
   `check` validates deterministically and Momus reviews before anyone sees them.
4. The pending queue (`pending`): proposals are applied only by the user, one at a time.
5. Models (`models`): the user model and the self model, with an append-only history, decay on
   read, and aspirations Daedalus writes itself.
"""
