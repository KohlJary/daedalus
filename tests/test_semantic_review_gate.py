"""
Semantic review gate tests (Workstream D).

CausalSliceVerifier only checks mechanical correctness (typecheck/lint/
tests); nothing previously checked whether a diff actually implemented what
was asked. These tests cover the new gate added between conflict resolution
and commit:

- SemanticReviewer stub harness (no real LLM calls -- LLMJudge's fail-closed
  path is covered separately) exercising the autonomy-mode policy table.
- AriadneBus's approve_review()/reject_review() resolving a NEEDS_REVIEW diff.
- Tracker's approve_review()/reject_review() actually resolving the
  previously dead-end "review" status.
- LLMJudge failing closed to NEEDS_HUMAN when claude-agent-sdk isn't
  installed, rather than silently approving.
"""

import subprocess
from pathlib import Path

import pytest

from daedalus.ariadne.diff_bus import AriadneBus, Diff, DiffStatus
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.planner import FeatureRequest, ImplementationPlan
from daedalus.ariadne.semantic_review import HAS_AGENT_SDK, LLMJudge, ReviewVerdict, SemanticReviewResult
from daedalus.ariadne.tracker import Tracker
from daedalus.ariadne.verification import CausalSliceVerifier

from ariadne_intent import approved_plan, tag


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )


def _init_repo(repo: Path) -> None:
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test Runner")
    (repo / "file_a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial commit")


def _capture_worker_diff(repo: Path, filename: str, new_content: str) -> str:
    (repo / filename).write_text(new_content, encoding="utf-8")
    diff = _run_git(repo, "diff", "--", filename).stdout
    _run_git(repo, "checkout", "--", filename)
    return diff


def _noop_verifier(repo_path: Path) -> CausalSliceVerifier:
    noop = ["python", "-c", "import sys"]
    return CausalSliceVerifier(
        repo_path, typecheck_cmd=noop, lint_cmd=noop, test_cmd=noop, require_tests=False
    )


class _ScriptedReviewer:
    """Stub SemanticReviewer returning a fixed verdict for every diff."""

    def __init__(self, verdict: ReviewVerdict, reasoning: str = "stub"):
        self.verdict = verdict
        self.reasoning = reasoning
        self.calls = []

    def review(self, diff, intent, verification=None) -> SemanticReviewResult:
        self.calls.append((diff.id, intent))
        return SemanticReviewResult(
            diff_id=diff.id,
            verdict=self.verdict,
            reasoning=self.reasoning,
            reviewer="scripted-stub",
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


def _submit_diff(repo, bus, intent="Add feature X") -> Diff:
    diff_content = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 42\n")
    diff = Diff.from_git_diff("work-1", "worker-1", diff_content, intent)
    tag(diff, approved_plan(repo, intent))  # approved intent, so the judge's verdict decides (0001)
    bus.submit_diff(diff)
    return diff


# ---------- Autonomy-mode policy table ----------

def test_full_autonomy_commits_on_judge_approval(repo, bus):
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="full",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.commits_created == 1
    assert result.diffs_needs_review == 0
    assert bus.status_summary()["diffs"]["merged"] == 1


def test_full_autonomy_queues_review_on_judge_non_approval(repo, bus):
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="full",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.NEEDS_HUMAN),
    )
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.commits_created == 0
    assert result.diffs_needs_review == 1
    pending = bus.list_needs_review_diffs()
    assert len(pending) == 1
    assert pending[0].semantic_review["verdict"] == "needs_human"


def test_judge_rejection_is_routed_to_review_not_final_rejection(repo, bus):
    """
    A judge REJECTED verdict must never unilaterally finalize a diff as
    REJECTED -- only a human resolving the review queue can do that. The
    judge can only unilaterally say yes.
    """
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="full",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.REJECTED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    orchestrator.process_pending()

    assert bus.status_summary()["diffs"]["needs_review"] == 1
    assert bus.status_summary()["diffs"]["rejected"] == 0


def test_supervised_autonomy_always_queues_review_even_if_approved(repo, bus):
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="supervised",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.commits_created == 0
    assert result.diffs_needs_review == 1


def test_hybrid_autonomy_queues_review_for_flagged_tags_even_if_approved(repo, bus):
    diff_content = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 42\n")
    diff = Diff.from_git_diff("work-1", "worker-1", diff_content, "Change the schema")
    tag(diff, approved_plan(repo, "Change the schema"))
    diff.metadata["tags"] = ["database"]
    bus.submit_diff(diff)

    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="hybrid",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.commits_created == 0
    assert result.diffs_needs_review == 1


def test_hybrid_autonomy_commits_when_approved_and_untagged(repo, bus):
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="hybrid",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    result = orchestrator.process_pending()

    assert result.commits_created == 1


# ---------- Resolving the review queue ----------

def test_bus_approve_review_moves_diff_back_to_verified(repo, bus):
    diff = _submit_diff(repo, bus)
    reviewer = _ScriptedReviewer(ReviewVerdict.APPROVED)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="supervised",
        semantic_reviewer=reviewer,
    )
    orchestrator.verifier = _noop_verifier(repo)
    orchestrator.process_pending()

    pending = bus.list_needs_review_diffs()
    assert len(pending) == 1

    assert bus.approve_review(pending[0].id, approved_by="kohl") is True

    resolved = bus.get_diff(pending[0].id)
    assert resolved.status == DiffStatus.VERIFIED
    assert resolved.semantic_review["resolution"] == "approved"
    assert resolved.semantic_review["resolved_by"] == "kohl"

    calls_before = len(reviewer.calls)

    # The spawning agent would call resolve_and_commit (or ariadne's CLI
    # equivalent) after a human approves -- it rechecks all VERIFIED diffs,
    # not just ones freshly verified this cycle. It must not re-invoke the
    # judge on a diff a human already resolved.
    result = orchestrator.resolve_and_commit({})
    assert result.commits_created == 1
    assert len(reviewer.calls) == calls_before


def test_process_pending_picks_up_a_previously_approved_diff(repo, bus):
    """
    Real bug found by manually smoke-testing the CLI review loop: `ariadne
    process --auto-commit` calls process_pending(), which used to (a) only
    look at diffs it verified *this* cycle, and (b) early-return before even
    reaching the commit phase whenever there were no new PENDING diffs --
    so a diff approved out of NEEDS_REVIEW (which moves it to VERIFIED, not
    PENDING) was never picked up by a subsequent `ariadne process` call.
    Only the separate resolve_and_commit() path (not CLI-reachable) handled
    it. This is the exact loop a human approving a review in conversation
    would trigger: approve, then re-run `ariadne process`.
    """
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="supervised",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)

    first = orchestrator.process_pending()
    assert first.commits_created == 0
    assert first.diffs_needs_review == 1

    pending = bus.list_needs_review_diffs()
    assert bus.approve_review(pending[0].id) is True

    # No new diffs submitted -- this call has nothing new to verify, but the
    # previously-approved diff must still get committed.
    second = orchestrator.process_pending()
    assert second.commits_created == 1
    assert bus.status_summary()["diffs"]["merged"] == 1


def test_bus_reject_review_moves_diff_to_rejected(repo, bus):
    diff = _submit_diff(repo, bus)
    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="supervised",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
    )
    orchestrator.verifier = _noop_verifier(repo)
    orchestrator.process_pending()

    pending = bus.list_needs_review_diffs()
    assert bus.reject_review(pending[0].id, "wrong approach", rejected_by="kohl") is True

    resolved = bus.get_diff(pending[0].id)
    assert resolved.status == DiffStatus.REJECTED
    assert resolved.semantic_review["resolution"] == "rejected"
    assert resolved.semantic_review["resolution_reason"] == "wrong approach"


def test_approve_reject_return_false_for_diff_not_pending_review(bus, repo):
    diff = _submit_diff(repo, bus)
    assert bus.approve_review(diff.id) is False
    assert bus.reject_review(diff.id, "nope") is False
    assert bus.approve_review("not-a-real-id") is False


# ---------- Tracker wiring ----------

@pytest.fixture
def tracker(tmp_path: Path) -> Tracker:
    return Tracker(roadmap_path=tmp_path / "roadmap")


def _start_tracked_feature(tracker: Tracker, plan_id: str) -> None:
    request = FeatureRequest(id="feat-1", title="Feature One", description="Do the thing")
    plan = ImplementationPlan(
        id=plan_id, feature_id="feat-1", feature_title="Feature One",
        summary="Do the thing", work_packages=[],
    )
    tracker.start_feature(request, plan)


def test_tracker_queues_feature_for_review_when_diff_is_queued(repo, bus, tracker):
    diff_content = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 42\n")
    diff = Diff.from_git_diff("plan-1", "worker-1", diff_content, "Do the thing")
    diff.metadata["plan_id"] = "plan-1"
    bus.submit_diff(diff)

    _start_tracked_feature(tracker, "plan-1")

    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="supervised",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
        tracker=tracker,
    )
    orchestrator.verifier = _noop_verifier(repo)
    orchestrator.process_pending()

    progress = tracker.get_feature_progress("plan-1")
    assert progress is not None
    assert progress.status == "verifying"  # feature_item.status == "review"
    items = tracker._load_items_by_plan("plan-1")
    feature_item = next(i for i in items if i.item_type == "feature")
    assert feature_item.status == "review"


def test_tracker_resolves_to_done_after_commit(repo, bus, tracker):
    diff_content = _capture_worker_diff(repo, "file_a.py", "def a():\n    return 42\n")
    diff = Diff.from_git_diff("plan-1", "worker-1", diff_content, "Do the thing")
    tag(diff, approved_plan(repo, "Do the thing", plan_id="plan-1"))
    bus.submit_diff(diff)

    _start_tracked_feature(tracker, "plan-1")

    orchestrator = AriadneOrchestrator(
        repo, bus=bus, auto_commit=True, autonomy="full",
        semantic_reviewer=_ScriptedReviewer(ReviewVerdict.APPROVED),
        tracker=tracker,
    )
    orchestrator.verifier = _noop_verifier(repo)
    result = orchestrator.process_pending()

    assert result.commits_created == 1
    items = tracker._load_items_by_plan("plan-1")
    feature_item = next(i for i in items if i.item_type == "feature")
    assert feature_item.status == "done"
    assert feature_item.commit_hash


def test_tracker_approve_review_resolves_review_to_done(tracker):
    _start_tracked_feature(tracker, "plan-2")
    tracker.complete_feature("plan-2", commit_hash=None)

    items = tracker._load_items_by_plan("plan-2")
    feature_item = next(i for i in items if i.item_type == "feature")
    assert feature_item.status == "review"

    resolved = tracker.approve_review("plan-2", commit_hash="abc123")
    assert resolved.status == "done"
    assert resolved.commit_hash == "abc123"


def test_tracker_reject_review_resolves_review_to_backlog(tracker):
    _start_tracked_feature(tracker, "plan-3")
    tracker.complete_feature("plan-3")

    resolved = tracker.reject_review("plan-3", "missed an edge case")
    assert resolved.status == "backlog"
    assert "missed an edge case" in resolved.description


# ---------- LLMJudge fail-closed path ----------

def test_llm_judge_fails_closed_without_agent_sdk():
    """
    In this test environment claude-agent-sdk is not installed, so
    HAS_AGENT_SDK is False and the judge must route to NEEDS_HUMAN rather
    than silently approving -- the one failure mode this module exists to
    prevent.
    """
    if HAS_AGENT_SDK:
        pytest.skip("claude-agent-sdk is installed in this environment; "
                    "fail-closed path isn't exercised without mocking it out.")

    diff = Diff(
        id="d1", work_id="w1", instance_id="worker-1",
        content="--- a\n+++ b\n", description="Some change",
    )
    judge = LLMJudge()
    result = judge.review(diff, "Some intent")

    assert result.verdict == ReviewVerdict.NEEDS_HUMAN
    assert "not installed" in result.reasoning
