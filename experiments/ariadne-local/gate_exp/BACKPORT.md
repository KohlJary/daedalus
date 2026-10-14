Snapshot of src/ at ad1675c (mature/BASE_COMMIT) with one backport from PR #24:
_create_atomic_commit applies the merged diff with `git apply --index` and commits only what is staged
(no `git commit -a`). Without it, new files from merged diffs are never committed, so dependent
work packages (worktrees from HEAD) cannot see them, and modified tracked files outside the diff get swept in.
Applied 2026-10-13 before the multi-wave feature runs; the gate-only runs (exp.py gen/judge) never commit.
