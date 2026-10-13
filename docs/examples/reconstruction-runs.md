# Reconstruction runs: rich vs. sparse commit messages

Edict 0006 asks for one run on a repository with sparse commit messages, reported next to the
wonderland-ai reference. Both runs are from 2026-10-13.

| | wonderland-ai ([reference](wonderland-reconstruction/)) | temple-codex |
|---|---|---|
| How it was run | By hand, before the tooling and schema existed | The 0006 pipeline: `gather`, the mnemosyne instructions, `check`, Momus |
| Window | 95 commits, 2026-05-18 to 2026-06-23 (the gap after the gameplan's last update) | 91 commits, 2025-11-03 to 2026-10-12 (whole history; no gameplan) |
| Commit messages | Long bodies, task IDs, release summaries | 83 of 91 have no body; subjects often poetic or jokes |
| Message score (0-100) | 0 of 94 scored below 50 | Median 21; 87 of 91 below 50, so their diffs went into the bundle |
| Entries proposed | 5 phases, 24 tasks, 3 task updates, 4 roadmap changes | 8 phases, 35 tasks (no gameplan or roadmap to update) |
| Proposer's labels | Not yet labelled per entry (pre-schema) | 40 shown, 0 inferred, 3 unknown |
| `reconstruct check` | Not available then | Passes; all 91 commits cited |
| Momus | 27 entries: 22 shown, 3 consistent, 2 contradicted | 24 of 43 entries checked: 21 shown, 2 unknown confirmed, 0 contradicted |
| Errors Momus found | A misquoted number, a misattributed source, a conflict taken as fact, evidence outside git called silent, a missing referenced file, thin roadmap coverage, 23 uncited commits | A line citation off by one, one sentence judging an essay instead of describing it, a guessed source for a figure |

## What the comparison shows

- **Sparse messages didn't sink it, because the diffs carried the evidence.** On temple-codex the
  scoring sent 87 of 91 commits' diffs into the bundle; the proposer read what each commit did
  rather than what its subject said (a commit titled "Housekeeping" turned out to delete the
  project's lore and community documents).
- **The rules from the first run held.** Every error class the hand run made is now either
  impossible to get past `check` (missing files, uncited commits, `done` on weak evidence,
  roadmap items skipped) or written into the proposer's rules (sources next to numbers,
  conflicts recorded both ways), and the temple-codex errors were minor.
- **Calibration caveat.** Momus judged "shown" earned for what the diffs contain, but noted that
  zero "inferred" is slightly generous: some phase notes admit inference (phase names) while the
  phase is labelled shown, and for a transcript or test log "shown" means the commit adds the
  file, not that its result holds.
- **What a reconstruction can surface.** Reading the diffs of a sparsely documented history, the
  temple-codex run found results that the project's own write-up summarizes more favourably than
  its logs support. Momus re-derived both independently. The proposal itself is kept with the
  project, not here.
