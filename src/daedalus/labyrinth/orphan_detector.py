"""
Orphan Code Detection for Mind Palace.

Finds functions and methods that are never called by other code in the project.
Distinguishes between true orphans (dead code) and framework entry points.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .cartographer import _is_noise_element
from .languages import CodeElement, get_language_registry

logger = logging.getLogger(__name__)


@dataclass
class OrphanReport:
    """Report on a potential orphan function/method."""
    node_id: str
    name: str
    simple_name: str
    element_type: str
    file: str
    line: int
    module: str
    confidence: str  # "high", "medium", "low"
    reason: str  # Why we think it's an orphan


@dataclass
class OrphanSummary:
    """Summary of orphan detection results."""
    total_functions: int
    never_called: int
    filtered_entry_points: int
    true_orphans: int
    orphans_by_module: Dict[str, List[OrphanReport]]
    high_confidence: List[OrphanReport]
    framework_entry_points: int


# Patterns that indicate framework-called code (not true orphans)
FRAMEWORK_PATTERNS = {
    # FastAPI/Starlette
    "fastapi_route": re.compile(r"^(get|post|put|delete|patch|head|options)_"),
    "fastapi_lifecycle": {"startup", "shutdown", "lifespan", "on_startup", "on_shutdown"},
    "fastapi_middleware": {"dispatch", "add_security_headers", "global_exception_handler"},
    "fastapi_deps": re.compile(r"^get_current_|^verify_|^require_"),

    # GraphQL (Strawberry, Graphene, etc.)
    "graphql_resolver": re.compile(r"^resolve_|_resolver$"),
    "graphql_mutation": re.compile(r"^mutate_|_mutation$"),

    # AST Visitor pattern
    "ast_visitor": re.compile(r"^visit_|^generic_visit$"),

    # Pydantic/dataclass validators
    "pydantic": re.compile(r"^validate_|^validator_|_validator$"),

    # SQLAlchemy/ORM
    "orm_hooks": {"before_insert", "after_insert", "before_update", "after_update",
                  "before_delete", "after_delete", "on_load"},

    # Pytest
    "pytest": re.compile(r"^test_|^fixture_|_fixture$"),

    # Click/CLI
    "cli_command": re.compile(r"^cli_|_command$|^cmd_"),

    # Event handlers
    "event_handler": re.compile(r"^on_|^handle_|_handler$|_callback$"),

    # Property-like (called via attribute access)
    "property_like": re.compile(r"^is_|^has_|^can_|^should_|^get_(?!current)|^set_(?!current)"),
}

# Module patterns that are primarily entry points
ENTRY_POINT_MODULES = {
    "routes",
    "handlers",
    "websocket",
    "graphql",
    "api",
    "views",
    "endpoints",
    "cli",
    "commands",
    "scripts",
    "tests",
    "test_",
    "conftest",
}


def _classify_potential_orphan(
    node_id: str,
    node: dict,
) -> Tuple[bool, str, str]:
    """
    Classify whether a node is a true orphan or a framework entry point.

    Returns:
        (is_orphan, confidence, reason)
    """
    name = node["simple"]
    module = node["module"]
    element_type = node["type"]

    # Check module-level entry points
    for pattern in ENTRY_POINT_MODULES:
        if pattern in module.lower():
            return False, "low", f"Entry point module: {pattern}"

    # Check FastAPI routes
    if FRAMEWORK_PATTERNS["fastapi_route"].match(name):
        return False, "low", "FastAPI route handler pattern"

    if name in FRAMEWORK_PATTERNS["fastapi_lifecycle"]:
        return False, "low", "FastAPI lifecycle hook"

    if name in FRAMEWORK_PATTERNS["fastapi_middleware"]:
        return False, "low", "FastAPI middleware"

    if FRAMEWORK_PATTERNS["fastapi_deps"].match(name):
        return False, "low", "FastAPI dependency"

    # Check GraphQL
    if FRAMEWORK_PATTERNS["graphql_resolver"].match(name):
        return False, "low", "GraphQL resolver"

    if FRAMEWORK_PATTERNS["graphql_mutation"].match(name):
        return False, "low", "GraphQL mutation"

    # Check AST visitor
    if FRAMEWORK_PATTERNS["ast_visitor"].match(name):
        return False, "low", "AST visitor method"

    # Check Pydantic
    if FRAMEWORK_PATTERNS["pydantic"].match(name):
        return False, "low", "Pydantic validator"

    # Check ORM hooks
    if name in FRAMEWORK_PATTERNS["orm_hooks"]:
        return False, "low", "ORM lifecycle hook"

    # Check pytest
    if FRAMEWORK_PATTERNS["pytest"].match(name):
        return False, "low", "Pytest test/fixture"

    # Check CLI
    if FRAMEWORK_PATTERNS["cli_command"].match(name):
        return False, "low", "CLI command"

    # Check event handlers
    if FRAMEWORK_PATTERNS["event_handler"].match(name):
        return False, "low", "Event handler"

    # Check property-like methods (often called via getattr)
    if FRAMEWORK_PATTERNS["property_like"].match(name):
        return True, "medium", "Property-like method - may be accessed dynamically"

    # Common entry point names
    if name in {"main", "app", "create_app", "run", "execute", "start", "setup"}:
        return False, "low", "Common entry point name"

    # If it's a class method with common interface names
    interface_methods = {"process", "execute", "run", "call", "invoke", "apply",
                        "transform", "render", "build", "create", "load", "save",
                        "send", "receive", "publish", "subscribe"}
    if name in interface_methods:
        return True, "medium", "Common interface method - may be called polymorphically"

    # Check if it looks like a public API method
    if element_type == "method" and not name.startswith("_"):
        # Methods on classes are often part of public API
        return True, "medium", "Public method - verify if part of class API"

    # Standalone functions with no callers = high confidence orphan
    if element_type == "function" and not name.startswith("_"):
        return True, "high", "Standalone function with no internal callers"

    return True, "high", "No callers found"


def detect_orphans(
    project_root: Path,
    include_medium_confidence: bool = True,
    include_low_confidence: bool = False,
) -> OrphanSummary:
    """
    Detect orphan code in a project.

    Args:
        project_root: Root directory to analyze
        include_medium_confidence: Include medium-confidence orphans
        include_low_confidence: Include framework entry points (low confidence)

    Returns:
        OrphanSummary with detection results
    """
    registry = get_language_registry()

    # Build call graph
    nodes: Dict[str, dict] = {}

    # Collect all source files
    skip_dirs = {"node_modules", "venv", "__pycache__", ".git", "dist", "build", ".venv", "env"}
    source_files = []

    for ext in registry.supported_extensions():
        source_files.extend(project_root.rglob(f"*{ext}"))

    source_files = [
        f for f in source_files
        if not any(skip in f.parts for skip in skip_dirs)
    ]

    # First pass: collect all nodes
    for source_file in source_files:
        try:
            lang = registry.get_by_extension(source_file)
            if not lang:
                continue

            elements = lang.analyze_file(source_file, project_root)
            rel_path = source_file.relative_to(project_root)
            module = str(rel_path.with_suffix("")).replace("/", ".")

            for element in elements:
                if _is_noise_element(element):
                    continue

                node_id = f"{module}.{element.name}"
                nodes[node_id] = {
                    "name": element.name,
                    "simple": element.simple_name,
                    "type": element.element_type,
                    "file": str(rel_path),
                    "line": element.line,
                    "calls": element.calls,
                    "called_by": [],
                    "module": module,
                }
        except Exception as e:
            logger.warning(f"Error analyzing {source_file}: {e}")
            continue

    # Second pass: build called_by relationships
    for node_id, node in nodes.items():
        for call in node["calls"]:
            # Find target by simple name
            for target_id, target in nodes.items():
                if target["simple"] == call or target["name"] == call:
                    target["called_by"].append(node_id)

    # Find orphans
    total_functions = len([n for n in nodes.values() if n["type"] in ("function", "method")])
    never_called = []

    for node_id, node in nodes.items():
        if len(node["called_by"]) == 0 and node["type"] in ("function", "method"):
            never_called.append((node_id, node))

    # Classify orphans
    orphans_by_module: Dict[str, List[OrphanReport]] = {}
    high_confidence: List[OrphanReport] = []
    filtered_entry_points = 0
    true_orphans = 0

    for node_id, node in never_called:
        is_orphan, confidence, reason = _classify_potential_orphan(node_id, node)

        if not is_orphan:
            filtered_entry_points += 1
            if not include_low_confidence:
                continue
            confidence = "low"

        # Filter by confidence level
        if confidence == "medium" and not include_medium_confidence:
            continue
        if confidence == "low" and not include_low_confidence:
            continue

        if is_orphan:
            true_orphans += 1

        report = OrphanReport(
            node_id=node_id,
            name=node["name"],
            simple_name=node["simple"],
            element_type=node["type"],
            file=node["file"],
            line=node["line"],
            module=node["module"],
            confidence=confidence,
            reason=reason,
        )

        # Group by module
        if node["module"] not in orphans_by_module:
            orphans_by_module[node["module"]] = []
        orphans_by_module[node["module"]].append(report)

        if confidence == "high":
            high_confidence.append(report)

    return OrphanSummary(
        total_functions=total_functions,
        never_called=len(never_called),
        filtered_entry_points=filtered_entry_points,
        true_orphans=true_orphans,
        orphans_by_module=orphans_by_module,
        high_confidence=high_confidence,
        framework_entry_points=filtered_entry_points,
    )


def format_orphan_report(summary: OrphanSummary, max_per_module: int = 5) -> str:
    """Format orphan summary as a readable report."""
    lines = [
        "ORPHAN CODE DETECTION REPORT",
        "=" * 60,
        "",
        "SUMMARY:",
        f"  Total functions/methods: {summary.total_functions}",
        f"  Never called internally: {summary.never_called}",
        f"  Framework entry points:  {summary.framework_entry_points}",
        f"  True orphans:            {summary.true_orphans}",
        "",
    ]

    if summary.high_confidence:
        lines.extend([
            "HIGH CONFIDENCE ORPHANS (likely dead code):",
            "-" * 40,
        ])

        # Group high confidence by module
        by_mod: Dict[str, List[OrphanReport]] = {}
        for o in summary.high_confidence:
            if o.module not in by_mod:
                by_mod[o.module] = []
            by_mod[o.module].append(o)

        for module, orphans in sorted(by_mod.items(), key=lambda x: -len(x[1])):
            lines.append(f"\n{module} ({len(orphans)} orphans):")
            for o in orphans[:max_per_module]:
                lines.append(f"  {o.simple_name}  ({o.file}:{o.line})")
                lines.append(f"    -> {o.reason}")
            if len(orphans) > max_per_module:
                lines.append(f"  ... and {len(orphans) - max_per_module} more")

    # Show modules with most orphans
    if summary.orphans_by_module:
        sorted_modules = sorted(
            summary.orphans_by_module.items(),
            key=lambda x: -len(x[1])
        )

        lines.extend([
            "",
            "MODULES BY ORPHAN COUNT:",
            "-" * 40,
        ])

        for module, orphans in sorted_modules[:15]:
            high = len([o for o in orphans if o.confidence == "high"])
            med = len([o for o in orphans if o.confidence == "medium"])
            lines.append(f"  {module}: {len(orphans)} total ({high} high, {med} medium)")

    return "\n".join(lines)
