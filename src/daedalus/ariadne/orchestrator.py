"""
Ariadne Orchestrator

The main coordination loop that holds the thread through the labyrinth.

Responsibilities:
1. Watch for incoming diffs from Icarus workers
2. Run causal slice verification on each diff
3. Detect conflicts between diffs
4. Resolve conflicts (auto or escalate)
5. Merge verified diffs into atomic commits
6. Notify workers of success/failure

The orchestrator can run as:
- One-shot: Process all pending diffs once
- Daemon: Continuously watch for new diffs
- Interactive: Process with Daedalus oversight
"""

import asyncio
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Callable, Any
import json

from .diff_bus import (
    AriadneBus,
    Diff,
    DiffStatus,
    Conflict,
    MergeResult,
    MergeStrategy,
)
from .conflict_detector import ConflictDetector, ConflictAnalysis, ConflictSeverity
from .verification import CausalSliceVerifier, VerificationResult, extract_causal_chain
from .semantic_review import LLMJudge, ReviewVerdict, SemanticReviewer, SemanticReviewResult
from .tracker import Tracker
from ..config import get_daedalus_email, load_config


def _commit_args(message: str, paths: Optional[List[str]] = None) -> List[str]:
    """
    Build the `git commit` argument list honoring the configured git.authorship.

    daedalus (default): authored as Daedalus via --author, matching what the CLAUDE.md
    template tells Claude to type by hand.
    user: no --author (commits as the configured git identity), with a '- Daedalus'
    sign-off appended to the body, matching the template's `git.authorship=user` text.

    With paths, only those paths are committed (`--only`), so nothing else that happens to be
    modified in the repository (plans, the gameplan, a human's work in progress) rides along.
    """
    config = load_config()
    scope = ["--only", *paths] if paths else ["-a"]
    if config.git.authorship == "user":
        signed_message = message.rstrip("\n") + "\n\n- Daedalus\n"
        return ["git", "commit", *scope, "-m", signed_message]

    email = get_daedalus_email(config)
    return ["git", "commit", *scope, f"--author=Daedalus <{email}>", "-m", message]


@dataclass
class OrchestrationResult:
    """Result of an orchestration cycle."""
    diffs_processed: int = 0
    diffs_verified: int = 0
    diffs_rejected: int = 0
    diffs_needs_review: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    commits_created: int = 0
    edicts_done: int = 0
    errors: List[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    duration_seconds: float = 0


class AriadneOrchestrator:
    """
    Main orchestration loop for Ariadne.

    Coordinates the verification, conflict detection, and merge process
    for diffs submitted by Icarus workers.
    """

    def __init__(
        self,
        repo_path: Path,
        bus: Optional[AriadneBus] = None,
        on_conflict: Optional[Callable[[ConflictAnalysis], MergeStrategy]] = None,
        on_verification_complete: Optional[Callable[[Diff, VerificationResult], None]] = None,
        on_commit: Optional[Callable[[MergeResult], None]] = None,
        auto_commit: bool = False,
        autonomy: str = "hybrid",
        semantic_reviewer: Optional[SemanticReviewer] = None,
        require_approval_tags: Optional[List[str]] = None,
        tracker: Optional[Tracker] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            repo_path: Path to the git repository
            bus: AriadneBus instance (creates new if None)
            on_conflict: Callback for conflict resolution (default: escalate all)
            on_verification_complete: Callback after verification
            on_commit: Callback after successful commit
            auto_commit: Whether to automatically commit verified diffs
            autonomy: "supervised" (every diff needs a human, regardless of the
                judge's verdict), "full" (judge-gated only), or "hybrid"
                (judge-gated, plus a human is always required for diffs tagged
                with anything in require_approval_tags)
            semantic_reviewer: Checks whether a diff actually does what it
                claims to, on top of CausalSliceVerifier's mechanical checks
                (type/lint/test). Defaults to LLMJudge, which fails closed to
                NEEDS_HUMAN if the LLM backend isn't available.
            require_approval_tags: Tags (read from diff.metadata.get("tags"))
                that force human review in "hybrid" mode even if the judge
                approves -- mirrors Planner.AriadneConfig.require_approval_for.
            tracker: Optional roadmap Tracker. If given, commits/review-queue
                transitions are reflected on the feature's roadmap item
                (plan_id read from diff.metadata.get("plan_id") or
                diff.work_id), fixing the "review" status being a dead end
                that nothing ever resolved out of.
        """
        self.repo_path = Path(repo_path)
        self.bus = bus or AriadneBus()
        self.conflict_detector = ConflictDetector()
        self.verifier = CausalSliceVerifier(repo_path)
        self.autonomy = autonomy
        # Model casting (edict 0002): the judge plays the configured model, or the SDK default
        self.semantic_reviewer = semantic_reviewer or LLMJudge(model=load_config().ariadne.judge_model)
        self.require_approval_tags = require_approval_tags or [
            "breaking_change", "security", "architecture", "database",
        ]
        self.tracker = tracker

        self.on_conflict = on_conflict or self._default_conflict_handler
        self.on_verification_complete = on_verification_complete
        self.on_commit = on_commit
        self.auto_commit = auto_commit

        # State
        self._running = False
        self._stats = {
            "diffs_processed": 0,
            "conflicts_detected": 0,
            "commits_made": 0,
        }

    def _default_conflict_handler(self, analysis: ConflictAnalysis) -> MergeStrategy:
        """Default conflict handler - auto-resolve low severity, escalate others."""
        if analysis.auto_resolvable and analysis.severity == ConflictSeverity.LOW:
            return analysis.suggested_strategy
        return MergeStrategy.ESCALATE

    def _approved_intent(self, diff: Diff):
        """
        (approved intent, reason) for a diff (edict 0001, amended). Read from the stored plan or
        the edict file, never from the diff's own metadata or description: an approved plan's
        work package (plus its source and approver), or an accepted edict's Intent and Acceptance
        criteria. None, with the reason, when there is neither.
        """
        from ..edicts import dispatch_block, intent_for_diff
        from .planner import Planner

        plan_id, spec_id = diff.metadata.get("plan_id"), diff.metadata.get("spec_id")
        tagged = str(diff.metadata.get("edict") or "").zfill(4) if diff.metadata.get("edict") else None
        if not (plan_id and spec_id):
            # A tag alone is metadata; it never grants intent (0001 as amended)
            if tagged:
                return None, (f"No approved intent: the diff is tagged edict {tagged} but carries no plan "
                              "provenance (plan_id/spec_id); edict intent applies only to dispatched work.")
            return intent_for_diff(self.repo_path, diff.metadata)
        if plan_id and spec_id:
            plan = Planner(self.repo_path).load_plan(plan_id)
            if plan is None:
                return None, f"No approved intent: plan {plan_id} not found."
            spec = next((wp for wp in plan.work_packages if wp.id == spec_id), None)
            if spec is None:
                return None, f"No approved intent: package {spec_id} is not in plan {plan_id}."
            if tagged and tagged != (plan.edict or "").zfill(4):
                return None, (f"No approved intent: the diff is tagged edict {tagged} but plan {plan_id} "
                              f"comes from {('edict ' + plan.edict) if plan.edict else 'a feature request'}.")
            if plan.edict:
                block = dispatch_block(self.repo_path, plan.edict)
                if block:
                    return None, f"No approved intent: {block}."
            if not plan.approval_valid():
                if plan.edict and not plan.approved:
                    # Work dispatched from an accepted edict: the edict itself is the approval
                    return intent_for_diff(self.repo_path, {"edict": plan.edict})
                why = "is not approved" if not plan.approved else "changed after it was approved"
                return None, f"No approved intent: plan {plan_id} {why}."
            source = f"edict {plan.edict}" if plan.edict else f"feature request: {plan.feature_title}"
            return (
                f"Approved plan {plan.id} (approved by {plan.approved_by} at {plan.approved_at}; "
                f"source: {source}).\n\n{spec.package_text()}\n\n## Source\n{plan.source}",
                "",
            )
        return intent_for_diff(self.repo_path, diff.metadata)

    def _diff_intent(self, diff: Diff) -> str:
        """The approved intent for a diff, or "" when it has none. No fallback to the worker's own
        description: a worker that misunderstood its task would describe it confidently (0001)."""
        return self._approved_intent(diff)[0] or ""

    def _plan_id_for_diff(self, diff: Diff) -> str:
        """
        Roadmap plan_id a diff's tracker item lives under, if any. Falls back
        to work_id since that's the closest thing a Diff always carries;
        callers that want precise tracker linkage should set
        diff.metadata["plan_id"] explicitly when submitting the diff.
        """
        return diff.metadata.get("plan_id") or diff.work_id

    def _passes_semantic_review(
        self,
        diff: Diff,
        verification: VerificationResult,
    ) -> bool:
        """
        Run the semantic review gate for a single diff and update its status
        accordingly. Returns True if the diff may proceed to the commit batch
        this cycle.

        Never lets the judge alone move a diff to a terminal REJECTED state --
        anything other than a confident APPROVED is routed to NEEDS_REVIEW so
        a human (via the spawning agent's conversation) makes the final call,
        matching the "fail closed" principle: the judge can only unilaterally
        say yes, never unilaterally say no.
        """
        # Already resolved by a human via bus.approve_review() -- don't let
        # the judge re-litigate a human's decision on a later cycle.
        existing = diff.semantic_review or {}
        if existing.get("resolution") == "approved":
            return True

        intent, reason = self._approved_intent(diff)
        if intent is None:
            # Fail closed in every autonomy mode, without consulting the judge (edicts 0001, 0003)
            review = SemanticReviewResult(
                diff_id=diff.id, verdict=ReviewVerdict.NEEDS_HUMAN, reasoning=reason, reviewer="intent-gate",
            )
            self.bus.update_diff_status(diff.id, DiffStatus.NEEDS_REVIEW, semantic_review=review.to_dict())
            if self.tracker:
                self.tracker.complete_feature(self._plan_id_for_diff(diff))
            return False

        review = self.semantic_reviewer.review(diff, intent, verification)

        if self.autonomy == "supervised":
            self.bus.update_diff_status(
                diff.id, DiffStatus.NEEDS_REVIEW, semantic_review=review.to_dict()
            )
            if self.tracker:
                self.tracker.complete_feature(self._plan_id_for_diff(diff))
            return False

        tags = set(diff.metadata.get("tags", []))
        tag_flagged = self.autonomy == "hybrid" and tags & set(self.require_approval_tags)

        if review.verdict == ReviewVerdict.APPROVED and not tag_flagged:
            return True

        self.bus.update_diff_status(
            diff.id, DiffStatus.NEEDS_REVIEW, semantic_review=review.to_dict()
        )
        if self.tracker:
            self.tracker.complete_feature(self._plan_id_for_diff(diff))
        return False

    # ========== One-Shot Processing ==========

    def process_pending(self) -> OrchestrationResult:
        """
        Process all pending diffs once.

        Returns orchestration result with stats.
        """
        start_time = time.time()
        result = OrchestrationResult()

        if not self.bus.is_initialized():
            result.errors.append("Bus not initialized")
            result.completed_at = datetime.now(timezone.utc).isoformat()
            return result

        # Get all pending diffs
        pending = self.bus.list_pending_diffs()
        result.diffs_processed = len(pending)

        # Only early-return if there's also nothing already VERIFIED waiting
        # to be committed (e.g. a diff a human just approved out of
        # NEEDS_REVIEW) -- otherwise a cycle with zero new pending diffs
        # would never pick those up.
        if not pending and not self.bus.list_verified_diffs():
            result.completed_at = datetime.now(timezone.utc).isoformat()
            result.duration_seconds = time.time() - start_time
            return result

        # Phase 1: Verify each diff
        verified_diffs = []
        verifications_by_id: Dict[str, VerificationResult] = {}
        for diff in pending:
            verification = self._verify_diff(diff)
            verifications_by_id[diff.id] = verification

            if verification.passed:
                self.bus.update_diff_status(
                    diff.id,
                    DiffStatus.VERIFIED,
                    verification_result=verification.to_dict(),
                )
                verified_diffs.append(diff)
                result.diffs_verified += 1
            else:
                self.bus.update_diff_status(
                    diff.id,
                    DiffStatus.REJECTED,
                    verification_result=verification.to_dict(),
                    error="; ".join(verification.typecheck_errors + verification.test_errors),
                )
                result.diffs_rejected += 1

            if self.on_verification_complete:
                self.on_verification_complete(diff, verification)

        # Phase 2: Detect conflicts among verified diffs
        if len(verified_diffs) > 1:
            analyses = self.conflict_detector.analyze_all(verified_diffs)
            result.conflicts_detected = len(analyses)

            # Resolve conflicts
            for analysis in analyses:
                strategy = self.on_conflict(analysis)
                if strategy != MergeStrategy.ESCALATE:
                    self.bus.resolve_conflict(
                        analysis.conflict.id,
                        strategy,
                        f"Auto-resolved with strategy: {strategy.value}",
                    )
                    result.conflicts_resolved += 1

        # Phase 3: Semantic review gate, then merge and commit if auto_commit enabled
        #
        # Deliberately re-reads the bus's full VERIFIED set rather than just
        # this cycle's `verified_diffs` -- otherwise a diff a human approved
        # out of NEEDS_REVIEW via bus.approve_review() (which moves it back
        # to VERIFIED, not PENDING) would never get picked up again, since
        # it won't appear in list_pending_diffs() on a later cycle. Found by
        # manually smoke-testing the review -> approve -> process loop.
        commit_candidates = self.bus.list_verified_diffs()
        if self.auto_commit and commit_candidates:
            # Only proceed if no unresolved conflicts
            unresolved = self.bus.list_conflicts(resolved=False)
            if not unresolved:
                approved_for_commit = []
                for diff in commit_candidates:
                    verification = verifications_by_id.get(diff.id)
                    if self._passes_semantic_review(diff, verification):
                        approved_for_commit.append(diff)
                    else:
                        result.diffs_needs_review += 1

                if approved_for_commit:
                    merge_result = self._create_atomic_commit(approved_for_commit)
                    if merge_result.success:
                        result.commits_created += 1
                        self._mark_committed_in_tracker(approved_for_commit, merge_result)
                        result.edicts_done += self._close_finished_edicts(approved_for_commit)
                    else:
                        result.errors.append(merge_result.error or "Unknown merge error")

        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = time.time() - start_time

        return result

    def _close_finished_edicts(self, committed: List[Diff]) -> int:
        """
        Move an edict to done once its work has merged (edict 0001): every package of every plan
        built from it has a merged diff, and no diff tagged with it is still waiting. Returns how
        many edicts moved.
        """
        from ..edicts import EdictError, load_edict, mark_done
        from .planner import Planner

        planner = Planner(self.repo_path)
        all_plans = planner.list_plans()
        plan_edict = {p.id: (p.edict or "").zfill(4) for p in all_plans if p.edict}
        # The edict comes from the stored plan, not from the diff's tag
        numbers = {plan_edict[d.metadata.get("plan_id")] for d in committed if d.metadata.get("plan_id") in plan_edict}
        diffs = self.bus.list_all_diffs()
        closed = 0
        for number in sorted(numbers):
            try:
                edict = load_edict(self.repo_path, number)
            except EdictError:
                continue
            if edict.status != "accepted":
                continue
            ours = [d for d in diffs if plan_edict.get(d.metadata.get("plan_id")) == number]
            # Work still in flight blocks; a rejected attempt doesn't, if its package merged later
            if any(d.status in (DiffStatus.PENDING, DiffStatus.VERIFIED, DiffStatus.NEEDS_REVIEW) for d in ours):
                continue
            merged = {(d.metadata.get("plan_id"), d.metadata.get("spec_id")) for d in ours if d.status == DiffStatus.MERGED}
            # The plans that count: approved ones, and any plan that produced a diff (drafts don't block)
            used = {d.metadata.get("plan_id") for d in ours}
            plans = [p for p in all_plans if plan_edict.get(p.id) == number and (p.approval_valid() or p.id in used)]
            if not plans or any((p.id, wp.id) not in merged for p in plans for wp in p.work_packages):
                continue
            rel = str(edict.path.relative_to(self.repo_path))
            dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=self.repo_path,
                                   capture_output=True, text=True).stdout.strip()
            if dirty:
                # Never commit someone's uncommitted edits to the edict along with the status change
                continue
            mark_done(self.repo_path, number)
            if self.auto_commit:
                subprocess.run(_commit_args(f"Edict {number}: done (all its planned work has merged)", [rel]),
                               cwd=self.repo_path, capture_output=True, text=True)
            closed += 1
        return closed

    def _mark_committed_in_tracker(self, diffs: List[Diff], merge_result: MergeResult) -> None:
        """
        Reflect a successful commit on each diff's roadmap item: complete the
        feature (-> 'review') then immediately approve it (-> 'done'), since
        these diffs already cleared whatever review the autonomy policy
        required before reaching commit. No-op if no tracker was configured.
        """
        if not self.tracker:
            return
        commit_hash = None
        try:
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            if rev.returncode == 0:
                commit_hash = rev.stdout.strip()
        except Exception:
            pass
        for diff in diffs:
            plan_id = self._plan_id_for_diff(diff)
            self.tracker.complete_feature(plan_id, commit_hash=commit_hash)
            self.tracker.approve_review(plan_id, commit_hash=commit_hash)

    def _verify_diff(self, diff: Diff) -> VerificationResult:
        """Verify a single diff using causal slice verification."""
        # Extract causal chain if not already present
        if diff.causal_chain:
            from .diff_bus import CausalChain
            chain = CausalChain(**diff.causal_chain)
        else:
            chain = extract_causal_chain(diff, self.repo_path)

        return self.verifier.verify(diff, chain)

    def _create_atomic_commit(self, diffs: List[Diff]) -> MergeResult:
        """Create an atomic commit from verified diffs."""
        # Merge the diffs
        diff_ids = [d.id for d in diffs]
        merge_result = self.bus.merge_diffs(diff_ids)

        if not merge_result.success:
            return merge_result

        # Prepare commit directory
        commit_dir = self.bus.prepare_atomic_commit(merge_result, self.repo_path)

        # Apply the combined diff, staged, so new files are committed and nothing else is. Paths come
        # from the diff headers too, so a rename commits its old path's deletion as well as the new one.
        paths = sorted({f for d in diffs for f in d.all_affected_files()} | {
            p for d in diffs for m in re.finditer(r"^diff --git a/(.+?) b/(.+)$", d.content, re.MULTILINE)
            for p in m.groups()
        })
        try:
            diff_file = commit_dir / "combined.diff"
            result = subprocess.run(
                ["git", "apply", "--index", str(diff_file)],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                merge_result.success = False
                merge_result.error = f"Failed to apply combined diff: {result.stderr}"
                return merge_result

            # Create commit
            message_file = commit_dir / "message.md"
            message = message_file.read_text(encoding="utf-8")

            result = subprocess.run(
                _commit_args(message, paths or None),
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                # Might be nothing to commit
                if "nothing to commit" not in result.stdout + result.stderr:
                    merge_result.success = False
                    merge_result.error = f"Failed to commit: {result.stderr}"
                    return merge_result

            merge_result.verification_passed = True

            # Update diff statuses
            for diff_id in diff_ids:
                self.bus.update_diff_status(diff_id, DiffStatus.MERGED)

            # Callback
            if self.on_commit:
                self.on_commit(merge_result)

            self._stats["commits_made"] += 1

        except Exception as e:
            merge_result.success = False
            merge_result.error = str(e)

        return merge_result

    # ========== Daemon Mode ==========

    async def run_daemon(
        self,
        poll_interval: float = 5.0,
        max_idle_cycles: Optional[int] = None,
    ):
        """
        Run as a daemon, continuously processing diffs.

        Args:
            poll_interval: Seconds between checks for new diffs
            max_idle_cycles: Stop after N cycles with no work (None = run forever)
        """
        self._running = True
        idle_cycles = 0

        while self._running:
            result = self.process_pending()

            if result.diffs_processed > 0:
                idle_cycles = 0
                print(f"[Ariadne] Processed {result.diffs_processed} diffs "
                      f"({result.diffs_verified} verified, {result.diffs_rejected} rejected)")
            else:
                idle_cycles += 1

            if max_idle_cycles and idle_cycles >= max_idle_cycles:
                print(f"[Ariadne] Stopping after {idle_cycles} idle cycles")
                break

            await asyncio.sleep(poll_interval)

    def stop(self):
        """Stop the daemon loop."""
        self._running = False

    # ========== Interactive Mode ==========

    def get_pending_conflicts(self) -> List[ConflictAnalysis]:
        """Get conflicts that need Daedalus attention."""
        pending_diffs = self.bus.list_pending_diffs() + self.bus.list_verified_diffs()

        if len(pending_diffs) < 2:
            return []

        analyses = self.conflict_detector.analyze_all(pending_diffs)
        return [a for a in analyses if not a.auto_resolvable]

    def resolve_and_commit(
        self,
        conflict_resolutions: Dict[str, MergeStrategy],
    ) -> OrchestrationResult:
        """
        Apply conflict resolutions and create commit.

        Args:
            conflict_resolutions: Map of conflict_id -> resolution strategy
        """
        result = OrchestrationResult()

        # Apply resolutions
        for conflict_id, strategy in conflict_resolutions.items():
            self.bus.resolve_conflict(
                conflict_id,
                strategy,
                f"Resolved by Daedalus: {strategy.value}",
            )
            result.conflicts_resolved += 1

        # Check for remaining unresolved conflicts
        unresolved = self.bus.list_conflicts(resolved=False)
        if unresolved:
            result.errors.append(
                f"Cannot commit: {len(unresolved)} unresolved conflicts remain"
            )
            result.completed_at = datetime.now(timezone.utc).isoformat()
            return result

        # Semantic review gate, then atomic commit
        verified_diffs = self.bus.list_verified_diffs()
        if verified_diffs:
            approved_for_commit = []
            for diff in verified_diffs:
                if self._passes_semantic_review(diff, verification=None):
                    approved_for_commit.append(diff)
                else:
                    result.diffs_needs_review += 1

            if approved_for_commit:
                merge_result = self._create_atomic_commit(approved_for_commit)
                if merge_result.success:
                    result.commits_created += 1
                    self._mark_committed_in_tracker(approved_for_commit, merge_result)
                else:
                    result.errors.append(merge_result.error or "Unknown merge error")

        result.completed_at = datetime.now(timezone.utc).isoformat()
        return result

    # ========== Status ==========

    def status(self) -> Dict[str, Any]:
        """Get current orchestrator status."""
        bus_status = self.bus.status_summary() if self.bus.is_initialized() else {}
        return {
            "running": self._running,
            "repo_path": str(self.repo_path),
            "auto_commit": self.auto_commit,
            "bus": bus_status,
            "stats": self._stats,
        }


# ========== CLI Interface ==========

def main():
    """CLI for the Ariadne orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(description="Ariadne Orchestrator")
    parser.add_argument("--repo", default=".", help="Repository path")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    subparsers.add_parser("init", help="Initialize Ariadne bus")

    # status
    subparsers.add_parser("status", help="Show orchestrator status")

    # process
    process_parser = subparsers.add_parser("process", help="Process pending diffs once")
    process_parser.add_argument("--auto-commit", action="store_true",
                               help="Automatically commit verified diffs")

    # daemon
    daemon_parser = subparsers.add_parser("daemon", help="Run as daemon")
    daemon_parser.add_argument("--interval", type=float, default=5.0,
                              help="Poll interval in seconds")
    daemon_parser.add_argument("--auto-commit", action="store_true",
                              help="Automatically commit verified diffs")

    # review (semantic review gate: list/show/approve/reject diffs sitting in
    # NEEDS_REVIEW -- meant to be driven by whatever agent spawned a worker,
    # mid-conversation, after it has shown the diff + its own take to a human)
    review_parser = subparsers.add_parser("review", help="Manage diffs pending semantic review")
    review_sub = review_parser.add_subparsers(dest="review_command", help="Review commands")

    review_list = review_sub.add_parser("list", help="List diffs needing review")
    review_list.add_argument("--json", action="store_true", help="Output as JSON")

    review_show = review_sub.add_parser("show", help="Show a diff pending review")
    review_show.add_argument("diff_id")
    review_show.add_argument("--json", action="store_true", help="Output as JSON")

    review_approve = review_sub.add_parser("approve", help="Approve a diff pending review")
    review_approve.add_argument("diff_id")
    review_approve.add_argument("--by", default="human", help="Who approved it")

    review_reject = review_sub.add_parser("reject", help="Reject a diff pending review")
    review_reject.add_argument("diff_id")
    review_reject.add_argument("--reason", required=True, help="Why it was rejected")
    review_reject.add_argument("--by", default="human", help="Who rejected it")

    # plans: approving a plan is an intent-approval event (edict 0001, amended)
    plans_parser = subparsers.add_parser("plans", help="List and approve implementation plans")
    plans_sub = plans_parser.add_subparsers(dest="plans_command", help="Plan commands")
    plans_sub.add_parser("list", help="List plans and whether their approval is valid")
    plans_approve = plans_sub.add_parser("approve", help="Approve a plan: its packages become approved intent")
    plans_approve.add_argument("plan_id")
    plans_approve.add_argument("--by", required=True,
                               help="Who approved it: the person, or the main Claude Code session")

    args = parser.parse_args()
    repo_path = Path(args.repo).resolve()

    if args.command == "init":
        bus = AriadneBus()
        bus.initialize()
        print(f"Ariadne bus initialized at {bus.root}")

    elif args.command == "status":
        orchestrator = AriadneOrchestrator(repo_path)
        status = orchestrator.status()
        print(json.dumps(status, indent=2))

    elif args.command == "process":
        orchestrator = AriadneOrchestrator(
            repo_path,
            auto_commit=args.auto_commit,
        )
        result = orchestrator.process_pending()
        print(json.dumps(asdict(result), indent=2))

    elif args.command == "daemon":
        orchestrator = AriadneOrchestrator(
            repo_path,
            auto_commit=args.auto_commit,
        )
        print(f"Starting Ariadne daemon (interval: {args.interval}s)")
        asyncio.run(orchestrator.run_daemon(poll_interval=args.interval))

    elif args.command == "review":
        bus = AriadneBus()
        tracker = Tracker()

        if args.review_command == "list":
            pending = bus.list_needs_review_diffs()
            if args.json:
                print(json.dumps([asdict(d) for d in pending], indent=2, default=str))
            elif not pending:
                print("No diffs pending review.")
            else:
                for d in pending:
                    verdict = (d.semantic_review or {}).get("verdict", "unknown")
                    print(f"{d.id}  [{verdict}]  {d.work_id}: {d.description}")

        elif args.review_command == "show":
            diff = bus.get_diff(args.diff_id)
            if not diff:
                print(f"No such diff: {args.diff_id}")
                return
            if args.json:
                print(json.dumps(asdict(diff), indent=2, default=str))
            else:
                print(f"diff {diff.id} ({diff.work_id})")
                print(f"description: {diff.description}")
                print(f"worker model: {diff.metadata.get('worker_model') or '(SDK default)'}")
                if diff.semantic_review:
                    review = diff.semantic_review
                    print(f"judge verdict: {review.get('verdict')}")
                    print(f"judged by: {review.get('reviewer')}, model {review.get('model') or '(SDK default)'}")
                    print(f"judge reasoning: {review.get('reasoning')}")
                print("---")
                print(diff.content)

        elif args.review_command == "approve":
            diff = bus.get_diff(args.diff_id)
            if not diff:
                print(f"No such diff: {args.diff_id}")
                return
            if not bus.approve_review(args.diff_id, approved_by=args.by):
                print(f"Could not approve {args.diff_id} (not pending review?)")
                return
            plan_id = diff.metadata.get("plan_id") or diff.work_id
            tracker.approve_review(plan_id)
            print(f"Approved {args.diff_id}; it will be committed on the next process cycle.")

        elif args.review_command == "reject":
            diff = bus.get_diff(args.diff_id)
            if not diff:
                print(f"No such diff: {args.diff_id}")
                return
            if not bus.reject_review(args.diff_id, args.reason, rejected_by=args.by):
                print(f"Could not reject {args.diff_id} (not pending review?)")
                return
            plan_id = diff.metadata.get("plan_id") or diff.work_id
            tracker.reject_review(plan_id, args.reason)
            print(f"Rejected {args.diff_id}: {args.reason}")

        else:
            review_parser.print_help()

    elif args.command == "plans":
        from .planner import Planner

        planner = Planner(repo_path)
        if args.plans_command == "list":
            for plan in planner.list_plans():
                state = ("approved by " + str(plan.approved_by)) if plan.approval_valid() else \
                    ("approval void: changed since" if plan.approved else "not approved")
                source = f"edict {plan.edict}" if plan.edict else "feature request"
                print(f"{plan.id}  {len(plan.work_packages)} packages  {source}  {state}")
        elif args.plans_command == "approve":
            if planner.load_plan(args.plan_id) is None:
                print(f"No such plan: {args.plan_id}")
                return
            if planner.load_plan(args.plan_id).edict:
                from ..edicts import dispatch_block

                block = dispatch_block(repo_path, planner.load_plan(args.plan_id).edict)
                if block:
                    print(f"Not approved: {block}")
                    return
            plan = planner.approve_plan(args.plan_id, approved_by=args.by)
            print(f"Approved {plan.id} ({len(plan.work_packages)} packages) by {plan.approved_by}")
        else:
            plans_parser.print_help()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

