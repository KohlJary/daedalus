"""
Daedalus - Claude Code plugin with Mind Palace navigation and Icarus parallel workers.

A plugin ecosystem for Claude Code workflows, including:
- Labyrinth: MUD-based codebase navigation (Mind Palace)
- Icarus Bus: Parallel work coordination
- Identity framework: Worker instances with soul
"""

from importlib.metadata import PackageNotFoundError, version as _version

# Single source of truth is pyproject.toml; this was hardcoded and drifted twice
try:
    __version__ = _version("daedalus-cli")
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0.0.0+unknown"

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
