"""
Drawing a graph as an Ophanic diagram (edict 0017): the one renderer every `oph map` uses, and `oph draw`.

The input is a graph:
    {"title": str,
     "nodes": [{"id", "label", "kind": "E|P|T|R|W|S|M|C|N", "mark"?, "parent"?, "detail"?}],
     "edges": [{"from", "to", "label"?}]}

How it's drawn, deterministically:
- **Slugs.** Every top-level node gets a slug (`█E13`): its own number when its ID ends in one (edicts),
  otherwise numbered per kind in ascending ID order from 01. A kind with more than 99 nodes is drawn
  legend-only.
- **Containment.** A node with a `parent` is drawn as a line inside its parent's box (`· █T01 [x] title`),
  not as a box of its own.
- **Layers.** An edge `a ─▶ b` means a depends on, or points at, b. A node's layer is the longest path from it to
  a node with no outgoing edges; layer 0 is drawn first (the foundations), and higher layers below it. Within a
  layer, nodes are ordered by ID. Boxes in a layer sit side by side and wrap onto further rows at the width.
- **Edges.** An edge between adjacent layers is *drawn*: an arrow line inside the source's box (`─▶ █E10 █E11`).
  Every other edge (skipping a layer, or within a layer) is *listed* under the diagram (`█E13 ─▶ █E06`). The JSON
  says which is which.
- **Fit.** Labels are cut with `…` to fit their box. If even one box can't fit the width, the whole map is
  legend-only, and says so.
- **Legend.** One line per slug: `█E13: <id> <label>`, so a reader can leave the diagram and find the thing.
- **No colour.** Every state is a text mark (`[done]`, `[>]`).
"""

from __future__ import annotations

import re
from typing import Any, Optional

MIN_BOX = 16
READABLE = 44  # boxes narrower than this truncate most labels: fewer, wider boxes per row


def _fit(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: max(0, n - 1)] + "…"


def assign_slugs(nodes: list[dict]) -> dict[str, str]:
    """{node id: slug} for top-level nodes. Edicts keep their own number; others count up per kind."""
    out: dict[str, str] = {}
    by_kind: dict[str, list[dict]] = {}
    for n in nodes:
        if not n.get("parent"):
            by_kind.setdefault(n.get("kind", "N"), []).append(n)
    for kind, group in by_kind.items():
        group = sorted(group, key=lambda n: str(n["id"]))
        if kind == "E" and all(re.search(r"(\d{1,4})$", str(n["id"])) for n in group):
            for n in group:
                out[n["id"]] = f"█E{int(re.search(r'(\d{1,4})$', str(n['id'])).group(1)):02d}"
            continue
        if len(group) > 99:
            continue
        for i, n in enumerate(group, 1):
            out[n["id"]] = f"█{kind}{i:02d}"
    return out


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
    body = ["│" + (" " + _fit(l, inner - 2)).ljust(inner) + "│" for l in lines]
    return ["┌" + "─" * inner + "┐", *body, "└" + "─" * inner + "┘"]


def draw(graph: dict, width: int = 100) -> tuple[str, dict]:
    """(diagram text, the JSON it was drawn from: nodes with slugs, edges marked drawn or listed)."""
    nodes = list(graph.get("nodes") or [])
    edges = [e for e in graph.get("edges") or [] if e.get("from") != e.get("to")]
    slugs = assign_slugs(nodes)
    top = [n for n in nodes if not n.get("parent") and n["id"] in slugs]
    children: dict[str, list[dict]] = {}
    for n in nodes:
        if n.get("parent"):
            children.setdefault(n["parent"], []).append(n)
    layer = layers(top, edges)
    by_id = {n["id"]: n for n in nodes}

    drawn, listed = [], []
    for e in sorted(edges, key=lambda e: (str(e["from"]), str(e["to"]))):
        a, b = e["from"], e["to"]
        if a in layer and b in layer and layer[a] == layer[b] + 1:
            drawn.append(e)
        elif a in slugs and b in slugs:
            listed.append(e)

    title = graph.get("title", "")
    inner = width - 4  # the whole map sits in one frame: "│ " ... " │"
    ncols = max(1, inner // (MIN_BOX + 2))
    while ncols > 1 and (inner - (ncols - 1) * 2) // ncols < READABLE:
        ncols -= 1
    box_w = (inner - (ncols - 1) * 2) // ncols
    legend_only = box_w < MIN_BOX or not top
    rows: list[str] = []
    if not legend_only:
        if title:
            rows += [_fit(title, inner), ""]
        for li, lvl in enumerate(sorted(set(layer.values()))):
            if li:
                rows.append("")
            row_nodes = sorted([n for n in top if layer[n["id"]] == lvl], key=lambda n: str(n["id"]))
            for start in range(0, len(row_nodes), ncols):
                chunk = row_nodes[start:start + ncols]
                boxes = []
                for n in chunk:
                    lines = [f"{slugs[n['id']]} {n.get('label', n['id'])}"]
                    if n.get("mark"):
                        lines.append(f"[{n['mark']}]")
                    if n.get("detail"):
                        lines.append(str(n["detail"]))
                    for c in sorted(children.get(n["id"], []), key=lambda c: str(c["id"])):
                        mark = f"[{c['mark']}] " if c.get("mark") else ""
                        lines.append(f"· {mark}{c['id']} {c.get('label', '')}".rstrip())
                    targets = [slugs[e["to"]] for e in drawn if e["from"] == n["id"]]
                    per = max(1, (box_w - 7) // 5)
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
    if legend_only:
        text_parts.append(f"{title}\n(The map doesn't fit {width} columns, or is empty; legend only.)".strip())
    else:
        frame = ["┌" + "─" * (width - 2) + "┐"] + ["│ " + r.ljust(inner) + " │" for r in rows] + ["└" + "─" * (width - 2) + "┘"]
        text_parts.append("\n".join(frame))
    after = []
    for e in listed:
        after.append(f"{slugs[e['from']]} ─▶ {slugs[e['to']]}" + (f"  ({e['label']})" if e.get("label") else ""))
    for nid, slug in sorted(slugs.items(), key=lambda kv: kv[1]):
        n = by_id[nid]
        after.append(f"{slug}: {nid} {_fit(n.get('label', ''), width - len(slug) - len(str(nid)) - 4)}".rstrip())
    data = {
        "title": title,
        "nodes": [{**n, "slug": slugs.get(n["id"])} for n in nodes],
        "edges": [{"from": e["from"], "to": e["to"], "state": "drawn"} for e in drawn]
        + [{"from": e["from"], "to": e["to"], "state": "listed"} for e in listed],
        "legend_only": legend_only,
    }
    return "\n".join(text_parts + after) + "\n", data


def read_edges(text: str) -> list[dict[str, Any]]:
    """The edges a diagram's text shows, read independently of any renderer: `─▶ █X01 ...` lines inside a box
    give drawn edges from that box's first slug; `█X01 ─▶ █X02` lines outside boxes give listed edges.
    Returned as slugs."""
    out: list[dict[str, Any]] = []
    lines = text.splitlines()
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
            owner = next((m.group(0) for line in contents for m in [re.match(r"█[A-Z]\d{2,4}", line)] if m), None)
            if owner is None:
                continue
            for line in contents:
                if line.startswith("─▶"):
                    for t in re.findall(r"█[A-Z]\d{2,4}", line):
                        out.append({"from": owner, "to": t, "state": "drawn"})
    for line in lines:
        m = re.match(r"^(█[A-Z]\d{2,4}) ─▶ (█[A-Z]\d{2,4})", line)
        if m:
            out.append({"from": m.group(1), "to": m.group(2), "state": "listed"})
    return out
