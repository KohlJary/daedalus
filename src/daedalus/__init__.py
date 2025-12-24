"""
Daedalus - Claude Code plugin with Mind Palace navigation and Icarus parallel workers.

A plugin ecosystem for Claude Code workflows, including:
- Labyrinth: MUD-based codebase navigation (Mind Palace)
- Icarus Bus: Parallel work coordination
- Identity framework: Worker instances with soul
"""

__version__ = "0.1.0"

# Re-export key labyrinth components
from .labyrinth import (
    # Core
    Palace,
    Region,
    Building,
    Room,
    Entity,
    # Navigation
    Navigator,
    NavigationResult,
    # Storage
    PalaceStorage,
    # Cartography
    Cartographer,
    # Pathfinding
    CallGraph,
    ImpactAnalysis,
    # Work packages
    WorkPackageManager,
    # Causal slicing
    CausalSlicer,
    # Icarus dispatch
    IcarusDispatcher,
)

# Re-export bus components
from .bus import (
    IcarusBus,
    WorkPackage,
    InstanceStatus,
    WorkStatus,
    RequestType,
)

__all__ = [
    "__version__",
    # Labyrinth - Core
    "Palace",
    "Region",
    "Building",
    "Room",
    "Entity",
    # Labyrinth - Navigation
    "Navigator",
    "NavigationResult",
    # Labyrinth - Storage
    "PalaceStorage",
    # Labyrinth - Cartography
    "Cartographer",
    # Labyrinth - Pathfinding
    "CallGraph",
    "ImpactAnalysis",
    # Labyrinth - Work
    "WorkPackageManager",
    "CausalSlicer",
    "IcarusDispatcher",
    # Bus
    "IcarusBus",
    "WorkPackage",
    "InstanceStatus",
    "WorkStatus",
    "RequestType",
]
