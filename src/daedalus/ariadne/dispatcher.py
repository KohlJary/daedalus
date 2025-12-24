"""
Ariadne Dispatcher

Converts implementation plans into WorkPackages and dispatches to Icarus workers.

The dispatcher:
1. Takes approved ImplementationPlans
2. Converts WorkPackageSpecs into Icarus WorkPackages
3. Respects dependencies (only dispatches when deps are met)
4. Tracks which packages are dispatched/completed
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Set
import json

from .planner import ImplementationPlan, WorkPackageSpec

# Import Icarus bus
try:
    from ..bus.icarus_bus import IcarusBus, WorkPackage, WorkStatus
    HAS_ICARUS = True
except ImportError:
    HAS_ICARUS = False
    IcarusBus = None
    WorkPackage = None


@dataclass
class DispatchRecord:
    """Tracks the dispatch state of a work package."""
    spec_id: str
    work_id: Optional[str] = None  # Icarus WorkPackage ID once dispatched
    status: str = "pending"  # pending, dispatched, completed, failed
    dispatched_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict] = None
    diff_id: Optional[str] = None  # Ariadne diff ID if using Ariadne mode


@dataclass
class PlanDispatchState:
    """Tracks the dispatch state of an entire plan."""
    plan_id: str
    feature_id: str
    records: Dict[str, DispatchRecord] = field(default_factory=dict)  # spec_id -> record
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def all_dispatched(self) -> bool:
        """Check if all packages have been dispatched."""
        return all(r.status != "pending" for r in self.records.values())

    def all_completed(self) -> bool:
        """Check if all packages are completed."""
        return all(r.status == "completed" for r in self.records.values())

    def completed_ids(self) -> Set[str]:
        """Get IDs of completed packages."""
        return {r.spec_id for r in self.records.values() if r.status == "completed"}

    def pending_ids(self) -> Set[str]:
        """Get IDs of pending packages."""
        return {r.spec_id for r in self.records.values() if r.status == "pending"}


class Dispatcher:
    """
    Dispatches work packages to Icarus workers.

    Handles:
    - Converting WorkPackageSpecs to Icarus WorkPackages
    - Dependency-aware dispatching
    - Tracking dispatch state
    - Coordinating with Ariadne bus for diff collection
    """

    def __init__(
        self,
        icarus_bus: Optional["IcarusBus"] = None,
        state_dir: Optional[Path] = None,
        use_ariadne: bool = True,
    ):
        """
        Initialize dispatcher.

        Args:
            icarus_bus: Icarus bus for worker dispatch
            state_dir: Where to store dispatch state
            use_ariadne: Whether workers should submit to Ariadne (vs commit directly)
        """
        self.icarus_bus = icarus_bus
        self.state_dir = state_dir or Path(".daedalus/ariadne/dispatch")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.use_ariadne = use_ariadne

    def create_dispatch_state(self, plan: ImplementationPlan) -> PlanDispatchState:
        """Create initial dispatch state for a plan."""
        state = PlanDispatchState(
            plan_id=plan.id,
            feature_id=plan.feature_id,
        )

        for wp in plan.work_packages:
            state.records[wp.id] = DispatchRecord(spec_id=wp.id)

        self._save_state(state)
        return state

    def get_dispatchable(
        self,
        plan: ImplementationPlan,
        state: PlanDispatchState,
    ) -> List[WorkPackageSpec]:
        """
        Get work packages ready for dispatch.

        A package is dispatchable if:
        - It hasn't been dispatched yet
        - All its dependencies are completed
        """
        completed = state.completed_ids()
        dispatchable = []

        for wp in plan.work_packages:
            record = state.records.get(wp.id)
            if not record or record.status != "pending":
                continue

            # Check dependencies
            deps_met = all(dep_id in completed for dep_id in wp.depends_on)
            if deps_met:
                dispatchable.append(wp)

        return dispatchable

    def dispatch_package(
        self,
        spec: WorkPackageSpec,
        state: PlanDispatchState,
        project_root: Optional[Path] = None,
    ) -> Optional[str]:
        """
        Dispatch a single work package to Icarus.

        Returns the Icarus work_id if successful.
        """
        if not HAS_ICARUS or not self.icarus_bus:
            raise RuntimeError("Icarus bus not available")

        # Build the prompt for the worker
        prompt = self._build_worker_prompt(spec)

        # Create Icarus WorkPackage
        work = WorkPackage(
            id="",  # Will be assigned
            type="implementation",
            description=prompt,
            inputs={
                "files": spec.files,
                "ariadne_mode": self.use_ariadne,
                "spec_id": spec.id,
            },
            outputs={
                "expected": "Modified files according to spec",
            },
            constraints=spec.constraints,
            priority=self._complexity_to_priority(spec.estimated_complexity),
        )

        # Post to Icarus bus
        work_id = self.icarus_bus.post_work(work)

        # Update state
        record = state.records[spec.id]
        record.work_id = work_id
        record.status = "dispatched"
        record.dispatched_at = datetime.now(timezone.utc).isoformat()

        if state.started_at is None:
            state.started_at = datetime.now(timezone.utc).isoformat()

        self._save_state(state)

        return work_id

    def dispatch_ready(
        self,
        plan: ImplementationPlan,
        state: PlanDispatchState,
        max_parallel: int = 4,
    ) -> List[str]:
        """
        Dispatch all ready packages up to max_parallel limit.

        Returns list of dispatched work_ids.
        """
        dispatchable = self.get_dispatchable(plan, state)

        # Count currently in-flight
        in_flight = sum(
            1 for r in state.records.values()
            if r.status == "dispatched"
        )

        # Limit to max_parallel
        slots = max_parallel - in_flight
        to_dispatch = dispatchable[:slots]

        work_ids = []
        for spec in to_dispatch:
            work_id = self.dispatch_package(spec, state)
            if work_id:
                work_ids.append(work_id)

        return work_ids

    def mark_completed(
        self,
        state: PlanDispatchState,
        spec_id: str,
        result: Optional[Dict] = None,
        diff_id: Optional[str] = None,
    ) -> None:
        """Mark a work package as completed."""
        record = state.records.get(spec_id)
        if record:
            record.status = "completed"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.result = result
            record.diff_id = diff_id

            # Check if plan is complete
            if state.all_completed():
                state.completed_at = datetime.now(timezone.utc).isoformat()

            self._save_state(state)

    def mark_failed(
        self,
        state: PlanDispatchState,
        spec_id: str,
        error: str,
    ) -> None:
        """Mark a work package as failed."""
        record = state.records.get(spec_id)
        if record:
            record.status = "failed"
            record.completed_at = datetime.now(timezone.utc).isoformat()
            record.result = {"error": error}
            self._save_state(state)

    def _build_worker_prompt(self, spec: WorkPackageSpec) -> str:
        """Build the prompt for an Icarus worker."""
        lines = [
            f"# Task: {spec.title}",
            "",
            spec.description,
            "",
        ]

        if spec.files:
            lines.append("## Files to modify:")
            for f in spec.files:
                lines.append(f"- {f}")
            lines.append("")

        if spec.constraints:
            lines.append("## Constraints:")
            for c in spec.constraints:
                lines.append(f"- {c}")
            lines.append("")

        if self.use_ariadne:
            lines.extend([
                "## Ariadne Mode",
                "Submit your changes as a diff to Ariadne instead of committing directly.",
                "Use `submit_diff_to_ariadne()` after completing your work.",
                "",
            ])

        return "\n".join(lines)

    def _complexity_to_priority(self, complexity: int) -> int:
        """Convert complexity (1-5) to Icarus priority (1-10, lower=higher priority)."""
        # Lower complexity = higher priority (get quick wins first)
        # Map 1-5 to 3-7 (reserve 1-2 for critical, 8-10 for low priority)
        return complexity + 2

    def _save_state(self, state: PlanDispatchState) -> None:
        """Save dispatch state to disk."""
        state_file = self.state_dir / f"{state.plan_id}.json"

        data = {
            "plan_id": state.plan_id,
            "feature_id": state.feature_id,
            "started_at": state.started_at,
            "completed_at": state.completed_at,
            "records": {
                spec_id: asdict(record)
                for spec_id, record in state.records.items()
            },
        }

        state_file.write_text(json.dumps(data, indent=2))

    def load_state(self, plan_id: str) -> Optional[PlanDispatchState]:
        """Load dispatch state from disk."""
        state_file = self.state_dir / f"{plan_id}.json"
        if not state_file.exists():
            return None

        data = json.loads(state_file.read_text())

        state = PlanDispatchState(
            plan_id=data["plan_id"],
            feature_id=data["feature_id"],
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )

        for spec_id, record_data in data.get("records", {}).items():
            state.records[spec_id] = DispatchRecord(**record_data)

        return state

    def get_progress(self, state: PlanDispatchState) -> Dict:
        """Get progress summary for a plan."""
        total = len(state.records)
        completed = sum(1 for r in state.records.values() if r.status == "completed")
        dispatched = sum(1 for r in state.records.values() if r.status == "dispatched")
        pending = sum(1 for r in state.records.values() if r.status == "pending")
        failed = sum(1 for r in state.records.values() if r.status == "failed")

        return {
            "plan_id": state.plan_id,
            "total": total,
            "completed": completed,
            "dispatched": dispatched,
            "pending": pending,
            "failed": failed,
            "percent_complete": int((completed / total) * 100) if total > 0 else 0,
            "started_at": state.started_at,
            "completed_at": state.completed_at,
        }
