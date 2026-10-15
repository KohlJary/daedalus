"""
Drawing a graph as an Ophanic diagram (edict 0017): the one renderer every `oph map` uses, and `oph draw`.

The input is a graph:
    {"title": str,
     "nodes": [{"id", "label", "kind": "E|P|T|R|W|S|M|C|N", "mark"?, "parent"?, "detail"?}],
     "edges": [{"from", "to", "label"?}]}

How it's drawn, deterministically:
- **Slugs.** Every top-level node gets a slug (`█E13`): its own number when its ID ends in one (edicts),
  otherwise numbered per kind in ascending ID order from 01. A kind with more than 99 nodes is numbered with three
  digits (`█T001`), more than 999 with four, so nothing vanishes.
- **Duplicates.** Two nodes with the same ID, or two edicts with the same number, can't share a slug: the later one
  gets the next free number of its kind, and a `note:` under the map says so.
- **Containment.** A node with a `parent` is drawn as a line inside its parent's box (`· █T01 [x] title`),
  not as a box of its own. A child whose ID starts with `~` is a placeholder line: its ID isn't printed.
- **Layers.** An edge `a ─▶ b` means a depends on, or points at, b. A node's layer is the longest path from it to
  a node with no outgoing edges; layer 0 is drawn first (the foundations), and higher layers below it. Within a
  layer, nodes are ordered by ID. Boxes in a layer sit side by side and wrap onto further rows at the width.
- **Edges.** An edge between adjacent layers is *drawn*: an arrow line inside the source's box (`─▶ █E10 █E11`).
  Every other edge (skipping a layer, or within a layer) is *listed* under the diagram (`█E13 ─▶ █E06`). The JSON
  says which is which. An edge to or from a node that isn't in the graph, and a child whose parent isn't, are
  listed as `missing: ...` lines: never dropped.
- **Fit.** Labels are cut with `…` to fit their box, by display width (a wide character takes two columns). If even
  one box can't fit the width, the whole map is legend-only, and says so; an empty graph says it's empty.
- **Text is text.** Box characters, arrows, `◆` and `█` in labels are replaced (`|`, `-`, `+`, `>`, `◇`, `#`), so a
  label can't draw a line, name a component or forge a slug, and every map passes `oph check`.
- **Legend.** One line per slug: `█E13: <id> <label>`, so a reader can leave the diagram and find the thing.
- **No colour.** Every state is a text mark (`[done]`, `[>]`).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .lint import ARMS, width

MIN_BOX = 16
READABLE = 44  # boxes narrower than this truncate most labels: fewer, wider boxes per row


class GraphError(ValueError):
    """A graph `draw` can't read: not an object, or a node or edge missing a field."""


def _clean_char(ch: str) -> str:
    if ch in "▶": return ">"
    if ch in "◀": return "<"
    if ch in "▼": return "v"
    if ch in "▲": return "^"
    if ch == "█": return "#"
    if ch == "◆": return "◇"
    arms = ARMS.get(ch)
    if not arms:
        return ch
    if arms <= {"L", "R"}: return "-"
    if arms <= {"U", "D"}: return "|"
    return "+"


def clean(text: Any) -> str:
    """One line of label text, with nothing in it that the lint would read as drawing."""
    return "".join(_clean_char(ch) for ch in " ".join(str(text).split()))


def _fit(text: Any, n: int) -> str:
    """Cut text to n display columns with `…`. Text from a graph is cleaned first (`clean`); this doesn't."""
    text = " ".join(str(text).split())
    if width(text) <= n:
        return text
    out = ""
    for ch in text:
        if width(out + ch) > n - 1:
            break
        out += ch
    return out + "…" if n > 0 else ""


def _pad(text: str, n: int) -> str:
    return text + " " * max(0, n - width(text))


def validate(graph: Any) -> None:
    """Raise GraphError for a graph `draw` can't read."""
    if not isinstance(graph, dict):
        raise GraphError("the graph must be a JSON object with nodes and edges")
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise GraphError("nodes and edges must be lists")
    for k, n in enumerate(nodes):
        if not isinstance(n, dict) or n.get("id") in (None, ""):
            raise GraphError(f"node {k} has no id")
    for k, e in enumerate(edges):
        if not isinstance(e, dict) or e.get("from") in (None, "") or e.get("to") in (None, ""):
            raise GraphError(f"edge {k} needs both from and to")


def _dedupe(nodes: list[dict]) -> tuple[list[dict], list[str]]:
    """Nodes with unique IDs (a repeated ID gets ` (2)`, ` (3)` ...), and a note for each repeat."""
    seen: dict[str, int] = {}
    out, notes = [], []
    for n in nodes:
        n = {**n, "id": n["id"] if isinstance(n["id"], str) else str(n["id"])}
        if n.get("parent") is not None:
            n["parent"] = str(n["parent"])
        k = seen.get(n["id"], 0) + 1
        seen[n["id"]] = k
        if k > 1:
            notes.append(f"duplicate id {n['id']}: drawn {k} times")
            n["id"] = f"{n['id']} ({k})"
        out.append(n)
    return out, notes


def assign_slugs(nodes: list[dict]) -> tuple[dict[str, str], list[str]]:
    """({node id: slug} for top-level nodes, notes on slugs that had to move). Edicts keep their own number;
    others count up per kind, with as many digits as the kind needs (two, three or four)."""
    out: dict[str, str] = {}
    notes: list[str] = []
    by_kind: dict[str, list[dict]] = {}
    for n in nodes:
        if not n.get("parent"):
            by_kind.setdefault(clean(n.get("kind") or "N")[:1].upper() or "N", []).append(n)
    for kind, group in sorted(by_kind.items()):
        if not ("A" <= kind <= "Z"):
            kind = "N"
        group = sorted(group, key=lambda n: str(n["id"]))
        digits = 2 if len(group) <= 99 else 3 if len(group) <= 999 else 4
        own = kind == "E" and all(re.search(r"(\d{1,4})(?: \(\d+\))?$", str(n["id"])) for n in group)
        if own:
            taken: set[int] = set()
            moved = []
            for n in group:
                num = int(re.search(r"(\d{1,4})(?: \(\d+\))?$", str(n["id"])).group(1))
                if num in taken:
                    moved.append(n)
                    continue
                taken.add(num)
                out[n["id"]] = f"█E{num:02d}"
            for n in moved:
                num = max(taken) + 1
                taken.add(num)
                out[n["id"]] = f"█E{num:02d}"
                notes.append(f"{n['id']} shares its number with another node; drawn as {out[n['id']]}")
            continue
        for i, n in enumerate(group, 1):
            out[n["id"]] = f"█{kind}{i:0{digits}d}"
    return out, notes


def layers(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """Longest path to a sink, for top-level nodes. Cycles are broken by ID order."""
    ids = [n["id"] for n in nodes if not n.get("parent")]
    out_edges: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        if e["from"] in out_edges and e["to"] in out_edges and e["from"] != e["to"]:
            out_edges[e["from"]].append(e["to"])
    memo: dict[str, int] = {}

    def depth(n: str, seen: frozenset) -> int:
        if n in memo:
            return memo[n]
        if n in seen:
            return 0
        d = 0
        for t in sorted(out_edges[n]):
            d = max(d, 1 + depth(t, seen | {n}))
        memo[n] = d
        return d

    return {i: depth(i, frozenset()) for i in sorted(ids)}


def _box(lines: list[str], w: int) -> list[str]:
    inner = w - 2
    body = ["│" + _pad(" " + _fit(l, inner - 2), inner) + "│" for l in lines]
    return ["┌" + "─" * inner + "┐", *body, "└" + "─" * inner + "┘"]


def draw(graph: dict, width: int = 100, max_columns: Optional[int] = None) -> tuple[str, dict]:
    """(diagram text, the JSON it was drawn from: nodes with slugs, edges marked drawn or listed). `max_columns`
    caps the boxes side by side (the TUI's send form uses 1, so boxes are full width and cut fewer labels)."""
    validate(graph)
    nodes, notes = _dedupe(list(graph.get("nodes") or []))
    edges = [{**e, "from": str(e["from"]), "to": str(e["to"])} for e in graph.get("edges") or []
             if str(e.get("from")) != str(e.get("to"))]
    slugs, slug_notes = assign_slugs(nodes)
    notes += slug_notes
    top = [n for n in nodes if not n.get("parent") and n["id"] in slugs]
    children: dict[str, list[dict]] = {}
    missing: list[str] = []
    for n in nodes:
        if n.get("parent"):
            if n["parent"] in slugs:
                children.setdefault(n["parent"], []).append(n)
            else:
                missing.append(f"missing: {clean(n['id'])} is inside {clean(n['parent'])}, which isn't in the graph")
    layer = layers(top, edges)
    by_id = {n["id"]: n for n in nodes}

    drawn, listed = [], []
    for e in sorted(edges, key=lambda e: (e["from"], e["to"])):
        a, b = e["from"], e["to"]
        if a in layer and b in layer and layer[a] == layer[b] + 1:
            drawn.append(e)
        elif a in slugs and b in slugs:
            listed.append(e)
        else:
            gone = [x for x in (a, b) if x not in slugs]
            why = ", ".join(f"no node {clean(x)}" if x not in by_id else f"{clean(x)} is a child, not a box"
                            for x in gone)
            missing.append(f"missing: {clean(a)} ─▶ {clean(b)} ({why})")

    title = graph.get("title", "")
    inner = width - 4  # the whole map sits in one frame: "│ " ... " │"
    ncols = max(1, inner // (MIN_BOX + 2))
    while ncols > 1 and (inner - (ncols - 1) * 2) // ncols < READABLE:
        ncols -= 1
    if max_columns:
        ncols = max(1, min(ncols, max_columns))
    box_w = (inner - (ncols - 1) * 2) // ncols
    legend_only = box_w < MIN_BOX or not top
    rows: list[str] = []
    if not legend_only:
        if title:
            rows += [_fit(clean(title), inner), ""]
        for li, lvl in enumerate(sorted(set(layer.values()))):
            if li:
                rows.append("")
            row_nodes = sorted([n for n in top if layer[n["id"]] == lvl], key=lambda n: str(n["id"]))
            for start in range(0, len(row_nodes), ncols):
                chunk = row_nodes[start:start + ncols]
                boxes = []
                for n in chunk:
                    lines = [f"{slugs[n['id']]} {clean(n.get('label', n['id']))}"]
                    if n.get("mark"):
                        lines.append(clean(f"[{n['mark']}]"))
                    if n.get("detail"):
                        lines.append(clean(n["detail"]))
                    for c in sorted(children.get(n["id"], []), key=lambda c: str(c["id"])):
                        mark = f"[{c['mark']}] " if c.get("mark") else ""
                        cid = "" if c["id"].startswith("~") else f"{c['id']} "
                        lines.append(clean(f"· {mark}{cid}{c.get('label', '')}".rstrip()))
                    targets = [slugs[e["to"]] for e in drawn if e["from"] == n["id"]]
                    per = max(1, (box_w - 7) // 6)
                    for i in range(0, len(targets), per):
                        lines.append("─▶ " + " ".join(targets[i:i + per]))
                    boxes.append(_box(lines, box_w))
                height = max(len(bx) for bx in boxes)
                for bx in boxes:
                    while len(bx) < height:
                        bx.insert(len(bx) - 1, "│" + " " * (box_w - 2) + "│")
                for r in range(height):
                    rows.append("  ".join(bx[r] for bx in boxes))
    text_parts = []
    if not top:
        text_parts.append(f"{_fit(clean(title), width)}\n(Nothing to map: the graph has no nodes.)".strip())
    elif legend_only:
        text_parts.append(f"{_fit(clean(title), width)}\n(The map doesn't fit {width} columns; legend only.)".strip())
    else:
        frame = ["┌" + "─" * (width - 2) + "┐"] + ["│ " + _pad(r, inner) + " │" for r in rows] + ["└" + "─" * (width - 2) + "┘"]
        text_parts.append("\n".join(frame))
    after = [f"note: {clean(n)}" for n in notes]
    for e in listed:
        after.append(f"{slugs[e['from']]} ─▶ {slugs[e['to']]}" + (f"  ({clean(e['label'])})" if e.get("label") else ""))
    after += missing
    for nid, slug in sorted(slugs.items(), key=lambda kv: kv[1]):
        n = by_id[nid]
        after.append(f"{slug}: {clean(nid)} {_fit(clean(n.get('label', '')), width - len(slug) - width_of(nid) - 4)}".rstrip())
    data = {
        "title": title,
        "nodes": [{**n, "slug": slugs.get(n["id"])} for n in nodes],
        "edges": [{"from": e["from"], "to": e["to"], "state": "drawn"} for e in drawn]
        + [{"from": e["from"], "to": e["to"], "state": "listed"} for e in listed],
        "missing": missing,
        "notes": notes,
        "legend_only": legend_only,
    }
    return "\n".join(text_parts + after) + "\n", data


def width_of(text: Any) -> int:
    return width(clean(text))


_SLUG = r"█[A-Z]\d{1,4}"
_H = "─━═┄┈╌┅┉╍"
_V = "│┃║├┤┣┫╠╣┆┊╎┇┋╏"
# A side-attached edge: a box side, a run of line (slugs allowed inside it), an arrow, the other box's side
_SIDE_EDGE = re.compile(rf"(?<=[{_V}])((?:[{_H}]|{_SLUG})*)([▶◀])((?:[{_H}]|{_SLUG})*)(?=[{_V}])")


def _owner(grid: list[str], r: int, c: int, step: int) -> Optional[str]:
    """The first slug inside the box whose side is at (r, c), on the side `step` points to (+1 right, -1 left)."""
    def at(rr, cc):
        return grid[rr][cc] if 0 <= rr < len(grid) and 0 <= cc < len(grid[rr]) else " "
    far = c + step
    while 0 <= far < len(grid[r]) and at(r, far) not in _V:
        far += step
    lo, hi = sorted((c, far))
    top = r
    while at(top - 1, c) in _V:
        top -= 1
    bottom = r
    while at(bottom + 1, c) in _V:
        bottom += 1
    for rr in range(top, bottom + 1):
        m = re.search(_SLUG, grid[rr][lo + 1:hi] if rr < len(grid) else "")
        if m:
            return m.group(0)
    return None


def read_edges(text: str) -> list[dict[str, Any]]:
    """The edges one diagram's text shows, read independently of any renderer. Returned as slugs:
    - `─▶ █X01 ...` lines inside a box give drawn edges from that box's first slug (the renderer's form);
    - a run attached to two boxes' sides (`│─█R11─▶│`, `│──────▶│`, `│◀─────│`) gives a drawn edge between the
      boxes' first slugs (None for a box with no slug), with the slug inside the run, if any, as its `via`;
    - `█X01 ─▶ █X02` lines outside boxes give listed edges."""
    from .lint import columns

    out: list[dict[str, Any]] = []
    lines = [columns(l) for l in text.splitlines()]
    # Boxes: find each ┌ and trace its rectangle
    grid = [list(l) for l in lines]

    def at(r, c):
        return grid[r][c] if 0 <= r < len(grid) and 0 <= c < len(grid[r]) else " "

    for r, row in enumerate(grid):
        for c, ch in enumerate(row):
            if ch != "┌":
                continue
            c2 = c + 1
            while c2 < len(row) and row[c2] == "─":
                c2 += 1
            if at(r, c2) != "┐":
                continue
            r2 = r + 1
            while r2 < len(grid) and at(r2, c) == "│":
                r2 += 1
            if at(r2, c) != "└":
                continue
            contents = ["".join(grid[k][c + 1:c2]).strip() for k in range(r + 1, r2)]
            owner = next((m.group(0) for line in contents for m in [re.match(_SLUG, line)] if m), None)
            if owner is None:
                continue
            for line in contents:
                if line.startswith("─▶"):
                    for t in re.findall(_SLUG, line):
                        out.append({"from": owner, "to": t, "state": "drawn"})
    for r, line in enumerate(lines):
        for m in _SIDE_EDGE.finditer(line):
            if not (m.group(1) or m.group(3)) or (m.group(2) == "▶" and m.group(3)) or (m.group(2) == "◀" and m.group(1)):
                continue  # the arrow ends the run: "─▶│" or "│◀─"
            left = _owner(lines, r, m.start() - 1, -1)
            right = _owner(lines, r, m.end(), +1)
            a, b = (left, right) if m.group(2) == "▶" else (right, left)
            via = re.search(_SLUG, m.group(0))
            edge = {"from": a, "to": b, "state": "drawn"}
            if via:
                edge["via"] = via.group(0)
            out.append(edge)
    for line in lines:
        m = re.match(rf"^({_SLUG}) ─▶ ({_SLUG})", line)
        if m:
            out.append({"from": m.group(1), "to": m.group(2), "state": "listed"})
    return out


def read_diagram_edges(text: str, markdown: bool = False) -> list[dict[str, Any]]:
    """Edges per diagram, so the same slugs in two `@variant`s don't merge: one entry per diagram, with its first
    line, its variant (the nearest `@name` line above it, if any) and the edges `read_edges` finds in it."""
    from .lint import diagrams

    lines = text.splitlines()
    out = []
    for d in diagrams(text, markdown=markdown):
        variant = next((lines[k].strip()[1:].split()[0] for k in range(d.start - 2, -1, -1)
                        if re.match(r"^@[A-Za-z]", lines[k].strip())), None)
        out.append({"line": d.start, "variant": variant, "edges": read_edges("\n".join(d.rows + d.after))})
    return out
