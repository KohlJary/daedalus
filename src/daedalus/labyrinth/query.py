"""
Fast, read-only call-graph queries for the main agent (`daedalus palace callers|callees|impact|path|tests-for`).

Builds the graph straight from source on every call (about 0.3 s on an 18k-line repo) and never touches
the project's .mind-palace storage. It differs from the palace builder's graph in ways that matter for
these queries:

- Private methods and dunders are nodes. The room builder's noise filter drops them, which cuts every
  call chain that passes through a private helper.
- A class links to its __init__, so construction (`Foo()`) carries on into the constructor's calls.
- The analyzer records calls made through an object (`orch.process_pending()`) by bare name; for Python,
  the query graph re-parses each def to tell `obj.name()` from a plain `name()`. A plain call to a name
  defined in the same module links to that definition. A call through an object links to every node
  with that name when there are at most `max_candidates` (for callers outside tests, definitions inside
  test files don't count: test doubles are injected at runtime); past the cap, only same-module definitions
  are linked, and if there are none the name is skipped and reported. This favours recall: what a
  change affects, and which tests reach it.

Recall is good where the call target is unique or nearly so. For interfaces with many implementations
(e.g. an injected `reviewer.review`), every implementation is linked, so precision is low: test lists are
a superset. Calls made through dispatch (CLI runners, callbacks) stay invisible, which is why test
selection falls back to "run the full suite" when it finds nothing.
"""

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .pathfinding import CallGraph, GraphNode

SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "__pycache__", ".git", "dist", "build", ".mind-palace"}


def in_test_file(file: str) -> bool:
    """Defined in test code (tests/, test_*.py, *_test.py, conftest.py)."""
    name = Path(file).name
    return (file.startswith("tests/") or "/tests/" in file or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


class GitError(RuntimeError):
    """git failed (not a repository, unknown base, ...)."""


@dataclass
class QueryGraph:
    graph: CallGraph
    ambiguous_links: int = 0
    skipped: Dict[str, int] = field(default_factory=dict)  # bare name -> number of definitions (over the cap)


def _python_info(path: Path) -> Tuple[Dict[int, int], Dict[int, Set[str]]]:
    """For a Python file: start line -> end line of each def/class, and start line -> names it calls through
    an attribute (`obj.name(...)`). The analyzer records neither."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}, {}
    ends: Dict[int, int] = {}
    attr_calls: Dict[int, Set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ends[node.lineno] = node.end_lineno or node.lineno
            attr_calls[node.lineno] = {c.func.attr for c in ast.walk(node)
                                       if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)}
    return ends, attr_calls


def _collect_nodes(project_root: Path) -> Dict[str, dict]:
    """Every function, method and class, private ones and dunders included."""
    from .cartographer import Cartographer
    from .storage import PalaceStorage

    # analyze_file reads only source; the palace argument is used by palace-building methods
    cart = Cartographer(None, PalaceStorage(project_root))  # type: ignore[arg-type]
    files = []
    for ext in cart.language_registry.supported_extensions():
        files.extend(f for f in project_root.rglob(f"*{ext}") if not SKIP_DIRS & set(f.relative_to(project_root).parts))
    raw: Dict[str, dict] = {}
    for f in sorted(set(files)):
        try:
            elements, _ = cart.analyze_file(f)
        except Exception:
            continue
        rel = f.relative_to(project_root)
        module = str(rel.with_suffix("")).replace("/", ".")
        ends, attr_calls = _python_info(f) if f.suffix == ".py" else ({}, {})
        for el in elements:
            node_id = f"{module}.{el.name}"
            raw[node_id] = {"id": node_id, "name": el.name, "simple_name": el.simple_name or el.name.split(".")[-1],
                            "type": el.element_type, "module": module, "file": str(rel), "line": el.line,
                            "end_line": ends.get(el.line), "attr_calls": sorted(attr_calls.get(el.line, ())),
                            "signature": el.signature,
                            "docstring": (el.docstring or "")[:200], "calls": list(el.calls)}
    return raw


def build_query_graph(project_root: Path, max_candidates: int = 10) -> QueryGraph:
    """Build a call graph from source, without reading or writing palace storage."""
    project_root = Path(project_root).resolve()
    raw = _collect_nodes(project_root)

    by_simple: Dict[str, List[str]] = {}
    for node_id, node in raw.items():
        by_simple.setdefault(node["simple_name"], []).append(node_id)

    resolved: Dict[str, Set[str]] = {}
    ambiguous, skipped = 0, {}
    for node_id, node in raw.items():
        targets: Set[str] = set()
        for call in node.get("calls", []):
            if call in raw:
                targets.add(call)
                continue
            through_object = call.split(".")[-1] in node.get("attr_calls", ())
            local = f"{node['module']}.{call}"
            if local in raw and not through_object:  # a plain call: the module's own definition is the target
                targets.add(local)
                continue
            candidates = by_simple.get(call.split(".")[-1], [])
            if not in_test_file(node["file"]):
                # Production code never calls into test files statically; test doubles are injected at runtime
                candidates = [c for c in candidates if not in_test_file(raw[c]["file"])]
            if 0 < len(candidates) <= max_candidates:
                targets.update(candidates)
                ambiguous += len(candidates) > 1
            elif candidates:
                same_module = [c for c in candidates if raw[c]["module"] == node["module"]]
                if same_module:
                    targets.update(same_module)
                else:
                    skipped[call.split(".")[-1]] = len(candidates)
        resolved[node_id] = targets
    for node_id, node in raw.items():  # Foo() carries on into Foo.__init__
        if node["type"] == "class" and f"{node_id}.__init__" in raw:
            resolved[node_id].add(f"{node_id}.__init__")

    graph = CallGraph()
    for node_id, node in raw.items():
        outgoing = sorted(t for t in resolved[node_id] if t != node_id)
        graph.nodes[node_id] = GraphNode.from_dict({**node, "calls": outgoing, "called_by": []})
    for node_id, node in graph.nodes.items():
        for t in node.calls:
            graph.nodes[t].called_by.append(node_id)
        graph.modules.setdefault(node.module, []).append(node_id)
    graph.project = project_root.name
    graph.end_lines = {nid: n.get("end_line") for nid, n in raw.items()}  # type: ignore[attr-defined]
    graph.raw_calls = {nid: list(n.get("calls", [])) for nid, n in raw.items()}  # type: ignore[attr-defined]
    return QueryGraph(graph=graph, ambiguous_links=ambiguous, skipped=skipped)


def resolve_symbol(graph: CallGraph, symbol: str) -> List[str]:
    """Node ids matching a symbol: an exact id, a dotted suffix (Class.method), or a simple name."""
    if symbol in graph.nodes:
        return [symbol]
    suffix = [n for n in graph.nodes if n.endswith("." + symbol)]
    if suffix:
        return sorted(suffix)
    return sorted(n for n, node in graph.nodes.items() if node.simple_name == symbol)


def is_test_node(node: GraphNode) -> bool:
    name = Path(node.file).name
    return (node.file.startswith("tests/") or "/tests/" in node.file or name.startswith("test_")) and \
        node.simple_name.startswith("test")


def reach(graph: CallGraph, node_ids: List[str], direction: str = "backward", max_depth: int = 6) -> Dict[str, int]:
    """Nodes reachable from any of node_ids (callers when backward), with their distance."""
    best: Dict[str, int] = {}
    for nid in node_ids:
        for other, depth in graph.bfs(nid, direction=direction, max_depth=max_depth).items():
            if other not in node_ids and (other not in best or depth < best[other]):
                best[other] = depth
    return best


def tests_reaching(graph: CallGraph, node_ids: List[str], max_depth: int = 6) -> List[str]:
    hits = [n for n in reach(graph, node_ids, "backward", max_depth) if is_test_node(graph.nodes[n])]
    hits += [n for n in node_ids if is_test_node(graph.nodes[n])]
    return sorted(set(hits))


def convention_tests(project_root: Path, files: List[str]) -> List[str]:
    """tests/test_<stem>.py files for the given source files, when they exist."""
    out = []
    for f in files:
        candidate = Path("tests") / f"test_{Path(f).stem}.py"
        if (Path(project_root) / candidate).exists():
            out.append(str(candidate))
    return sorted(set(out))


def nodes_in_file(graph: CallGraph, rel_path: str) -> List[str]:
    rel_path = str(Path(rel_path))
    return sorted(n for n, node in graph.nodes.items() if node.file == rel_path)


def _spans(graph: CallGraph) -> Dict[str, List[Tuple[int, int, str]]]:
    """Per file: (start, end, node_id). Python end lines are exact; otherwise up to the next node's start."""
    end_lines = getattr(graph, "end_lines", {})
    per_file: Dict[str, List[GraphNode]] = {}
    for node in graph.nodes.values():
        per_file.setdefault(node.file, []).append(node)
    spans = {}
    for f, nodes in per_file.items():
        nodes.sort(key=lambda n: n.line)
        out = []
        for i, n in enumerate(nodes):
            end = end_lines.get(n.id) or ((nodes[i + 1].line - 1) if i + 1 < len(nodes) else 10 ** 9)
            out.append((n.line, end, n.id))
        spans[f] = out
    return spans


def _git(project_root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=project_root, capture_output=True, text=True)
    if r.returncode != 0:
        raise GitError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def changed_nodes(graph: CallGraph, project_root: Path, base: str = "HEAD") -> Dict[str, List[str]]:
    """Nodes touched by the working tree's changes against `base`: each changed line maps to the innermost
    def/class containing it (lines outside any def touch nothing); new untracked files count whole."""
    project_root = Path(project_root)
    diff = _git(project_root, "diff", "-U0", "--find-renames", base)
    untracked = _git(project_root, "ls-files", "--others", "--exclude-standard").split()
    changed: Dict[str, Set[int]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
                changed.setdefault(current, set()).update(range(start, start + max(count, 1)))
    spans = _spans(graph)
    out: Dict[str, List[str]] = {}
    for f, lines in changed.items():
        hits = set()
        for ln in lines:
            containing = [(b - a, nid) for (a, b, nid) in spans.get(f, []) if a <= ln <= b]
            if containing:
                hits.add(min(containing)[1])
        if hits:
            out[f] = sorted(hits)
    for f in untracked:
        if nodes_in_file(graph, f):
            out[f] = nodes_in_file(graph, f)
    return out


def project_root_for(cwd: Path) -> Path:
    """The git work tree root when inside one (git reports repo-relative paths), else cwd."""
    try:
        return Path(_git(Path(cwd), "rev-parse", "--show-toplevel").strip())
    except (GitError, FileNotFoundError):
        return Path(cwd).resolve()
