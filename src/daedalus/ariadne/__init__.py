"""
Ariadne - Orchestration + Causal Verification Layer

The thread through the labyrinth.

Ariadne coordinates parallel Icarus workers by:
1. Receiving feature requests from Daedalus
2. Planning implementation and breaking into work packages
3. Dispatching work to Icarus workers
4. Collecting DIFFs instead of commits
5. Detecting conflicts before they happen
6. Verifying changes via causal slicing
7. Merging verified changes atomically
8. Updating roadmap items as work completes

Mythology: Daedalus (architect) -> Ariadne (planner/coordinator) -> Icarus (workers)

Usage:
    # Plan a feature
    from daedalus.ariadne import Planner, FeatureRequest
    planner = Planner(repo_path)
    request = FeatureRequest.create("Add authentication", "JWT-based auth...")
    plan = planner.analyze_feature(request)

    # Dispatch to workers
    from daedalus.ariadne import Dispatcher
    dispatcher = Dispatcher(icarus_bus)
    state = dispatcher.create_dispatch_state(plan)
    dispatcher.dispatch_ready(plan, state)

    # Process diffs from workers
    from daedalus.ariadne import AriadneOrchestrator
    orchestrator = AriadneOrchestrator(repo_path)
    result = orchestrator.process_pending()

    # Track progress
    from daedalus.ariadne import Tracker
    tracker = Tracker()
    progress = tracker.get_feature_progress(plan.id)
"""

from .diff_bus import (
    AriadneBus,
    Diff,
    DiffStatus,
    CausalChain,
    Conflict,
    ConflictType,
    MergeResult,
    MergeStrategy,
)

from .conflict_detector import (
    ConflictDetector,
    ConflictAnalysis,
    ConflictSeverity,
    check_causal_conflict,
)

from .verification import (
    CausalSliceVerifier,
    VerificationResult,
    extract_causal_chain,
)

from .orchestrator import (
    AriadneOrchestrator,
    OrchestrationResult,
)

from .planner import (
    Planner,
    FeatureRequest,
    ImplementationPlan,
    WorkPackageSpec,
    RiskAssessment,
    AriadneConfig,
)

from .dispatcher import (
    Dispatcher,
    DispatchRecord,
    PlanDispatchState,
)

from .tracker import (
    Tracker,
    RoadmapItem,
    FeatureProgress,
)

__all__ = [
    # Bus
    "AriadneBus",
    "Diff",
    "DiffStatus",
    "CausalChain",
    "Conflict",
    "ConflictType",
    "MergeResult",
    "MergeStrategy",
    # Conflict detection
    "ConflictDetector",
    "ConflictAnalysis",
    "ConflictSeverity",
    "check_causal_conflict",
    # Verification
    "CausalSliceVerifier",
    "VerificationResult",
    "extract_causal_chain",
    # Orchestration
    "AriadneOrchestrator",
    "OrchestrationResult",
    # Planning
    "Planner",
    "FeatureRequest",
    "ImplementationPlan",
    "WorkPackageSpec",
    "RiskAssessment",
    "AriadneConfig",
    # Dispatch
    "Dispatcher",
    "DispatchRecord",
    "PlanDispatchState",
    # Tracking
    "Tracker",
    "RoadmapItem",
    "FeatureProgress",
]
