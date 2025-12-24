"""
Ariadne Planner

Converts feature requests into implementation plans with work breakdown.

The planner:
1. Receives feature requests from Daedalus
2. Analyzes affected files and complexity
3. Optionally runs Theseus for risk assessment
4. Breaks the feature into WorkPackages
5. Determines if approval is needed based on config
"""

import hashlib
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
import json
import re


@dataclass
class FeatureRequest:
    """
    Input from Kohl + Daedalus design session.

    This is the starting point for Ariadne's planning process.
    """
    id: str
    title: str
    description: str  # Markdown with requirements
    constraints: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    priority: str = "P2"  # P0-P3
    roadmap_item_id: Optional[str] = None  # Link to existing roadmap item
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = "daedalus"

    @classmethod
    def create(cls, title: str, description: str, **kwargs) -> "FeatureRequest":
        """Create a new feature request with generated ID."""
        feature_id = f"feat-{hashlib.sha256(f'{title}{datetime.now().isoformat()}'.encode()).hexdigest()[:8]}"
        return cls(id=feature_id, title=title, description=description, **kwargs)


@dataclass
class WorkPackageSpec:
    """
    Specification for a WorkPackage before dispatch.

    This is Ariadne's plan for what work needs to be done,
    before it becomes an actual WorkPackage in the Icarus bus.
    """
    id: str
    title: str
    description: str
    files: List[str] = field(default_factory=list)
    estimated_lines: int = 0
    estimated_complexity: int = 1  # 1-5 scale
    constraints: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)  # Other package IDs
    tags: List[str] = field(default_factory=list)


@dataclass
class RiskAssessment:
    """Risk assessment from Theseus analysis."""
    has_hydra: bool = False  # High coupling
    has_spider: bool = False  # Deep nesting
    has_minotaur: bool = False  # God functions
    has_cerberus: bool = False  # Multiple entry points
    has_chimera: bool = False  # Mixed abstractions
    monsters_found: List[Dict] = field(default_factory=list)
    safe_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ImplementationPlan:
    """
    Ariadne's plan for implementing a feature.

    Contains the full work breakdown, complexity assessment,
    and approval status.
    """
    id: str
    feature_id: str
    feature_title: str
    summary: str

    # Analysis
    affected_files: List[str] = field(default_factory=list)
    affected_modules: List[str] = field(default_factory=list)
    complexity_score: int = 0  # 0-10 scale
    risk_assessment: Optional[Dict] = None  # From Theseus

    # Work breakdown
    work_packages: List[WorkPackageSpec] = field(default_factory=list)
    dependencies: Dict[str, List[str]] = field(default_factory=dict)  # package_id -> [depends_on_ids]
    total_estimated_lines: int = 0

    # Approval
    requires_approval: bool = False
    approval_reasons: List[str] = field(default_factory=list)
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    # Status
    status: str = "draft"  # draft, pending_approval, approved, dispatched, completed
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        result = asdict(self)
        # Convert WorkPackageSpec objects
        result["work_packages"] = [asdict(wp) for wp in self.work_packages]
        return result

    @classmethod
    def from_dict(cls, data: Dict) -> "ImplementationPlan":
        """Create from dictionary."""
        # Convert work_packages back to WorkPackageSpec objects
        work_packages = [WorkPackageSpec(**wp) for wp in data.pop("work_packages", [])]
        return cls(work_packages=work_packages, **data)


@dataclass
class AriadneConfig:
    """Configuration for Ariadne planner."""
    autonomy: str = "hybrid"  # supervised, hybrid, full
    auto_dispatch_threshold: int = 3  # Complexity threshold for auto-dispatch
    require_approval_for: List[str] = field(default_factory=lambda: [
        "breaking_change", "security", "architecture", "database"
    ])
    max_parallel_workers: int = 4
    theseus_analysis: bool = True

    @classmethod
    def from_dict(cls, data: Dict) -> "AriadneConfig":
        """Load from config dict."""
        return cls(
            autonomy=data.get("autonomy", "hybrid"),
            auto_dispatch_threshold=data.get("auto_dispatch_threshold", 3),
            require_approval_for=data.get("require_approval_for", [
                "breaking_change", "security", "architecture", "database"
            ]),
            max_parallel_workers=data.get("max_parallel_workers", 4),
            theseus_analysis=data.get("theseus_analysis", True),
        )


class Planner:
    """
    Converts feature requests into implementation plans.

    The planner analyzes the codebase, estimates complexity,
    and breaks features into dispatchable work packages.
    """

    def __init__(
        self,
        repo_path: Path,
        config: Optional[AriadneConfig] = None,
        plans_dir: Optional[Path] = None,
    ):
        """
        Initialize planner.

        Args:
            repo_path: Path to the git repository
            config: Ariadne configuration
            plans_dir: Where to store plans (default: .daedalus/ariadne/plans/)
        """
        self.repo_path = Path(repo_path)
        self.config = config or AriadneConfig()
        self.plans_dir = plans_dir or (self.repo_path / ".daedalus" / "ariadne" / "plans")
        self.plans_dir.mkdir(parents=True, exist_ok=True)

    def analyze_feature(self, request: FeatureRequest) -> ImplementationPlan:
        """
        Analyze a feature request and generate an implementation plan.

        This is the main entry point for planning.
        """
        plan_id = f"plan-{request.id}"

        # Parse the description for file hints
        mentioned_files = self._extract_file_mentions(request.description)

        # Analyze which files will likely be affected
        affected_files = self._analyze_affected_files(request, mentioned_files)
        affected_modules = self._extract_modules(affected_files)

        # Generate work breakdown
        work_packages = self._generate_work_packages(request, affected_files)

        # Build dependency map
        dependencies = self._build_dependencies(work_packages)

        # Calculate total estimated lines
        total_lines = sum(wp.estimated_lines for wp in work_packages)

        # Calculate complexity score
        complexity = self._calculate_complexity(
            affected_files=affected_files,
            work_packages=work_packages,
            total_lines=total_lines,
        )

        # Check if approval is required
        requires_approval, approval_reasons = self._check_requires_approval(
            request=request,
            complexity=complexity,
            affected_files=affected_files,
        )

        plan = ImplementationPlan(
            id=plan_id,
            feature_id=request.id,
            feature_title=request.title,
            summary=self._generate_summary(request, work_packages),
            affected_files=affected_files,
            affected_modules=affected_modules,
            complexity_score=complexity,
            work_packages=work_packages,
            dependencies=dependencies,
            total_estimated_lines=total_lines,
            requires_approval=requires_approval,
            approval_reasons=approval_reasons,
            status="draft" if not requires_approval else "pending_approval",
        )

        # Save plan
        self._save_plan(plan)

        return plan

    def _extract_file_mentions(self, description: str) -> List[str]:
        """Extract file paths mentioned in the description."""
        # Look for common file path patterns
        patterns = [
            r'`([a-zA-Z0-9_/.-]+\.[a-zA-Z]+)`',  # `path/to/file.py`
            r'(?:^|\s)([a-zA-Z0-9_]+(?:/[a-zA-Z0-9_]+)*\.[a-zA-Z]+)(?:\s|$|,)',  # plain paths
        ]

        files = []
        for pattern in patterns:
            matches = re.findall(pattern, description)
            files.extend(matches)

        return list(set(files))

    def _analyze_affected_files(
        self,
        request: FeatureRequest,
        mentioned_files: List[str],
    ) -> List[str]:
        """
        Analyze which files will likely be affected by this feature.

        Uses:
        - Explicitly mentioned files
        - Keyword-based grep
        - Common patterns (e.g., "add endpoint" → look for routes file)
        """
        affected = set(mentioned_files)

        # Keyword-based search
        keywords = self._extract_keywords(request.title + " " + request.description)

        for keyword in keywords[:5]:  # Limit to top 5 keywords
            try:
                result = subprocess.run(
                    ["grep", "-rl", "--include=*.py", keyword, str(self.repo_path / "src")],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if line:
                            # Convert to relative path
                            rel_path = Path(line).relative_to(self.repo_path)
                            affected.add(str(rel_path))
            except (subprocess.TimeoutExpired, Exception):
                continue

        return sorted(list(affected))

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Remove common words
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
            "be", "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "shall", "can", "need",
            "add", "create", "implement", "make", "build", "update", "fix",
            "this", "that", "these", "those", "it", "its", "they", "them",
        }

        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        # Count frequency
        from collections import Counter
        counts = Counter(keywords)

        return [word for word, _ in counts.most_common(10)]

    def _extract_modules(self, files: List[str]) -> List[str]:
        """Extract Python module names from file paths."""
        modules = []
        for filepath in files:
            if filepath.endswith(".py"):
                module = filepath.replace("/", ".").replace("\\", ".")
                if module.endswith(".py"):
                    module = module[:-3]
                if module.startswith("src."):
                    module = module[4:]
                modules.append(module)
        return modules

    def _generate_work_packages(
        self,
        request: FeatureRequest,
        affected_files: List[str],
    ) -> List[WorkPackageSpec]:
        """
        Break the feature into work packages.

        Heuristics:
        - Group related files together
        - Separate tests from implementation
        - Create logical units of work
        """
        packages = []

        # Group files by directory/module
        file_groups: Dict[str, List[str]] = {}
        test_files: List[str] = []

        for filepath in affected_files:
            if "test" in filepath.lower():
                test_files.append(filepath)
            else:
                # Group by parent directory
                parts = filepath.split("/")
                if len(parts) > 1:
                    group = parts[-2]  # Parent directory
                else:
                    group = "root"
                if group not in file_groups:
                    file_groups[group] = []
                file_groups[group].append(filepath)

        # Create packages for each group
        package_num = 1
        for group, files in file_groups.items():
            wp_id = f"wp-{request.id[:6]}-{package_num:02d}"
            packages.append(WorkPackageSpec(
                id=wp_id,
                title=f"Implement {group} changes",
                description=f"Modify {', '.join(files)} for {request.title}",
                files=files,
                estimated_lines=len(files) * 50,  # Rough estimate
                estimated_complexity=min(len(files), 5),
                constraints=request.constraints.copy(),
                tags=request.tags.copy(),
            ))
            package_num += 1

        # Create test package if there are test files
        if test_files:
            wp_id = f"wp-{request.id[:6]}-{package_num:02d}"
            # Tests depend on all implementation packages
            impl_ids = [p.id for p in packages]
            packages.append(WorkPackageSpec(
                id=wp_id,
                title=f"Add tests for {request.title}",
                description=f"Create/update tests: {', '.join(test_files)}",
                files=test_files,
                estimated_lines=len(test_files) * 100,
                estimated_complexity=2,
                constraints=request.constraints.copy(),
                depends_on=impl_ids,
                tags=["tests"] + request.tags.copy(),
            ))

        # If no packages generated, create a single package
        if not packages:
            wp_id = f"wp-{request.id[:6]}-01"
            packages.append(WorkPackageSpec(
                id=wp_id,
                title=request.title,
                description=request.description,
                files=affected_files,
                estimated_lines=100,
                estimated_complexity=3,
                constraints=request.constraints.copy(),
                tags=request.tags.copy(),
            ))

        return packages

    def _build_dependencies(
        self,
        work_packages: List[WorkPackageSpec],
    ) -> Dict[str, List[str]]:
        """Build dependency map from work packages."""
        deps = {}
        for wp in work_packages:
            if wp.depends_on:
                deps[wp.id] = wp.depends_on
        return deps

    def _calculate_complexity(
        self,
        affected_files: List[str],
        work_packages: List[WorkPackageSpec],
        total_lines: int,
    ) -> int:
        """
        Calculate complexity score (0-10).

        Factors:
        - Number of files affected
        - Number of work packages
        - Estimated lines of code
        """
        score = 0

        # Files factor (0-3)
        if len(affected_files) <= 2:
            score += 1
        elif len(affected_files) <= 5:
            score += 2
        else:
            score += 3

        # Packages factor (0-3)
        if len(work_packages) <= 2:
            score += 1
        elif len(work_packages) <= 4:
            score += 2
        else:
            score += 3

        # Lines factor (0-4)
        if total_lines <= 100:
            score += 1
        elif total_lines <= 300:
            score += 2
        elif total_lines <= 500:
            score += 3
        else:
            score += 4

        return min(score, 10)

    def _check_requires_approval(
        self,
        request: FeatureRequest,
        complexity: int,
        affected_files: List[str],
    ) -> Tuple[bool, List[str]]:
        """
        Determine if plan requires Daedalus approval.

        Returns (requires_approval, reasons).
        """
        reasons = []

        # Check autonomy mode
        if self.config.autonomy == "supervised":
            reasons.append("Supervised mode - all plans require approval")
            return True, reasons

        if self.config.autonomy == "full":
            return False, []

        # Hybrid mode - check conditions

        # Check tags
        for tag in request.tags:
            if tag in self.config.require_approval_for:
                reasons.append(f"Tag '{tag}' requires approval")

        # Check complexity threshold
        if complexity > self.config.auto_dispatch_threshold:
            reasons.append(f"Complexity {complexity} exceeds threshold {self.config.auto_dispatch_threshold}")

        return len(reasons) > 0, reasons

    def _generate_summary(
        self,
        request: FeatureRequest,
        work_packages: List[WorkPackageSpec],
    ) -> str:
        """Generate a human-readable summary of the plan."""
        lines = [
            f"Plan for: {request.title}",
            f"Work packages: {len(work_packages)}",
        ]

        for wp in work_packages:
            deps = f" (depends on: {', '.join(wp.depends_on)})" if wp.depends_on else ""
            lines.append(f"  - {wp.title}{deps}")

        return "\n".join(lines)

    def _save_plan(self, plan: ImplementationPlan) -> None:
        """Save plan to disk."""
        plan_file = self.plans_dir / f"{plan.id}.json"
        plan_file.write_text(json.dumps(plan.to_dict(), indent=2))

    def load_plan(self, plan_id: str) -> Optional[ImplementationPlan]:
        """Load a plan from disk."""
        plan_file = self.plans_dir / f"{plan_id}.json"
        if plan_file.exists():
            data = json.loads(plan_file.read_text())
            return ImplementationPlan.from_dict(data)
        return None

    def list_plans(self, status: Optional[str] = None) -> List[ImplementationPlan]:
        """List all plans, optionally filtered by status."""
        plans = []
        for plan_file in self.plans_dir.glob("*.json"):
            data = json.loads(plan_file.read_text())
            plan = ImplementationPlan.from_dict(data)
            if status is None or plan.status == status:
                plans.append(plan)
        return sorted(plans, key=lambda p: p.created_at, reverse=True)

    def approve_plan(
        self,
        plan_id: str,
        approved_by: str = "daedalus",
    ) -> Optional[ImplementationPlan]:
        """Mark a plan as approved."""
        plan = self.load_plan(plan_id)
        if plan:
            plan.approved = True
            plan.approved_by = approved_by
            plan.approved_at = datetime.now(timezone.utc).isoformat()
            plan.status = "approved"
            self._save_plan(plan)
        return plan

    def reject_plan(
        self,
        plan_id: str,
        reason: str,
        rejected_by: str = "daedalus",
    ) -> Optional[ImplementationPlan]:
        """Mark a plan as rejected."""
        plan = self.load_plan(plan_id)
        if plan:
            plan.approved = False
            plan.status = "rejected"
            plan.approval_reasons.append(f"Rejected: {reason}")
            self._save_plan(plan)
        return plan
