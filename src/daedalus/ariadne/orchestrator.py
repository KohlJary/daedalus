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


@dataclass
class OrchestrationResult:
    """Result of an orchestration cycle."""
    diffs_processed: int = 0
    diffs_verified: int = 0
    diffs_rejected: int = 0
    conflicts_detected: int = 0
    conflicts_resolved: int = 0
    commits_created: int = 0
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
        """
        self.repo_path = Path(repo_path)
        self.bus = bus or AriadneBus()
        self.conflict_detector = ConflictDetector()
        self.verifier = CausalSliceVerifier(repo_path)

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

        if not pending:
            result.completed_at = datetime.now(timezone.utc).isoformat()
            result.duration_seconds = time.time() - start_time
            return result

        # Phase 1: Verify each diff
        verified_diffs = []
        for diff in pending:
            verification = self._verify_diff(diff)

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

        # Phase 3: Merge and commit if auto_commit enabled
        if self.auto_commit and verified_diffs:
            # Only merge if no unresolved conflicts
            unresolved = self.bus.list_conflicts(resolved=False)
            if not unresolved:
                merge_result = self._create_atomic_commit(verified_diffs)
                if merge_result.success:
                    result.commits_created += 1
                else:
                    result.errors.append(merge_result.error or "Unknown merge error")

        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_seconds = time.time() - start_time

        return result

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

        # Apply the combined diff
        try:
            diff_file = commit_dir / "combined.diff"
            result = subprocess.run(
                ["git", "apply", str(diff_file)],
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
            message = message_file.read_text()

            result = subprocess.run(
                ["git", "commit", "-a", "--author=Daedalus <daedalus@localhost>", "-m", message],
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

        # Create atomic commit
        verified_diffs = self.bus.list_verified_diffs()
        if verified_diffs:
            merge_result = self._create_atomic_commit(verified_diffs)
            if merge_result.success:
                result.commits_created += 1
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

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
