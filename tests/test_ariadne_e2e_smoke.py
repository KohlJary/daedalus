"""
Ariadne end-to-end smoke test (Workstream C).

This is the "prove it or shelve it" experiment for the Ariadne/Icarus subsystem:
~3,900 lines across diff_bus/conflict_detector/verification/planner/dispatcher/
tracker/orchestrator, labeled "Experimental" in the README, both feature flags
default off, and (before this file) zero tests exercised the actual daemon
cycle, verification execution, or a real git apply + commit.

These tests drive the real orchestrator against a real (temporary) git repo:
submit diffs the way an Icarus worker would -> run one `process_pending()`
cycle (the same cycle `ariadne process`/`ariadne daemon` run) -> verify the
combined diff actually gets `git apply`'d and committed, or that conflicting
diffs are correctly blocked from auto-commit.

Why this matters beyond "does the code run": the appeal of Ariadne is that the
*workers* (Icarus instances) don't need to be a frontier model babysitting
merge safety -- Ariadne's conflict detection + verification gate is supposed to
be the safety net. If that gate is solid and deterministic, it's what would
let cheaper/smaller models run as workers safely. If it isn't, routing small
models through it would be routing them through an unverified safety net.
"""

import subprocess
from pathlib import Path

import pytest

from ariadne_intent import approved_plan, tag

from daedalus.ariadne.diff_bus import AriadneBus, Diff
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.semantic_review import ReviewVerdict, SemanticReviewResult
from daedalus.ariadne.verification import CausalSliceVerifier


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def _init_repo(repo: Path) -> None:
    """A minimal git repo with two independent files, committed to HEAD."""
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test Runner")

    (repo / "file_a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (repo / "file_b.py").write_text("def b():\n    return 2\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial commit")


def _capture_worker_diff(repo: Path, filename: str, new_content: str) -> str:
    """
    Simulate an Icarus worker: make an edit, capture it as a `git diff` the
    way a worker would hand off to Ariadne's bus instead of committing
    directly, then revert the working tree so the next "worker" starts clean.
    """
    (repo / filename).write_text(new_content, encoding="utf-8")
    diff = _run_git(repo, "diff", "--", filename).stdout
    _run_git(repo, "checkout", "--", filename)
    return diff


def _noop_verifier(repo_path: Path) -> CausalSliceVerifier:
    """
    A verifier wired with harmless no-op commands instead of real mypy/ruff/
    pytest invocations, so the smoke test exercises the orchestration logic
    (verify -> detect conflicts -> merge -> commit) deterministically, without
    depending on which lint/type tools happen to be installed in whatever
    environment runs the suite.
    """
    noop = ["python", "-c", "import sys"]
    return CausalSliceVerifier(
        repo_path, typecheck_cmd=noop, lint_cmd=noop, test_cmd=noop
    )


class _ApproveAllReviewer:
    """
    Stub SemanticReviewer for tests that only exercise the mechanical
    verify/conflict/commit pipeline -- no real LLM calls. Approves everything
    so those tests aren't incidentally exercising the semantic review gate
    (that gate gets its own dedicated tests).
    """

    def review(self, diff, intent, verification=None) -> SemanticReviewResult:
        return SemanticReviewResult(
            diff_id=diff.id,
            verdict=ReviewVerdict.APPROVED,
            reasoning="stub reviewer: always approves",
            reviewer="stub-approve-all",
        )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo(repo_dir)
    return repo_dir


@pytest.fixture
def bus(tmp_path: Path) -> AriadneBus:
    bus = AriadneBus(root=tmp_path / ".ariadne")
    bus.initialize()
    return bus


def test_non_overlapping_diffs_are_verified_merged_and_committed(repo, bus):
    """
    Two "workers" touch different files. This is the case Ariadne exists for:
    collect diffs instead of racing commits, verify them, and merge both into
    one atomic commit with no conflicts.
    """
    diff_a = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 100\n")
    diff_b = _capture_worker_diff(repo, "file_b.py", "def b():\n    return 200\n")

    plan = approved_plan(repo, "Update a() and b()", packages=("wp-a", "wp-b"))
    bus.submit_diff(tag(Diff.from_git_diff("work-a", "worker-1", diff_a, "Update a()"), plan, "wp-a"))
    bus.submit_diff(tag(Diff.from_git_diff("work-b", "worker-2", diff_b, "Update b()"), plan, "wp-b"))

    orchestrator = AriadneOrchestrator(repo, bus=bus, auto_commit=True, semantic_reviewer=_ApproveAllReviewer())
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.errors == []
    assert result.diffs_processed == 2
    assert result.diffs_verified == 2
    assert result.diffs_rejected == 0
    assert result.conflicts_detected == 0
    assert result.commits_created == 1

    # The merge actually landed in the real working tree, not just the bus's
    # bookkeeping -- both workers' changes are present after one commit.
    assert "return 100" in (repo / "file_a.py").read_text(encoding="utf-8")
    assert "return 200" in (repo / "file_b.py").read_text(encoding="utf-8")

    log = _run_git(repo, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 2  # initial commit + Ariadne's atomic commit

    bus_status = bus.status_summary()
    # Once merged, diffs move out of "verified" into their own "merged" bucket
    # (a bug found by this test: update_diff_status() used to have no route for
    # DiffStatus.MERGED and silently misfiled merged diffs into "rejected" --
    # fixed in diff_bus.py alongside this test).
    assert bus_status["diffs"]["verified"] == 0
    assert bus_status["diffs"]["merged"] == 2
    assert bus_status["diffs"]["rejected"] == 0
    assert bus_status["merges"] == 1


def test_conflicting_diffs_are_blocked_from_auto_commit(repo, bus):
    """
    Two "workers" touch the same lines of the same file. Verification passes
    for each individually, but the conflict gate must stop the merge -- this
    is the exact failure mode that matters if small/cheap models are driving
    workers: the gate, not the worker's own judgement, is what prevents a bad
    simultaneous edit from landing.
    """
    diff_a = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 'from worker 1'\n")
    diff_b = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 'from worker 2'\n")

    # Approved intent for both, so the conflict gate (not the intent gate) is what stops the merge
    plan = approved_plan(repo, "Edit a()", packages=("wp-a", "wp-b"))
    bus.submit_diff(tag(Diff.from_git_diff("work-a", "worker-1", diff_a, "Worker 1 edits a()"), plan, "wp-a"))
    bus.submit_diff(tag(Diff.from_git_diff("work-b", "worker-2", diff_b, "Worker 2 edits a()"), plan, "wp-b"))

    orchestrator = AriadneOrchestrator(repo, bus=bus, auto_commit=True, semantic_reviewer=_ApproveAllReviewer())
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.diffs_verified == 2  # each diff is individually valid
    assert result.conflicts_detected >= 1
    assert result.commits_created == 0  # escalated conflict must block the merge
    assert result.diffs_held == 2 and len(bus.list_conflicts(resolved=False)) == 1

    # The repo's working tree is untouched -- no partial/unsafe merge happened.
    assert "def a():\n    return 1\n" == (repo / "file_a.py").read_text(encoding="utf-8")

    log = _run_git(repo, "log", "--oneline").stdout.strip().splitlines()
    assert len(log) == 1  # only the initial commit


def test_rejected_diff_is_excluded_from_the_commit(repo, bus, monkeypatch):
    """
    A diff that fails verification must not be silently merged in alongside
    diffs that pass -- the whole point of the verification gate is per-diff
    accept/reject, not all-or-nothing.
    """
    diff_a = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 999\n")
    diff_b = _capture_worker_diff(repo, "file_b.py", "def b():\n    return 999\n")

    plan = approved_plan(repo, "Two changes", packages=("wp-a", "wp-b"))
    diff_obj_a = tag(Diff.from_git_diff("work-a", "worker-1", diff_a, "Good change"), plan, "wp-a")
    diff_obj_b = tag(Diff.from_git_diff("work-b", "worker-2", diff_b, "Change that fails verification"), plan, "wp-b")
    bus.submit_diff(diff_obj_a)
    bus.submit_diff(diff_obj_b)

    orchestrator = AriadneOrchestrator(repo, bus=bus, auto_commit=True, semantic_reviewer=_ApproveAllReviewer())
    orchestrator.verifier = _noop_verifier(repo)

    real_verify = orchestrator.verifier.verify

    def fake_verify(diff, causal_chain=None):
        verification = real_verify(diff, causal_chain)
        if diff.id == diff_obj_b.id:
            verification.passed = False
            verification.test_errors = ["simulated failure"]
        return verification

    monkeypatch.setattr(orchestrator.verifier, "verify", fake_verify)

    result = orchestrator.process_pending()

    assert result.diffs_verified == 1
    assert result.diffs_rejected == 1
    assert result.commits_created == 1

    assert "return 999" in (repo / "file_a.py").read_text(encoding="utf-8")
    # The rejected diff's change must not have been applied.
    assert "return 999" not in (repo / "file_b.py").read_text(encoding="utf-8")

