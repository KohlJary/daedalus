"""
Icarus Bus - File-based coordination for Daedalus/Icarus parallelization.

Provides work dispatch, status tracking, and result collection for
parallel Claude Code sessions.

When Icarus is disabled (default), a NullBus is used that returns empty
results for reads and raises helpful errors for writes.
"""

from .icarus_bus import (
    IcarusBus,
    IcarusInstance,
    WorkPackage,
    Request,
    Response,
    InstanceStatus,
    WorkStatus,
    RequestType,
    BUS_ROOT,
)

from .null_bus import NullBus

from .permissions import (
    PermissionType,
    PermissionRequest,
    ApprovalScope,
    classify_tool,
    check_auto_approve,
    create_permission_request,
)


def get_bus() -> IcarusBus | NullBus:
    """
    Get the appropriate bus instance based on configuration.

    Returns IcarusBus if Icarus is enabled, NullBus otherwise.
    """
    try:
        from ..config import load_config
        config = load_config()
        if config.icarus.enabled:
            return IcarusBus()
    except Exception:
        pass
    return NullBus()


__all__ = [
    # Core bus
    "IcarusBus",
    "NullBus",
    "get_bus",
    "IcarusInstance",
    "WorkPackage",
    "Request",
    "Response",
    "InstanceStatus",
    "WorkStatus",
    "RequestType",
    "BUS_ROOT",
    # Permissions
    "PermissionType",
    "PermissionRequest",
    "ApprovalScope",
    "classify_tool",
    "check_auto_approve",
    "create_permission_request",
]
