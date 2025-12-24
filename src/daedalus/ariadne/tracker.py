"""
Ariadne Tracker

Tracks feature progress and updates roadmap items.

The tracker:
1. Creates/updates roadmap items as features progress
2. Tracks completion of work packages
3. Links commits to roadmap items
4. Provides progress visibility
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional

from .planner import ImplementationPlan, FeatureRequest
from .dispatcher import PlanDispatchState


@dataclass
class RoadmapItem:
    """A roadmap item (matches existing roadmap schema)."""
    id: str
    title: str
    description: str
    status: str = "backlog"  # backlog, ready, in_progress, review, done
    priority: str = "P2"
    item_type: str = "feature"
    assigned_to: str = "ariadne"
    tags: List[str] = field(default_factory=list)
    created_by: str = "ariadne"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Ariadne-specific fields
    plan_id: Optional[str] = None
    feature_id: Optional[str] = None
    commit_hash: Optional[str] = None
    parent_id: Optional[str] = None  # For sub-items

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "RoadmapItem":
        return cls(**data)


@dataclass
class FeatureProgress:
    """Progress tracking for a feature."""
    feature_id: str
    plan_id: str
    title: str
    status: str  # planning, dispatching, in_progress, verifying, complete, failed

    # Counts
    total_packages: int = 0
    completed_packages: int = 0
    failed_packages: int = 0

    # Timing
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Results
    commit_hash: Optional[str] = None
    error: Optional[str] = None

    @property
    def percent_complete(self) -> int:
        if self.total_packages == 0:
            return 0
        return int((self.completed_packages / self.total_packages) * 100)


class Tracker:
    """
    Tracks feature progress and manages roadmap integration.

    Responsibilities:
    - Create roadmap items for features
    - Update item status as work progresses
    - Track sub-items for work packages
    - Link commits to items on completion
    """

    def __init__(self, roadmap_path: Optional[Path] = None):
        """
        Initialize tracker.

        Args:
            roadmap_path: Path to .daedalus/roadmap/ directory
        """
        self.roadmap_path = roadmap_path or Path(".daedalus/roadmap")
        self.roadmap_path.mkdir(parents=True, exist_ok=True)
        self.items_path = self.roadmap_path / "items"
        self.items_path.mkdir(exist_ok=True)
        self.index_path = self.roadmap_path / "index.json"

        # Ensure index exists
        if not self.index_path.exists():
            self._save_index([])

    # ========== Feature Lifecycle ==========

    def start_feature(
        self,
        request: FeatureRequest,
        plan: ImplementationPlan,
    ) -> RoadmapItem:
        """
        Start tracking a feature.

        Creates a roadmap item and sub-items for each work package.
        """
        # Create main feature item
        item = RoadmapItem(
            id=self._generate_id(),
            title=request.title,
            description=request.description,
            status="in_progress",
            priority=request.priority,
            item_type="feature",
            tags=request.tags,
            plan_id=plan.id,
            feature_id=request.id,
        )

        self._save_item(item)

        # Create sub-items for work packages
        for wp in plan.work_packages:
            sub_item = RoadmapItem(
                id=self._generate_id(),
                title=wp.title,
                description=wp.description,
                status="ready",
                priority=request.priority,
                item_type="task",
                tags=wp.tags,
                plan_id=plan.id,
                feature_id=request.id,
                parent_id=item.id,
            )
            self._save_item(sub_item)

        return item

    def update_package_status(
        self,
        plan_id: str,
        package_title: str,
        status: str,
    ) -> Optional[RoadmapItem]:
        """Update a work package sub-item's status."""
        items = self._load_items_by_plan(plan_id)

        for item in items:
            if item.title == package_title and item.item_type == "task":
                item.status = status
                item.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_item(item)
                return item

        return None

    def complete_feature(
        self,
        plan_id: str,
        commit_hash: Optional[str] = None,
    ) -> Optional[RoadmapItem]:
        """
        Mark a feature as complete.

        Updates the main item to 'review' status and links the commit.
        """
        items = self._load_items_by_plan(plan_id)

        for item in items:
            if item.plan_id == plan_id and item.item_type == "feature":
                item.status = "review"
                item.commit_hash = commit_hash
                item.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_item(item)

                # Also complete all sub-items
                for sub in items:
                    if sub.parent_id == item.id:
                        sub.status = "done"
                        sub.updated_at = datetime.now(timezone.utc).isoformat()
                        self._save_item(sub)

                return item

        return None

    def fail_feature(
        self,
        plan_id: str,
        error: str,
    ) -> Optional[RoadmapItem]:
        """Mark a feature as failed."""
        items = self._load_items_by_plan(plan_id)

        for item in items:
            if item.plan_id == plan_id and item.item_type == "feature":
                item.status = "backlog"  # Return to backlog for retry
                item.description += f"\n\n**Failed**: {error}"
                item.updated_at = datetime.now(timezone.utc).isoformat()
                self._save_item(item)
                return item

        return None

    # ========== Progress Queries ==========

    def get_feature_progress(self, plan_id: str) -> Optional[FeatureProgress]:
        """Get progress for a feature."""
        items = self._load_items_by_plan(plan_id)

        feature_item = None
        sub_items = []

        for item in items:
            if item.item_type == "feature" and item.plan_id == plan_id:
                feature_item = item
            elif item.parent_id and item.plan_id == plan_id:
                sub_items.append(item)

        if not feature_item:
            return None

        completed = sum(1 for i in sub_items if i.status == "done")
        failed = sum(1 for i in sub_items if "failed" in i.description.lower())

        # Determine overall status
        if feature_item.status == "done":
            status = "complete"
        elif feature_item.status == "review":
            status = "verifying"
        elif completed == len(sub_items) and sub_items:
            status = "verifying"
        elif completed > 0:
            status = "in_progress"
        else:
            status = "dispatching"

        return FeatureProgress(
            feature_id=feature_item.feature_id or "",
            plan_id=plan_id,
            title=feature_item.title,
            status=status,
            total_packages=len(sub_items),
            completed_packages=completed,
            failed_packages=failed,
            commit_hash=feature_item.commit_hash,
        )

    def get_active_features(self) -> List[FeatureProgress]:
        """Get all features currently being worked on."""
        all_items = self._load_all_items()

        # Group by plan_id
        by_plan: Dict[str, List[RoadmapItem]] = {}
        for item in all_items:
            if item.plan_id:
                if item.plan_id not in by_plan:
                    by_plan[item.plan_id] = []
                by_plan[item.plan_id].append(item)

        features = []
        for plan_id, items in by_plan.items():
            progress = self.get_feature_progress(plan_id)
            if progress and progress.status not in ["complete", "failed"]:
                features.append(progress)

        return features

    # ========== Item Management ==========

    def get_item(self, item_id: str) -> Optional[RoadmapItem]:
        """Get a specific roadmap item."""
        item_file = self.items_path / f"{item_id}.json"
        if item_file.exists():
            data = json.loads(item_file.read_text())
            return RoadmapItem.from_dict(data)
        return None

    def list_items(
        self,
        status: Optional[str] = None,
        item_type: Optional[str] = None,
    ) -> List[RoadmapItem]:
        """List roadmap items with optional filters."""
        items = self._load_all_items()

        if status:
            items = [i for i in items if i.status == status]
        if item_type:
            items = [i for i in items if i.item_type == item_type]

        return sorted(items, key=lambda i: i.updated_at, reverse=True)

    # ========== Private Helpers ==========

    def _generate_id(self) -> str:
        """Generate a short unique ID."""
        return uuid.uuid4().hex[:8]

    def _save_item(self, item: RoadmapItem) -> None:
        """Save an item to disk."""
        item_file = self.items_path / f"{item.id}.json"
        item_file.write_text(json.dumps(item.to_dict(), indent=2))
        self._update_index(item)

    def _update_index(self, item: RoadmapItem) -> None:
        """Update the index with item summary."""
        index = self._load_index()

        # Find and update or append
        found = False
        for i, entry in enumerate(index):
            if entry.get("id") == item.id:
                index[i] = {
                    "id": item.id,
                    "title": item.title,
                    "status": item.status,
                    "priority": item.priority,
                    "item_type": item.item_type,
                    "updated_at": item.updated_at,
                }
                found = True
                break

        if not found:
            index.append({
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "priority": item.priority,
                "item_type": item.item_type,
                "updated_at": item.updated_at,
            })

        self._save_index(index)

    def _load_index(self) -> List[Dict]:
        """Load the index."""
        if self.index_path.exists():
            return json.loads(self.index_path.read_text())
        return []

    def _save_index(self, index: List[Dict]) -> None:
        """Save the index."""
        self.index_path.write_text(json.dumps(index, indent=2))

    def _load_all_items(self) -> List[RoadmapItem]:
        """Load all items from disk."""
        items = []
        for item_file in self.items_path.glob("*.json"):
            data = json.loads(item_file.read_text())
            items.append(RoadmapItem.from_dict(data))
        return items

    def _load_items_by_plan(self, plan_id: str) -> List[RoadmapItem]:
        """Load all items for a specific plan."""
        return [i for i in self._load_all_items() if i.plan_id == plan_id]
