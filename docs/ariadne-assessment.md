# Ariadne/Icarus assessment: experimental status review

**Date:** 2026-10-13
**Trigger:** Ariadne (`src/daedalus/ariadne/`, ~3,900 lines) and the Icarus worker
harness (`src/daedalus/worker/harness.py`, ~670 lines) have been labeled
"Experimental" in the README since inception, with `icarus.enabled` and
`ariadne.enabled` both defaulting to `false`. Before this review, the only test
coverage was a handful of unit tests for `diff_bus.py` parsing and
`conflict_detector.py` classification added in a prior pass — nothing exercised
the orchestrator's actual daemon cycle, the verification gate's execution path,
or a real `git apply` + commit. This was a "prove it or shelve it" experiment
rather than an open-ended hardening effort: one bounded smoke test plus targeted
unit tests, scoped to produce a real verdict either way.

## Why this matters beyond "does the code run"

The architectural pitch of Ariadne is that *workers* (Icarus instances) don't
need to be a careful, expensive model babysitting merge safety — they just
submit diffs, and Ariadne's conflict-detection + verification gate is supposed
to be the actual safety net. If that gate is solid and deterministic, it's
exactly the kind of mechanical, well-specified logic that would let **cheaper
or smaller models** drive Icarus workers unsupervised, with Ariadne (not the
worker's own judgment) preventing unsafe simultaneous edits from landing. If
the gate itself is shaky, routing smaller models through it means routing them
through an unverified safety net — the opposite of what you'd want.

## What was tested

`tests/test_ariadne_e2e_smoke.py` — drives the **real** orchestrator against a
real temporary git repo, the same code path `ariadne process`/`ariadne daemon`
use in production:

1. **Non-overlapping diffs** (two simulated workers editing different files):
   submit → verify → detect conflicts → merge → `git apply` → `git commit`.
   Asserts both changes land in a single atomic commit and the bus's own
   status bookkeeping agrees.
2. **Conflicting diffs** (two workers editing the same lines of the same
   file): confirms the conflict gate correctly escalates and **blocks**
   auto-commit — the repo's working tree is left untouched, no partial merge.
3. **Mixed verify/reject**: one diff passes verification, one is forced to
   fail; confirms only the passing diff's change is merged in, not
   all-or-nothing.

`tests/test_ariadne_planner.py` — unit tests for `Planner._calculate_complexity`
and `Planner._check_requires_approval`, the pure decision logic that gates
whether a plan can auto-dispatch or needs a human/frontier-model in the loop.
Covers all three autonomy modes (`supervised`, `hybrid`, `full`), complexity
scoring and its cap, and tag-based approval requirements.

**Result: 11 new tests, all passing on the first real run except one (see
Finding 1, fixed below). 97 total tests passing** (was 86 before this
assessment).

## Findings

### Finding 1 (bug, fixed): merged diffs were being misfiled as rejected

`AriadneBus.update_diff_status()` only routed diffs to `pending`/`verified`/
`rejected` buckets. When the orchestrator calls it with `DiffStatus.MERGED`
after a successful commit, the status fell through to the `else` branch and
was written into the **rejected** directory — with `diff.status` correctly
saying `"merged"` in the JSON, but physically filed next to real rejections.
`AriadneBus.status_summary()` (what `ariadne status` prints) had no "merged"
bucket at all, so every successful merge silently inflated the reported
rejection count and gave no visibility into how many diffs had actually
landed.

This was caught immediately by the first smoke-test run (`bus_status["diffs"]
["verified"] == 2` failed with `0`), which is itself evidence for the
"shaky vs. solid" question above: a one-line gap in status routing had been
sitting unexercised in a core bookkeeping path. **Fixed** in `diff_bus.py`:
added a dedicated `merged` bucket to `AriadneBus.dirs`, routed `MERGED` status
updates there, and surfaced it in `status_summary()`. The underlying merge/
commit logic itself (conflict detection, verification gating, `git apply`,
atomic commit) was correct — this was purely a status-reporting bug, not a
correctness bug in what actually gets committed.

### Finding 2: the verification gate's core logic held up

Beyond the one status-routing bug, the orchestration logic itself behaved
exactly as documented on every attempt:
- Non-overlapping diffs merge cleanly into one atomic commit.
- Overlapping diffs are detected and the merge is correctly blocked rather
  than attempted-and-failed.
- Rejected diffs are excluded from the commit rather than dragging the whole
  batch down.

This is the part that matters most for the "smaller models as workers"
framing — the safety-critical path (don't merge conflicting or failing
changes) worked correctly without needing to be babysat.

### Finding 3: the planner's autonomy gating is sound and does what it claims

All three autonomy modes behaved exactly as configured: `supervised` always
requires approval, `full` never does (confirmed this holds even with a tagged,
maximally-complex request — there is genuinely no safety net left in that mode
except Ariadne's downstream conflict/verification gate), and `hybrid` correctly
gates on both configured tags and the complexity threshold. No surprises here;
this logic is simple enough that it was unlikely to be wrong, and testing
confirmed that.

### Finding 4 (observation, not a bug): verification is real but expensive

`CausalSliceVerifier.verify()` does a full `shutil.copytree` of the repo into a
temp workspace *per diff* before type-checking/linting/testing it. That's
correct and isolated, but means verification cost scales with repo size, not
diff size — worth knowing before running this against anything larger than a
small project. Not exercised at scale in this review (the smoke test used a
2-file repo with no-op check commands by design, to keep the test hermetic and
independent of which lint/type tools happen to be installed).

## What graduating further would require

This review covered the core merge/verification/gating path end-to-end and the
planner's decision logic, but **not**: `dispatcher.py` (347 lines, worker
dispatch), `tracker.py` (372 lines, work tracking), or
`worker/harness.py` (671 lines, the actual Icarus worker process) — none of
which have any test coverage yet. Before calling this subsystem production-
ready rather than "the core logic has been smoke-tested," those would need the
same treatment: real dispatch of a synthetic worker process, not just the
bus/orchestrator side.

## Recommendation

**Promote from "Experimental" to "Beta" in spirit, not yet in the README
wording.** The core safety-critical path (conflict detection, verification
gating, atomic merge) is sound, and the one real bug found was in status
*reporting*, not in what actually gets committed to the repo. That's a
meaningfully better result than "mostly broken" or "well, it probably works."
But `dispatcher`/`tracker`/the worker harness are still completely unverified,
and real-world usage (actual Icarus workers, actual LLM-generated diffs, a
real-sized repo) hasn't been attempted. Keep both feature flags default-off
until a dogfood period covers the dispatch/worker side too; this assessment is
evidence the foundation is solid enough to be worth that next step, not a
signal to flip the flags on yet.
