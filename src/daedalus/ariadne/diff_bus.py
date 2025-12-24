#!/usr/bin/env python3
"""
Ariadne Diff Bus

File-based coordination system for diff collection and conflict detection.
Workers submit diffs instead of committing directly; Ariadne orchestrates
the merge and verification process.

Directory structure:
    /tmp/ariadne-bus/
        diffs/
            pending/          # Diffs awaiting verification
                {work_id}.json
            verified/         # Passed causal slice check
                {work_id}.json
            rejected/         # Failed verification
                {work_id}.json
        conflicts/            # Detected conflicts
            {conflict_id}.json
        merges/               # Merge resolutions
            {merge_id}.json
        commits/              # Ready for atomic commit
            {commit_id}/
                combined.diff
                message.md
                verification.json
"""

import json
import os
import fcntl
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Set, Tuple


# Base directory for the bus
BUS_ROOT = Path("/tmp/ariadne-bus")


class DiffStatus(str, Enum):
    """Status of a submitted diff."""
    PENDING = "pending"          # Awaiting verification
    VERIFYING = "verifying"      # Currently being verified
    VERIFIED = "verified"        # Passed causal slice check
    REJECTED = "rejected"        # Failed verification
    CONFLICTED = "conflicted"    # Has conflicts with other diffs
    MERGED = "merged"            # Successfully merged into atomic commit


class ConflictType(str, Enum):
    """Types of conflicts between diffs."""
    FILE_OVERLAP = "file_overlap"      # Same file modified
    LINE_OVERLAP = "line_overlap"      # Same lines modified
    SEMANTIC = "semantic"              # Logical conflict (detected by tests)
    CAUSAL = "causal"                  # Affects same causal chain


class MergeStrategy(str, Enum):
    """Strategies for resolving conflicts."""
    SEQUENTIAL = "sequential"    # Apply A then B
    INTERLEAVE = "interleave"   # Merge hunks (git merge style)
    ESCALATE = "escalate"       # Need Daedalus decision
    REJECT = "reject"           # Cannot merge, reject later diff


@dataclass
class CausalChain:
    """
    Represents the causal chain of a diff - what functions/modules are affected.

    This is the key to fast verification: instead of running the full test suite,
    we only verify the affected code paths.
    """
    diff_id: str
    affected_files: List[str] = field(default_factory=list)
    affected_functions: List[str] = field(default_factory=list)  # module:function format
    affected_modules: List[str] = field(default_factory=list)
    call_depth: int = 0  # How deep the causal chain goes
    test_files: List[str] = field(default_factory=list)  # Tests that should run
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def overlaps_with(self, other: "CausalChain") -> bool:
        """Check if two causal chains have overlapping paths."""
        return bool(
            set(self.affected_files) & set(other.affected_files) or
            set(self.affected_functions) & set(other.affected_functions) or
            set(self.affected_modules) & set(other.affected_modules)
        )

    def get_overlap(self, other: "CausalChain") -> Dict[str, List[str]]:
        """Get the overlapping elements between two chains."""
        return {
            "files": list(set(self.affected_files) & set(other.affected_files)),
            "functions": list(set(self.affected_functions) & set(other.affected_functions)),
            "modules": list(set(self.affected_modules) & set(other.affected_modules)),
        }


@dataclass
class Diff:
    """
    A diff submitted by an Icarus worker.

    Contains the raw diff content plus metadata about its causal chain
    and verification status.
    """
    id: str
    work_id: str                          # Original work package ID
    instance_id: str                      # Icarus instance that produced it
    content: str                          # Raw diff content (git diff output)
    description: str                      # What this diff does
    status: DiffStatus = DiffStatus.PENDING

    # Files affected (extracted from diff)
    files_added: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    files_deleted: List[str] = field(default_factory=list)

    # Line-level changes for conflict detection
    # Format: {filepath: [(start_line, end_line, change_type), ...]}
    line_changes: Dict[str, List[Tuple[int, int, str]]] = field(default_factory=dict)

    # Causal chain (populated by pathfinding analysis)
    causal_chain: Optional[Dict] = None

    # Verification results
    verification_result: Optional[Dict] = None
    verification_error: Optional[str] = None

    # Timestamps
    submitted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verified_at: Optional[str] = None
    merged_at: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_git_diff(
        cls,
        work_id: str,
        instance_id: str,
        diff_content: str,
        description: str,
    ) -> "Diff":
        """Create a Diff from git diff output."""
        diff_id = f"diff-{hashlib.sha256(diff_content.encode()).hexdigest()[:12]}"

        # Parse diff to extract file changes
        files_added = []
        files_modified = []
        files_deleted = []
        line_changes = {}

        current_file = None
        current_lines = []

        for line in diff_content.split("\n"):
            if line.startswith("diff --git"):
                # Save previous file's changes
                if current_file and current_lines:
                    line_changes[current_file] = current_lines

                # Extract filename
                parts = line.split(" b/")
                if len(parts) >= 2:
                    current_file = parts[1]
                    current_lines = []

            elif line.startswith("new file"):
                if current_file:
                    files_added.append(current_file)

            elif line.startswith("deleted file"):
                if current_file:
                    files_deleted.append(current_file)

            elif line.startswith("@@"):
                # Parse hunk header: @@ -start,count +start,count @@
                import re
                match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if match and current_file:
                    old_start = int(match.group(1))
                    old_count = int(match.group(2) or 1)
                    new_start = int(match.group(3))
                    new_count = int(match.group(4) or 1)
                    current_lines.append((new_start, new_start + new_count, "modify"))

            elif current_file and current_file not in files_added and current_file not in files_deleted:
                if current_file not in files_modified:
                    files_modified.append(current_file)

        # Save last file's changes
        if current_file and current_lines:
            line_changes[current_file] = current_lines

        return cls(
            id=diff_id,
            work_id=work_id,
            instance_id=instance_id,
            content=diff_content,
            description=description,
            files_added=files_added,
            files_modified=files_modified,
            files_deleted=files_deleted,
            line_changes=line_changes,
        )

    def all_affected_files(self) -> Set[str]:
        """Get all files affected by this diff."""
        return set(self.files_added + self.files_modified + self.files_deleted)


@dataclass
class Conflict:
    """Represents a conflict between two diffs."""
    id: str
    diff_a_id: str
    diff_b_id: str
    conflict_type: ConflictType
    affected_files: List[str]
    affected_lines: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)
    description: str = ""
    suggested_strategy: MergeStrategy = MergeStrategy.ESCALATE
    resolved: bool = False
    resolution: Optional[str] = None
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None


@dataclass
class MergeResult:
    """Result of merging multiple diffs."""
    id: str
    diff_ids: List[str]
    combined_diff: str
    commit_message: str
    success: bool
    error: Optional[str] = None
    conflicts_resolved: List[str] = field(default_factory=list)
    verification_passed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AriadneBus:
    """
    Coordination bus for diff collection and conflict resolution.

    Usage (Worker side - in harness):
        bus = AriadneBus()

        # Generate diff instead of committing
        diff_content = subprocess.run(["git", "diff"], capture_output=True).stdout
        diff = Diff.from_git_diff(work_id, instance_id, diff_content, "Description")

        # Extract causal chain (requires pathfinding integration)
        causal_chain = extract_causal_chain(diff)
        diff.causal_chain = asdict(causal_chain)

        # Submit to Ariadne
        bus.submit_diff(diff)

    Usage (Ariadne orchestrator side):
        bus = AriadneBus()

        # Check for pending diffs
        pending = bus.list_pending_diffs()

        # Detect conflicts
        conflicts = bus.detect_conflicts(pending)

        # After verification and conflict resolution
        result = bus.merge_diffs(verified_diff_ids)

        # If successful, commit
        if result.success and result.verification_passed:
            bus.atomic_commit(result)
    """

    def __init__(self, root: Path = BUS_ROOT):
        self.root = root
        self.dirs = {
            "pending": root / "diffs" / "pending",
            "verified": root / "diffs" / "verified",
            "rejected": root / "diffs" / "rejected",
            "conflicts": root / "conflicts",
            "merges": root / "merges",
            "commits": root / "commits",
        }

    def initialize(self) -> None:
        """Create bus directory structure."""
        for dir_path in self.dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)

        # Create manifest
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
            "orchestrator_pid": os.getpid(),
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2))

    def is_initialized(self) -> bool:
        """Check if bus is initialized."""
        return (self.root / "manifest.json").exists()

    # ========== Diff Submission ==========

    def submit_diff(self, diff: Diff) -> str:
        """
        Submit a diff from a worker.

        Returns the diff ID.
        """
        diff_file = self.dirs["pending"] / f"{diff.id}.json"

        # Convert to dict, handling CausalChain if present
        diff_dict = asdict(diff)

        diff_file.write_text(json.dumps(diff_dict, indent=2, default=str))
        return diff.id

    def get_diff(self, diff_id: str) -> Optional[Diff]:
        """Get a diff by ID, checking all directories."""
        for dir_name in ["pending", "verified", "rejected"]:
            diff_file = self.dirs[dir_name] / f"{diff_id}.json"
            if diff_file.exists():
                data = json.loads(diff_file.read_text())
                data["status"] = DiffStatus(data["status"])
                return Diff(**data)
        return None

    def list_pending_diffs(self) -> List[Diff]:
        """List all pending diffs."""
        diffs = []
        for f in self.dirs["pending"].glob("*.json"):
            data = json.loads(f.read_text())
            data["status"] = DiffStatus(data["status"])
            diffs.append(Diff(**data))
        return sorted(diffs, key=lambda d: d.submitted_at)

    def list_verified_diffs(self) -> List[Diff]:
        """List all verified diffs ready for merge."""
        diffs = []
        for f in self.dirs["verified"].glob("*.json"):
            data = json.loads(f.read_text())
            data["status"] = DiffStatus(data["status"])
            diffs.append(Diff(**data))
        return sorted(diffs, key=lambda d: d.verified_at or d.submitted_at)

    def update_diff_status(
        self,
        diff_id: str,
        new_status: DiffStatus,
        verification_result: Optional[Dict] = None,
        error: Optional[str] = None,
    ) -> bool:
        """
        Update a diff's status, moving it to the appropriate directory.

        Returns True if successful.
        """
        diff = self.get_diff(diff_id)
        if not diff:
            return False

        # Remove from current location
        for dir_name in ["pending", "verified", "rejected"]:
            old_file = self.dirs[dir_name] / f"{diff_id}.json"
            if old_file.exists():
                old_file.unlink()
                break

        # Update status
        diff.status = new_status
        if verification_result:
            diff.verification_result = verification_result
        if error:
            diff.verification_error = error
        if new_status == DiffStatus.VERIFIED:
            diff.verified_at = datetime.now(timezone.utc).isoformat()

        # Write to new location
        if new_status in [DiffStatus.PENDING, DiffStatus.VERIFYING]:
            target_dir = self.dirs["pending"]
        elif new_status == DiffStatus.VERIFIED:
            target_dir = self.dirs["verified"]
        else:
            target_dir = self.dirs["rejected"]

        diff_dict = asdict(diff)
        (target_dir / f"{diff_id}.json").write_text(
            json.dumps(diff_dict, indent=2, default=str)
        )
        return True

    # ========== Conflict Detection ==========

    def detect_conflicts(self, diffs: Optional[List[Diff]] = None) -> List[Conflict]:
        """
        Detect conflicts between diffs.

        If diffs is None, checks all pending + verified diffs.
        """
        if diffs is None:
            diffs = self.list_pending_diffs() + self.list_verified_diffs()

        conflicts = []

        for i, diff_a in enumerate(diffs):
            for diff_b in diffs[i+1:]:
                conflict = self._check_conflict(diff_a, diff_b)
                if conflict:
                    conflicts.append(conflict)
                    self._save_conflict(conflict)

        return conflicts

    def _check_conflict(self, diff_a: Diff, diff_b: Diff) -> Optional[Conflict]:
        """Check if two diffs conflict."""
        files_a = diff_a.all_affected_files()
        files_b = diff_b.all_affected_files()

        # File-level overlap
        overlapping_files = files_a & files_b
        if not overlapping_files:
            return None

        # Line-level overlap check
        overlapping_lines = {}
        for filepath in overlapping_files:
            lines_a = diff_a.line_changes.get(filepath, [])
            lines_b = diff_b.line_changes.get(filepath, [])

            for start_a, end_a, _ in lines_a:
                for start_b, end_b, _ in lines_b:
                    # Check if ranges overlap
                    if not (end_a < start_b or end_b < start_a):
                        if filepath not in overlapping_lines:
                            overlapping_lines[filepath] = []
                        overlapping_lines[filepath].append((
                            max(start_a, start_b),
                            min(end_a, end_b)
                        ))

        if overlapping_lines:
            conflict_type = ConflictType.LINE_OVERLAP
            suggested_strategy = MergeStrategy.ESCALATE
        else:
            conflict_type = ConflictType.FILE_OVERLAP
            suggested_strategy = MergeStrategy.SEQUENTIAL

        conflict_id = f"conflict-{diff_a.id[:6]}-{diff_b.id[:6]}"

        return Conflict(
            id=conflict_id,
            diff_a_id=diff_a.id,
            diff_b_id=diff_b.id,
            conflict_type=conflict_type,
            affected_files=list(overlapping_files),
            affected_lines=overlapping_lines,
            description=f"Diffs {diff_a.id} and {diff_b.id} both modify: {', '.join(overlapping_files)}",
            suggested_strategy=suggested_strategy,
        )

    def _save_conflict(self, conflict: Conflict) -> None:
        """Save a conflict to the conflicts directory."""
        conflict_file = self.dirs["conflicts"] / f"{conflict.id}.json"
        conflict_dict = asdict(conflict)
        conflict_dict["conflict_type"] = conflict.conflict_type.value
        conflict_dict["suggested_strategy"] = conflict.suggested_strategy.value
        conflict_file.write_text(json.dumps(conflict_dict, indent=2))

    def list_conflicts(self, resolved: Optional[bool] = None) -> List[Conflict]:
        """List conflicts, optionally filtered by resolved status."""
        conflicts = []
        for f in self.dirs["conflicts"].glob("*.json"):
            data = json.loads(f.read_text())
            data["conflict_type"] = ConflictType(data["conflict_type"])
            data["suggested_strategy"] = MergeStrategy(data["suggested_strategy"])
            conflict = Conflict(**data)

            if resolved is None or conflict.resolved == resolved:
                conflicts.append(conflict)

        return sorted(conflicts, key=lambda c: c.detected_at)

    def resolve_conflict(
        self,
        conflict_id: str,
        strategy: MergeStrategy,
        resolution: str,
    ) -> bool:
        """Mark a conflict as resolved."""
        conflict_file = self.dirs["conflicts"] / f"{conflict_id}.json"
        if not conflict_file.exists():
            return False

        data = json.loads(conflict_file.read_text())
        data["resolved"] = True
        data["resolution"] = resolution
        data["suggested_strategy"] = strategy.value
        data["resolved_at"] = datetime.now(timezone.utc).isoformat()

        conflict_file.write_text(json.dumps(data, indent=2))
        return True

    # ========== Merge Operations ==========

    def merge_diffs(
        self,
        diff_ids: List[str],
        commit_message: Optional[str] = None,
    ) -> MergeResult:
        """
        Combine multiple verified diffs into a single merge result.

        This does NOT apply the merge to the repo - it prepares the combined
        diff for verification and eventual atomic commit.
        """
        import hashlib

        merge_id = f"merge-{hashlib.sha256('-'.join(diff_ids).encode()).hexdigest()[:8]}"

        diffs = []
        for diff_id in diff_ids:
            diff = self.get_diff(diff_id)
            if not diff:
                return MergeResult(
                    id=merge_id,
                    diff_ids=diff_ids,
                    combined_diff="",
                    commit_message="",
                    success=False,
                    error=f"Diff not found: {diff_id}",
                )
            diffs.append(diff)

        # Combine diff contents
        # In a real implementation, we'd use git's merge machinery
        # For now, simple concatenation (works for non-overlapping changes)
        combined = "\n".join(d.content for d in diffs)

        # Generate commit message
        if not commit_message:
            descriptions = [d.description for d in diffs]
            commit_message = "Merged work from parallel workers:\n\n" + "\n".join(
                f"- {desc}" for desc in descriptions
            )

        result = MergeResult(
            id=merge_id,
            diff_ids=diff_ids,
            combined_diff=combined,
            commit_message=commit_message,
            success=True,
        )

        # Save merge result
        merge_file = self.dirs["merges"] / f"{merge_id}.json"
        merge_file.write_text(json.dumps(asdict(result), indent=2))

        return result

    def get_merge_result(self, merge_id: str) -> Optional[MergeResult]:
        """Get a merge result by ID."""
        merge_file = self.dirs["merges"] / f"{merge_id}.json"
        if merge_file.exists():
            data = json.loads(merge_file.read_text())
            return MergeResult(**data)
        return None

    # ========== Atomic Commit ==========

    def prepare_atomic_commit(
        self,
        merge_result: MergeResult,
        repo_path: Path,
    ) -> Path:
        """
        Prepare an atomic commit from a merge result.

        Creates a commit directory with all necessary files.
        Returns the path to the commit directory.
        """
        commit_dir = self.dirs["commits"] / merge_result.id
        commit_dir.mkdir(parents=True, exist_ok=True)

        # Write combined diff
        (commit_dir / "combined.diff").write_text(merge_result.combined_diff)

        # Write commit message
        full_message = f"{merge_result.commit_message}\n\nMerged diffs:\n"
        for diff_id in merge_result.diff_ids:
            full_message += f"  - {diff_id}\n"
        (commit_dir / "message.md").write_text(full_message)

        # Write verification info
        verification = {
            "merge_id": merge_result.id,
            "diff_count": len(merge_result.diff_ids),
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "repo_path": str(repo_path),
            "verification_passed": merge_result.verification_passed,
        }
        (commit_dir / "verification.json").write_text(json.dumps(verification, indent=2))

        return commit_dir

    # ========== Status Summary ==========

    def status_summary(self) -> Dict[str, Any]:
        """Get overall bus status."""
        return {
            "initialized": self.is_initialized(),
            "diffs": {
                "pending": len(list(self.dirs["pending"].glob("*.json"))),
                "verified": len(list(self.dirs["verified"].glob("*.json"))),
                "rejected": len(list(self.dirs["rejected"].glob("*.json"))),
            },
            "conflicts": {
                "total": len(list(self.dirs["conflicts"].glob("*.json"))),
                "unresolved": len(self.list_conflicts(resolved=False)),
            },
            "merges": len(list(self.dirs["merges"].glob("*.json"))),
            "commits_ready": len(list(self.dirs["commits"].iterdir())) if self.dirs["commits"].exists() else 0,
        }

    # ========== Cleanup ==========

    def reset(self) -> None:
        """Clear all bus data. Use with caution."""
        import shutil
        if self.root.exists():
            shutil.rmtree(self.root)
        self.initialize()


# ========== CLI Interface ==========

def main():
    """CLI for interacting with the Ariadne bus."""
    import argparse

    parser = argparse.ArgumentParser(description="Ariadne Diff Bus")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    subparsers.add_parser("init", help="Initialize the bus")

    # status
    subparsers.add_parser("status", help="Show bus status")

    # diffs
    diff_parser = subparsers.add_parser("diffs", help="Diff management")
    diff_parser.add_argument("action", choices=["pending", "verified", "rejected"])

    # conflicts
    subparsers.add_parser("conflicts", help="List conflicts")

    # reset
    subparsers.add_parser("reset", help="Reset bus (clears all data)")

    args = parser.parse_args()
    bus = AriadneBus()

    if args.command == "init":
        bus.initialize()
        print(f"Ariadne bus initialized at {bus.root}")

    elif args.command == "status":
        if not bus.is_initialized():
            print("Bus not initialized. Run: ariadne init")
            return
        summary = bus.status_summary()
        print(json.dumps(summary, indent=2))

    elif args.command == "diffs":
        if args.action == "pending":
            for d in bus.list_pending_diffs():
                print(f"{d.id}: {d.description[:50]} ({len(d.all_affected_files())} files)")
        elif args.action == "verified":
            for d in bus.list_verified_diffs():
                print(f"{d.id}: {d.description[:50]} (verified: {d.verified_at})")
        elif args.action == "rejected":
            for f in bus.dirs["rejected"].glob("*.json"):
                data = json.loads(f.read_text())
                print(f"{data['id']}: {data.get('verification_error', 'unknown error')}")

    elif args.command == "conflicts":
        for c in bus.list_conflicts():
            status = "RESOLVED" if c.resolved else "UNRESOLVED"
            print(f"[{status}] {c.id}: {c.description}")

    elif args.command == "reset":
        confirm = input("This will clear all Ariadne bus data. Continue? [y/N] ")
        if confirm.lower() == "y":
            bus.reset()
            print("Bus reset.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
