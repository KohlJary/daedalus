# Status

*Committed handoff snapshot. Daedalus updates this at the end of each working
session so work can be picked up from outside the session. See
`docs/edicts/README.md`.*

**Last updated:** 2026-10-13, by a Daedalus session (on `main`)

## Current phase
Gameplan (`.daedalus/roadmap/gameplan.json`, local) created this session:
- **p1-edicts-ariadne** (active): build edicts 0001, 0002, 0003, 0005; verifier
  fails closed and gains an import/build check (#15); bugs #13, #14; local
  backends + live tier (#16) blocked on an edict.
- **p2-memory-backbone** (planned): edict 0004.
- **p3-theseus-index** (planned): index, status, and linkage for Theseus reports.
- **p4-evidence** (planned): resume benchmark against plain Claude Code, with
  cost telemetry and a falsifier registered with Momus first.

## Edicts
| Edict | Status | Built? | Notes |
|-------|--------|--------|-------|
| 0001 Intent flows from edicts | accepted | no | Header reads `Status: acccepted` (typo); Kohl to fix. Build behind 0005's intent-source interface. |
| 0002 Model casting | accepted | no | Non-goal narrowed by 2026-10-13 amendment; local backends still need their own edict (#16). |
| 0003 Dissent | accepted | no | Depends on 0001's edict CLI. |
| 0004 Memory backbone | accepted | no | `daedalus doctor`, gameplan-first session-start hook, proposal-only capture hook, optional free-form memory. |
| 0005 Edicts opt-in, intent from any source | accepted | no | `edicts.enabled` (default off); intent-source interface with edict and github-issue sources. |

0004 and 0005 were drafted by Daedalus at Kohl's request and committed to
`main` directly at his instruction.

## Open dissents
None.

## In flight
- Issues: #1, #2 (palace), #6 (hydrate edited-file detection), #13, #14, #15, #16.

## Last session
Surveyed real Daedalus usage to pick the next value-add:
- cass-vessel: Theseus heavily used (~50 reports); session summaries have a
  53-day gap over the busiest stretch; roadmap empty but still queried by the
  session-start hook.
- wonderland-ai: gameplan heavily used (27 phases, rich resolutions) but not
  updated after 2026-05-18 while work ran to 2026-06-23; session summaries never
  written. LLM review passed code that failed at import.
- Conclusion: structured, task-shaped memory gets written; free-form memory
  doesn't; both go stale unless drift is surfaced. Led to edicts 0004 and 0005.

Found: the session-start hook reads `data/roadmap/index.json` (a cass-vessel
path), not `.daedalus/roadmap/` (covered by 0004).

**Guardrail:** never run live model calls (workers, judge, the live tier) on
an employer's account or machine. The hermetic tier needs no model.

**Next, in order:** T-e1 + T-e7 (0001 behind 0005's intent-source interface),
then T-e2, T-e3, T-e4; then activate p2 for edict 0004.
