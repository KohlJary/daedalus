"""Test helper: give diffs approved intent the way production does, through an approved plan (edict 0001)."""

import uuid
from pathlib import Path

from daedalus.ariadne.planner import ImplementationPlan, Planner, WorkPackageSpec


def approved_plan(repo: Path, title: str = "Do the work", packages=("wp-1",), approved_by: str = "kohl",
                  edict=None, approve: bool = True, plan_id=None) -> ImplementationPlan:
    plan = ImplementationPlan(
        id=plan_id or f"plan-{uuid.uuid4().hex[:8]}", feature_id="feat-test", feature_title=title, summary="",
        work_packages=[WorkPackageSpec(id=p, title=f"{title} ({p})", description=f"{title}, as requested.",
                                       edict=edict or "") for p in packages],
        source=f"{title}, as requested.", edict=edict,
    )
    planner = Planner(repo)
    if approve:
        planner.approve_plan(plan, approved_by)
    else:
        planner.save_plan(plan)
    return plan


def tag(diff, plan: ImplementationPlan, spec: str = "wp-1"):
    diff.metadata.update(plan_id=plan.id, spec_id=spec)
    return diff
