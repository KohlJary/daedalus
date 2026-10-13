"""Tests for daedalus.ariadne.conflict_detector.ConflictDetector.

Covers the four outcomes analyze_pair can produce: no conflict, file-level overlap
(auto-resolvable), line-level overlap (escalate), and a delete/modify conflict (critical).
"""

from daedalus.ariadne.conflict_detector import ConflictDetector, ConflictSeverity
from daedalus.ariadne.diff_bus import Diff, MergeStrategy


def make_diff(diff_id, files_modified=None, files_added=None, files_deleted=None, line_changes=None):
    return Diff(
        id=diff_id,
        work_id=f"wp-{diff_id}",
        instance_id="icarus-1",
        content="",
        description=f"diff {diff_id}",
        files_modified=files_modified or [],
        files_added=files_added or [],
        files_deleted=files_deleted or [],
        line_changes=line_changes or {},
    )


def test_no_conflict_when_no_files_overlap():
    detector = ConflictDetector()
    diff_a = make_diff("a", files_modified=["src/a.py"])
    diff_b = make_diff("b", files_modified=["src/b.py"])

    assert detector.analyze_pair(diff_a, diff_b) is None


def test_file_overlap_without_line_overlap_is_low_and_auto_resolvable():
    detector = ConflictDetector()
    diff_a = make_diff("a", files_modified=["src/a.py"], line_changes={"src/a.py": [(1, 5, "modify")]})
    diff_b = make_diff("b", files_modified=["src/a.py"], line_changes={"src/a.py": [(50, 55, "modify")]})

    analysis = detector.analyze_pair(diff_a, diff_b)

    assert analysis is not None
    assert analysis.severity == ConflictSeverity.LOW
    assert analysis.auto_resolvable is True
    assert analysis.suggested_strategy == MergeStrategy.SEQUENTIAL


def test_overlapping_lines_are_high_and_escalated():
    detector = ConflictDetector()
    diff_a = make_diff("a", files_modified=["src/a.py"], line_changes={"src/a.py": [(10, 20, "modify")]})
    diff_b = make_diff("b", files_modified=["src/a.py"], line_changes={"src/a.py": [(15, 25, "modify")]})

    analysis = detector.analyze_pair(diff_a, diff_b)

    assert analysis is not None
    assert analysis.severity == ConflictSeverity.HIGH
    assert analysis.auto_resolvable is False
    assert analysis.suggested_strategy == MergeStrategy.ESCALATE
    assert "src/a.py" in analysis.conflict.affected_lines


def test_delete_modify_is_critical_and_escalated():
    detector = ConflictDetector()
    diff_a = make_diff("a", files_deleted=["src/a.py"])
    diff_b = make_diff("b", files_modified=["src/a.py"])

    analysis = detector.analyze_pair(diff_a, diff_b)

    assert analysis is not None
    assert analysis.severity == ConflictSeverity.CRITICAL
    assert analysis.auto_resolvable is False
    assert analysis.suggested_strategy == MergeStrategy.ESCALATE


def test_analyze_all_sorts_by_severity_critical_first():
    detector = ConflictDetector()
    low_a = make_diff("low-a", files_modified=["src/x.py"], line_changes={"src/x.py": [(1, 2, "modify")]})
    low_b = make_diff("low-b", files_modified=["src/x.py"], line_changes={"src/x.py": [(100, 101, "modify")]})
    critical_a = make_diff("crit-a", files_deleted=["src/y.py"])
    critical_b = make_diff("crit-b", files_modified=["src/y.py"])

    analyses = detector.analyze_all([low_a, low_b, critical_a, critical_b])

    assert len(analyses) == 2
    assert analyses[0].severity == ConflictSeverity.CRITICAL
    assert analyses[1].severity == ConflictSeverity.LOW
