"""
Unit tests for daedalus.ariadne.planner's pure decision logic.

Scoped per the Workstream C smoke-test experiment to the cheapest, highest-value
untested surface: _calculate_complexity() and _check_requires_approval() are
pure functions of small inputs (no subprocess/filesystem/git calls), and they
are exactly the gate that decides whether a plan can run autonomously or needs
a human/frontier-model in the loop -- the part that matters most if Ariadne is
ever used to let a cheaper model drive Icarus workers unsupervised.
"""

from pathlib import Path

from daedalus.ariadne.planner import AriadneConfig, FeatureRequest, Planner


def make_planner(tmp_path: Path, **config_kwargs) -> Planner:
    return Planner(
        repo_path=tmp_path,
        config=AriadneConfig(**config_kwargs),
        plans_dir=tmp_path / "plans",
    )


# ========== _calculate_complexity ==========

def test_complexity_is_low_for_small_single_file_change(tmp_path):
    planner = make_planner(tmp_path)
    score = planner._calculate_complexity(
        affected_files=["a.py"], work_packages=[object()], total_lines=20
    )
    assert score == 3  # 1 (files) + 1 (packages) + 1 (lines)


def test_complexity_rises_with_more_files_packages_and_lines(tmp_path):
    planner = make_planner(tmp_path)
    score = planner._calculate_complexity(
        affected_files=[f"f{i}.py" for i in range(6)],
        work_packages=[object() for _ in range(5)],
        total_lines=600,
    )
    assert score == 10  # 3 (files) + 3 (packages) + 4 (lines)


def test_complexity_is_capped_at_ten(tmp_path):
    planner = make_planner(tmp_path)
    score = planner._calculate_complexity(
        affected_files=[f"f{i}.py" for i in range(50)],
        work_packages=[object() for _ in range(50)],
        total_lines=100_000,
    )
    assert score == 10


# ========== _check_requires_approval ==========

def _request(**kwargs) -> FeatureRequest:
    return FeatureRequest.create(title="Test feature", description="desc", **kwargs)


def test_supervised_mode_always_requires_approval(tmp_path):
    planner = make_planner(tmp_path, autonomy="supervised")
    requires, reasons = planner._check_requires_approval(_request(), complexity=0, affected_files=[])
    assert requires is True
    assert reasons


def test_full_autonomy_never_requires_approval(tmp_path):
    """
    This is the mode that matters for "cheap model drives workers unsupervised"
    -- confirms that in 'full' mode, neither complexity nor tags can force a
    stop; there is no safety net left except whatever Ariadne's conflict/
    verification gate does downstream.
    """
    planner = make_planner(tmp_path, autonomy="full", auto_dispatch_threshold=1)
    requires, reasons = planner._check_requires_approval(
        _request(tags=["security"]), complexity=10, affected_files=[]
    )
    assert requires is False
    assert reasons == []


def test_hybrid_mode_requires_approval_for_configured_tags(tmp_path):
    planner = make_planner(tmp_path, autonomy="hybrid")
    requires, reasons = planner._check_requires_approval(
        _request(tags=["security"]), complexity=0, affected_files=[]
    )
    assert requires is True
    assert any("security" in r for r in reasons)


def test_hybrid_mode_requires_approval_above_complexity_threshold(tmp_path):
    planner = make_planner(tmp_path, autonomy="hybrid", auto_dispatch_threshold=3)
    requires, reasons = planner._check_requires_approval(
        _request(), complexity=4, affected_files=[]
    )
    assert requires is True
    assert any("exceeds threshold" in r for r in reasons)


def test_hybrid_mode_auto_dispatches_below_threshold_and_untagged(tmp_path):
    planner = make_planner(tmp_path, autonomy="hybrid", auto_dispatch_threshold=3)
    requires, reasons = planner._check_requires_approval(
        _request(), complexity=2, affected_files=[]
    )
    assert requires is False
    assert reasons == []
