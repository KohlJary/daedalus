"""
Conflict Detector

Sophisticated conflict detection beyond simple file/line overlap.
Integrates with the Palace/Labyrinth for semantic conflict detection.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Set, Tuple
import re

from .diff_bus import (
    Diff,
    CausalChain,
    Conflict,
    ConflictType,
    MergeStrategy,
)


class ConflictSeverity(str, Enum):
    """Severity levels for conflicts."""
    LOW = "low"           # File overlap but different sections
    MEDIUM = "medium"     # Same file, nearby lines
    HIGH = "high"         # Same lines modified
    CRITICAL = "critical" # Semantic conflict or delete/modify


@dataclass
class ConflictAnalysis:
    """Detailed analysis of a conflict."""
    conflict: Conflict
    severity: ConflictSeverity
    auto_resolvable: bool
    suggested_strategy: MergeStrategy
    resolution_steps: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)


class ConflictDetector:
    """
    Analyzes diffs for conflicts with varying levels of sophistication.

    Levels:
    1. File-level: Do diffs touch the same files?
    2. Line-level: Do diffs modify overlapping line ranges?
    3. Semantic-level: Do diffs affect the same logical units? (requires Palace)
    4. Causal-level: Do diffs affect the same causal chains? (requires pathfinding)
    """

    def __init__(self, palace_path: Optional[Path] = None):
        """
        Initialize detector.

        Args:
            palace_path: Path to .daedalus/labyrinth/ for semantic analysis
        """
        self.palace_path = palace_path

    def analyze_pair(self, diff_a: Diff, diff_b: Diff) -> Optional[ConflictAnalysis]:
        """
        Analyze two diffs for conflicts.

        Returns None if no conflict, otherwise returns detailed analysis.
        """
        # Level 1: File overlap
        files_a = diff_a.all_affected_files()
        files_b = diff_b.all_affected_files()
        overlapping_files = files_a & files_b

        if not overlapping_files:
            return None

        # Check for delete/modify conflicts (critical)
        delete_modify = self._check_delete_modify(diff_a, diff_b, overlapping_files)
        if delete_modify:
            return delete_modify

        # Level 2: Line overlap
        line_conflicts = self._check_line_overlap(diff_a, diff_b, overlapping_files)

        # Determine severity and strategy
        if line_conflicts:
            severity = ConflictSeverity.HIGH
            auto_resolvable = False
            strategy = MergeStrategy.ESCALATE
            risk_factors = [
                f"Same lines modified in: {', '.join(line_conflicts.keys())}",
                "Manual review required to determine correct merge order",
            ]
        else:
            severity = ConflictSeverity.LOW
            auto_resolvable = True
            strategy = MergeStrategy.SEQUENTIAL
            risk_factors = [
                f"Same files but different sections: {', '.join(overlapping_files)}",
            ]

        conflict = Conflict(
            id=f"conflict-{diff_a.id[:6]}-{diff_b.id[:6]}",
            diff_a_id=diff_a.id,
            diff_b_id=diff_b.id,
            conflict_type=ConflictType.LINE_OVERLAP if line_conflicts else ConflictType.FILE_OVERLAP,
            affected_files=list(overlapping_files),
            affected_lines=line_conflicts,
            description=self._generate_description(diff_a, diff_b, overlapping_files, line_conflicts),
            suggested_strategy=strategy,
        )

        return ConflictAnalysis(
            conflict=conflict,
            severity=severity,
            auto_resolvable=auto_resolvable,
            suggested_strategy=strategy,
            resolution_steps=self._generate_resolution_steps(strategy, diff_a, diff_b),
            risk_factors=risk_factors,
        )

    def analyze_all(self, diffs: List[Diff]) -> List[ConflictAnalysis]:
        """Analyze all diffs for conflicts."""
        analyses = []

        for i, diff_a in enumerate(diffs):
            for diff_b in diffs[i+1:]:
                analysis = self.analyze_pair(diff_a, diff_b)
                if analysis:
                    analyses.append(analysis)

        # Sort by severity (critical first)
        severity_order = {
            ConflictSeverity.CRITICAL: 0,
            ConflictSeverity.HIGH: 1,
            ConflictSeverity.MEDIUM: 2,
            ConflictSeverity.LOW: 3,
        }
        analyses.sort(key=lambda a: severity_order[a.severity])

        return analyses

    def _check_delete_modify(
        self,
        diff_a: Diff,
        diff_b: Diff,
        overlapping_files: Set[str],
    ) -> Optional[ConflictAnalysis]:
        """Check for delete/modify conflicts (one deletes, other modifies)."""
        for filepath in overlapping_files:
            a_deletes = filepath in diff_a.files_deleted
            b_deletes = filepath in diff_b.files_deleted
            a_modifies = filepath in diff_a.files_modified
            b_modifies = filepath in diff_b.files_modified

            if (a_deletes and b_modifies) or (b_deletes and a_modifies):
                conflict = Conflict(
                    id=f"conflict-{diff_a.id[:6]}-{diff_b.id[:6]}",
                    diff_a_id=diff_a.id,
                    diff_b_id=diff_b.id,
                    conflict_type=ConflictType.SEMANTIC,
                    affected_files=[filepath],
                    description=f"Delete/modify conflict: one diff deletes {filepath}, other modifies it",
                    suggested_strategy=MergeStrategy.ESCALATE,
                )

                return ConflictAnalysis(
                    conflict=conflict,
                    severity=ConflictSeverity.CRITICAL,
                    auto_resolvable=False,
                    suggested_strategy=MergeStrategy.ESCALATE,
                    resolution_steps=[
                        "Determine if file should be deleted or kept",
                        "If kept, merge the modification",
                        "If deleted, discard the modification",
                    ],
                    risk_factors=[
                        "One worker deleted a file another modified",
                        "Cannot auto-resolve - requires human decision",
                    ],
                )

        return None

    def _check_line_overlap(
        self,
        diff_a: Diff,
        diff_b: Diff,
        overlapping_files: Set[str],
    ) -> Dict[str, List[Tuple[int, int]]]:
        """Check for overlapping line ranges."""
        overlapping_lines = {}

        for filepath in overlapping_files:
            lines_a = diff_a.line_changes.get(filepath, [])
            lines_b = diff_b.line_changes.get(filepath, [])

            for start_a, end_a, _ in lines_a:
                for start_b, end_b, _ in lines_b:
                    # Check if ranges overlap (with some buffer for context)
                    buffer = 3  # Lines of context
                    if not (end_a + buffer < start_b or end_b + buffer < start_a):
                        if filepath not in overlapping_lines:
                            overlapping_lines[filepath] = []
                        overlapping_lines[filepath].append((
                            max(start_a, start_b),
                            min(end_a, end_b)
                        ))

        return overlapping_lines

    def _generate_description(
        self,
        diff_a: Diff,
        diff_b: Diff,
        overlapping_files: Set[str],
        line_conflicts: Dict[str, List[Tuple[int, int]]],
    ) -> str:
        """Generate human-readable conflict description."""
        parts = [
            f"Conflict between {diff_a.work_id} and {diff_b.work_id}",
            f"Files affected: {', '.join(overlapping_files)}",
        ]

        if line_conflicts:
            parts.append("Line-level conflicts:")
            for filepath, ranges in line_conflicts.items():
                range_strs = [f"{s}-{e}" for s, e in ranges]
                parts.append(f"  {filepath}: lines {', '.join(range_strs)}")

        return "\n".join(parts)

    def _generate_resolution_steps(
        self,
        strategy: MergeStrategy,
        diff_a: Diff,
        diff_b: Diff,
    ) -> List[str]:
        """Generate resolution steps based on strategy."""
        if strategy == MergeStrategy.SEQUENTIAL:
            return [
                f"Apply {diff_a.id} first (submitted: {diff_a.submitted_at})",
                f"Then apply {diff_b.id}",
                "Run verification on combined result",
            ]
        elif strategy == MergeStrategy.INTERLEAVE:
            return [
                "Use git merge-file to combine changes",
                "Review merge result for correctness",
                "Run verification on merged result",
            ]
        elif strategy == MergeStrategy.ESCALATE:
            return [
                "Present conflict to Daedalus for review",
                "Show both diffs side-by-side",
                "Wait for resolution decision",
                "Apply chosen resolution",
            ]
        else:  # REJECT
            return [
                f"Reject {diff_b.id} (later submission)",
                f"Keep {diff_a.id}",
                "Notify worker of rejection with reason",
                "Worker can re-submit after rebasing",
            ]


def check_causal_conflict(
    chain_a: CausalChain,
    chain_b: CausalChain,
) -> Optional[Dict]:
    """
    Check if two causal chains conflict.

    Returns conflict details if they overlap, None otherwise.
    """
    if not chain_a.overlaps_with(chain_b):
        return None

    overlap = chain_a.get_overlap(chain_b)

    return {
        "type": "causal",
        "overlap": overlap,
        "risk": "Changes affect same code paths - verification must run both",
    }
