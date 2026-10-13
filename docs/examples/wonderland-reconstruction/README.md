# Reference example: wonderland-ai gameplan reconstruction

The first memory reconstruction, run by hand on 2026-10-13 before any tooling
existed. It is the reference example for [edict 0006](../../edicts/0006-memory-reconstruction.md).

[wonderland-ai](https://github.com/KohlJary/wonderland-ai)'s gameplan was last
committed on 2026-05-18 (`ccaf3f7`), but work continued to 2026-06-23
(`73c0800`): 95 commits and releases 0.8.1 to 0.12.1 that the gameplan didn't
record.

- `gameplan-reconstruction.json` is the proposal, as corrected after review:
  updates to existing tasks, 5 phases, 24 tasks, and roadmap drift. Every
  resolution cites commits and carries a confidence label. It was never
  applied to wonderland-ai's gameplan.
- `momus-review.md` is Momus's review of the version before corrections. It
  found 22 entries shown, 3 consistent, 2 contradicted, and every cited hash
  correct.

## What it found
- A task left `in_progress` since May (T-a1, milestone deletion) was probably
  fixed in June under another name (`5abfd9c`). The fix's own regression test
  fails against the May code, and an mvp-demo run log fits the timeline. Momus
  rated it "consistent, strongly", not shown, and named the cheapest check
  that would settle it.
- Four roadmap items that shipped in 0.11.0 were still marked `backlog`. Momus
  found many more candidates.

## What it got wrong (and what edict 0006 now requires because of it)
- A number misquoted, and a projection reported as a measurement -> every
  number cites its source file.
- A figure attributed to the wrong file -> the same.
- One of two conflicting commit messages taken as fact -> when sources
  disagree, both are recorded.
- A pilot called silent when 53 runs (~$188) sat in gitignored files ->
  evidence paths outside git can be configured.
- Roadmap drift checked by eye -> checked item by item.
- 23 of 95 commits uncited, with nothing flagging it -> `reconstruct check`
  reports coverage.
