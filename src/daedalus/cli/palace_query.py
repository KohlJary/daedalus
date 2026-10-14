"""Output for `daedalus palace callers|callees|impact|path|tests-for` (queries live in labyrinth/query.py)."""

import json
import sys
from pathlib import Path
from typing import List

import click

STATIC_NOTE = ("static call graph: calls through dispatch (CLI runners, callbacks) can be missed, and a call "
               "through an object links to every definition of that name, so test lists are a superset, not exact")


def _load(cwd: Path):
    from ..labyrinth.query import build_query_graph, project_root_for

    root = project_root_for(cwd)
    return root, build_query_graph(root)


def _where(graph, node_id: str) -> str:
    node = graph.nodes[node_id]
    return f"{node.file}:{node.line}"


def _one(graph, symbol: str) -> str:
    """Resolve a symbol to exactly one node, or exit with the candidates."""
    from ..labyrinth.query import resolve_symbol

    ids = resolve_symbol(graph, symbol)
    if not ids:
        click.echo(f"No symbol matches '{symbol}'. Try Class.method, a module-qualified name, or a simple name. "
                   "(Nested functions aren't nodes: query the enclosing function.)", err=True)
        sys.exit(1)
    if len(ids) > 1:
        click.echo(f"'{symbol}' is ambiguous; {len(ids)} matches:", err=True)
        for i in ids[:20]:
            click.echo(f"  {i}  ({_where(graph, i)})", err=True)
        click.echo("Pass one of these (or a longer suffix such as Class.method).", err=True)
        sys.exit(2)
    return ids[0]


def _emit(data, as_json: bool, lines: List[str]):
    click.echo(json.dumps(data, indent=2) if as_json else "\n".join(lines))


def neighbors(cwd: Path, symbol: str, direction: str, as_json: bool):
    _, q = _load(cwd)
    graph = q.graph
    nid = _one(graph, symbol)
    node = graph.nodes[nid]
    ids = sorted(node.called_by if direction == "callers" else node.calls)
    label = "called by" if direction == "callers" else "calls"
    lines = [f"{nid}  ({_where(graph, nid)})", f"  {label} ({len(ids)}):"]
    lines += [f"    {i}  ({_where(graph, i)})" for i in ids] or ["    (none found)"]
    notes = []
    if direction == "callers" and node.simple_name == "__init__":
        cls = nid.rsplit(".", 1)[0]
        if cls in graph.nodes:
            via = sorted(graph.nodes[cls].called_by)
            lines.append(f"  constructed by ({len(via)}), i.e. callers of {cls.rsplit('.', 1)[-1]}():")
            lines += [f"    {i}  ({_where(graph, i)})" for i in via] or ["    (none found)"]
    if direction == "callers" and node.simple_name in q.skipped:
        notes.append(f"'{node.simple_name}' has {q.skipped[node.simple_name]} definitions, so calls by that bare "
                     "name elsewhere were not linked; callers through an object may be missing")
    if direction == "callees":
        missing = sorted({c.split(".")[-1] for c in getattr(graph, "raw_calls", {}).get(nid, []) if c.split(".")[-1] in q.skipped})
        if missing:
            notes.append("not linked (too many definitions to guess): " + ", ".join(f"{m} ({q.skipped[m]})" for m in missing))
    lines += [f"Note: {n}." for n in notes]
    _emit({"symbol": nid, "location": _where(graph, nid), direction: [{"id": i, "location": _where(graph, i)} for i in ids],
           "notes": notes}, as_json, lines)


def impact(cwd: Path, symbol: str, depth: int, tests: bool, as_json: bool):
    from ..labyrinth.query import reach, tests_reaching

    _, q = _load(cwd)
    graph = q.graph
    nid = _one(graph, symbol)
    up = reach(graph, [nid], "backward", depth)
    by_depth = {}
    for other, d in up.items():
        by_depth.setdefault(d, []).append(other)
    lines = [f"Impact of {nid} ({_where(graph, nid)}): {len(up)} transitive callers within {depth} hops"]
    lines += [f"  depth {d}: {len(by_depth[d])}" for d in sorted(by_depth)]
    data = {"symbol": nid, "callers": len(up), "by_depth": {d: sorted(v) for d, v in sorted(by_depth.items())}}
    if tests:
        hits = tests_reaching(graph, [nid], depth)
        files = sorted({graph.nodes[t].file for t in hits})
        data.update(tests=hits, test_files=files, full_suite_recommended=not files)
        lines.append(f"Tests that may reach it ({len(hits)} in {len(files)} files):")
        lines += [f"  {f}" for f in files] or ["  (none found: run the full suite)"]
        if files:
            lines.append(f"Run: python -m pytest {' '.join(files)}")
        lines.append(f"Note: {STATIC_NOTE}.")
    _emit(data, as_json, lines)


def path(cwd: Path, source: str, target: str, depth: int, limit: int, as_json: bool):
    _, q = _load(cwd)
    graph = q.graph
    a, b = _one(graph, source), _one(graph, target)
    result = graph.find_paths(a, b, max_depth=depth + 1, max_paths=limit)  # find_paths counts nodes; depth is hops
    paths = sorted(result.paths, key=len)[:limit]
    lines = [f"{len(paths)} call path(s) from {a} to {b}" + (" (shortest first)" if paths else "")]
    for p in paths:
        names = [graph.nodes[x].simple_name for x in p]
        shown = names if len(names) <= 12 else names[:5] + [f"... {len(names) - 10} more ..."] + names[-5:]
        lines.append(f"  ({len(p) - 1} hops) " + " -> ".join(shown))
    if not paths:
        lines.append(f"  none within {depth} hops. Note: {STATIC_NOTE}.")
    _emit({"source": a, "target": b, "paths": paths}, as_json, lines)


def tests_for(cwd: Path, target: str, diff: bool, base: str, depth: int, as_json: bool):
    from ..labyrinth.query import GitError, changed_nodes, convention_tests, nodes_in_file, tests_reaching

    root, q = _load(cwd)
    graph = q.graph
    if diff:
        try:
            touched = changed_nodes(graph, root, base)
        except GitError as e:
            click.echo(f"Can't read the changes: {e}", err=True)
            click.echo("(--diff needs a git repository and a valid --base.)", err=True)
            sys.exit(3)
    else:
        if not target:
            click.echo("Give a file path, or --diff for the working tree's changes.", err=True)
            sys.exit(1)
        p = (Path(cwd) / target).resolve()
        try:
            rel = str(p.relative_to(root.resolve()))
        except ValueError:
            click.echo(f"{target} is outside the project ({root}).", err=True)
            sys.exit(1)
        if not p.exists():
            click.echo(f"{target} does not exist.", err=True)
            sys.exit(1)
        touched = {rel: nodes_in_file(graph, rel)}
    symbols = sorted({n for ids in touched.values() for n in ids})
    hits = tests_reaching(graph, symbols, depth)
    files = sorted({graph.nodes[t].file for t in hits} | set(convention_tests(root, list(touched))))
    lines = [f"Changed: {len(symbols)} symbols in {len(touched)} files" if diff else f"{target}: {len(symbols)} symbols"]
    if files:
        lines += [f"Tests to run ({len(files)} files):"] + [f"  {f}" for f in files]
        lines.append(f"Run: python -m pytest {' '.join(files)}")
    else:
        lines.append("No tests found statically. Run the full suite: python -m pytest")
    lines.append(f"Note: {STATIC_NOTE}.")
    _emit({"files": sorted(touched), "symbols": symbols, "tests": hits, "test_files": files,
           "full_suite_recommended": not files}, as_json, lines)
