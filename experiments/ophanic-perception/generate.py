#!/usr/bin/env python3
"""
generate.py: deterministic task generator for the Ophanic perception experiment (see DESIGN.md).

    python generate.py --seed 5016 [--per-cell 10] [--out tasks] [--harness 2]

For each structure type (layout, graph, containment) and size (small, medium, large) it makes
`--per-cell` structures. Each structure carries:
- `data`: the generator's own data (the `json` encoding is exactly this, indented);
- `encodings`: ophanic@100, ophanic@60, ophanic-noise@100, ophanic-noise@60, prose, json, list (and, from harness 2,
  json-compact);
- `questions`: one per question kind for the type, each with its gold answer and answer type.

`--harness 1` reproduces pilot 1's tasks byte for byte and `--harness 2` pilot 2's. Harness 2 implements DESIGN.md's
proposed amendments: layouts state character widths instead of percentages in the text arms (A1), and the graph's
aggregate question is "how many nodes have no incoming edge" (A2). Harness 3 (the default) adds, for layouts, the
`list-lookup` control arm with the share stated as a percentage (A12) and records `share_pair`, the ophanic arm
whose drawn widths the text arms state. The prompt framing (A3, A13) is in `build_prompt`.

Everything comes from `random.Random("<seed>:<type>:<size>:<i>")`, so the same seed gives the same file.
Every clean ophanic diagram must pass the Ophanic lint (oph_lint.py); every noisy one must fail it with
exactly a width and a joins finding. Anything else raises HarnessBug.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import deque
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import oph_lint  # noqa: E402

TYPES = ("layout", "graph", "containment")
SIZES = {"small": (5, 8), "medium": (15, 25), "large": (40, 60)}
WIDTHS = (100, 60)
EDGE_LABELS = ("needs", "calls", "feeds", "extends")
INSTRUCTION = "Answer with only the answer."
HARNESS = 3          # the default task format; 1 is pilot 1's, 2 is pilot 2's
PROPORTION_WIDTH = 60  # harness 2+: the text arms state widths from the 60-column drawing (span 59, not 100)
# The ophanic arm whose drawn widths the text arms state: H1b pairs the text arms with this one (Momus, pilot 2)
SHARE_PAIR = f"ophanic@{PROPORTION_WIDTH}"
# Harness 3 (A12): a lookup-ceiling control for the share question, the list with the percentage stated
LOOKUP_ARM = "list-lookup"

LAYOUT_NAMES = """Header Footer Sidebar Nav Search Logo Menu Tabs Toolbar Status Editor Preview Console
Inbox Profile Avatar Badge Cart Filter Map Legend Chart Table Log Help Alerts Notes Calendar Tasks Files
Tree Outline Minimap Terminal Output Debug Crumbs Pager Ads Banner Hero Gallery Video Player Queue Lyrics
Comments Likes Share Stats Metrics Clock Weather News Ticker Settings Account Billing Usage Keys Team
Invite Upload Export Palette Layers Canvas Zoom Ruler History Bookmarks Friends Feed Chat Trends Events
Photos Music Mail Drafts Archive Trash Labels Contacts Timer Detail Summary Actions""".split()
GRAPH_NAMES = """Auth Store Cache Queue Router Parser Lexer Indexer Crawler Mailer Billing Ledger Search
Ranker Scorer Loader Fetcher Planner Worker Gateway Proxy Config Logger Metrics Tracer Alerter Scheduler
Builder Linter Tester Packer Deployer Monitor Backup Mirror Sync Notifier Session Profile Upload Thumbs
Encoder Decoder Archive Exporter Importer Reports Audit Policy Vault Secrets Keyring Tokens Ingest
Cleaner Joiner Splitter Sampler Labeler Trainer Embedder Reranker Webhook Cron Resolver Shard Replica
Compactor""".split()
GROUP_NAMES = """Alpha Beta Gamma Delta Omega Atlas Orion Vega Lyra Nova Apex Zenith Harbor Summit Cedar
Maple Willow Aspen Birch Falcon Heron Kestrel""".split()
ITEM_NAMES = """apple anchor bolt cable comet dune flint grove hinge iris jade kelp lantern marble nectar
opal pebble quartz reed saffron thistle umber velvet wick yarrow zinc acorn basil clover dahlia fennel
ginger hazel ivy juniper kale lilac mint nutmeg olive pepper quince rhubarb sage tansy vanilla walnut
barley cumin dill fig lemon mango pear plum rye sorrel thyme yam lotus fern moss cactus orchid""".split()

for _pool in (LAYOUT_NAMES, GRAPH_NAMES, GROUP_NAMES, ITEM_NAMES):
    assert len(set(_pool)) == len(_pool), "duplicate name in a pool"
assert not {n.lower() for n in GROUP_NAMES} & {n.lower() for n in ITEM_NAMES}

ARM_CHAR = {frozenset("LR"): "─", frozenset("UD"): "│", frozenset("RD"): "┌", frozenset("LD"): "┐",
            frozenset("RU"): "└", frozenset("LU"): "┘", frozenset("UDR"): "├", frozenset("UDL"): "┤",
            frozenset("LRD"): "┬", frozenset("LRU"): "┴", frozenset("UDLR"): "┼"}


# Seeds (README, "Seeds"): never reuse one between a pilot and a confirmatory run
RESERVED_PAST = {1015: "pilot 1", 99001: "tests", 5016: "pilot 2"}
CONFIRMATORY_SEEDS = (2000, 2999)   # reserved for confirmatory runs; no pilot or test uses them


class HarnessBug(Exception):
    pass


class Reject(Exception):
    """This draw of a structure can't be used (undrawable, or a question kind has no candidate): redraw."""


def oxford(names: list[str]) -> str:
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def spread(rng: random.Random, n: int, k: int) -> list[int]:
    """n split into k positive parts of roughly equal size."""
    parts = [1] * k
    for _ in range(n - k):
        parts[rng.randrange(k)] += 1
    return parts


def partition(rng: random.Random, n: int, k: int) -> list[int]:
    cuts = sorted(rng.sample(range(1, n), k - 1))
    return [b - a for a, b in zip([0] + cuts, cuts + [n])]


# ---------------------------------------------------------------------------------------------------------
# Layout: nested rows and columns with proportions, drawn in the shared-divider style
# ---------------------------------------------------------------------------------------------------------
# A node is {"panel": name}, {"rows": [node, ...]} (top to bottom) or {"columns": [node, ...]} (left to
# right). A child of "columns" also carries "share": its percentage of the row's width.

MIN_LEAF = 8   # characters, border to border, at width 60


def build_layout(rng, n, kind, depth):
    if n == 1:
        return {"panel": None}
    if kind == "rows":
        k = max(2, min(n, round(n / rng.uniform(3.0, 5.0)))) if depth == 0 else rng.randint(2, min(n, 3))
        return {"rows": [build_layout(rng, p, "columns", depth + 1) for p in partition(rng, n, k)]}
    k = rng.randint(2, min(n, 5 if depth == 1 else 3))
    return {"columns": [build_layout(rng, p, "rows", depth + 1) for p in partition(rng, n, k)]}


def min_span(node):
    if "panel" in node:
        return MIN_LEAF
    if "rows" in node:
        return max(min_span(c) for c in node["rows"])
    return sum(min_span(c) for c in node["columns"])


def assign_shares(rng, node, span):
    if "panel" in node:
        return span >= MIN_LEAF
    if "rows" in node:
        return all(assign_shares(rng, c, span) for c in node["rows"])
    cols = node["columns"]
    shares = [max(10, 5 * math.ceil(100 * (min_span(c) + 1) / span / 5)) for c in cols]
    if sum(shares) > 100:
        return False
    for _ in range((100 - sum(shares)) // 5):
        shares[rng.randrange(len(cols))] += 5
    for c, s in zip(cols, shares):
        c["share"] = s
    return all(assign_shares(rng, c, s * span // 100) for c, s in zip(cols, shares))


def leaves(node):
    if "panel" in node:
        return [node]
    return [x for c in node.get("rows", node.get("columns")) for x in leaves(c)]


def height(node):
    if "panel" in node:
        return 2
    if "rows" in node:
        return sum(height(c) for c in node["rows"])
    return max(height(c) for c in node["columns"])


def ordered(node):
    """The node as JSON with keys in reading order (share first)."""
    out = {}
    if "share" in node:
        out["share"] = node["share"]
    if "panel" in node:
        out["panel"] = node["panel"]
    elif "rows" in node:
        out["rows"] = [ordered(c) for c in node["rows"]]
    else:
        out["columns"] = [ordered(c) for c in node["columns"]]
    return out


def node_spans(root, W):
    """Border-to-border width of every node at diagram width W, with place_layout's arithmetic: {id(node): span}."""
    spans = {}

    def go(node, x0, x1):
        spans[id(node)] = x1 - x0
        if "panel" in node:
            return
        if "rows" in node:
            for c in node["rows"]:
                go(c, x0, x1)
            return
        cum, px = 0, x0
        for i, c in enumerate(node["columns"]):
            cum += c["share"]
            nx = x1 if i == len(node["columns"]) - 1 else x0 + round(Fraction(cum, 100) * (x1 - x0))
            go(c, px, nx)
            px = nx
    go(root, 0, W - 1)
    return spans


def ordered_widths(node, spans, in_columns=False):
    """Harness 2's layout data: like ordered(), but a column and a set of columns carry "width" (characters,
    border to border, at PROPORTION_WIDTH) instead of a percentage "share". A column's share of its row is its
    width over the width of the columns node holding it."""
    out = {}
    if in_columns or "columns" in node:
        out["width"] = spans[id(node)]
    if "panel" in node:
        out["panel"] = node["panel"]
    elif "rows" in node:
        out["rows"] = [ordered_widths(c, spans) for c in node["rows"]]
    else:
        out["columns"] = [ordered_widths(c, spans, True) for c in node["columns"]]
    return out


def place_layout(root, W):
    """Leaf rectangles: fractional x (fx0, fx1, in [0,1]), drawn x (x0, x1, border columns) and y (rows)."""
    rects, drawn_share = {}, {}

    def go(node, fx0, fx1, x0, x1, y0, y1):
        if "panel" in node:
            rects[node["panel"]] = dict(fx0=fx0, fx1=fx1, x0=x0, x1=x1, y0=y0, y1=y1)
            return
        if "rows" in node:
            y = y0
            for i, c in enumerate(node["rows"]):
                ny = y1 if i == len(node["rows"]) - 1 else y + height(c)
                go(c, fx0, fx1, x0, x1, y, ny)
                y = ny
            return
        cum, px, pf = 0, x0, fx0
        for i, c in enumerate(node["columns"]):
            cum += c["share"]
            nf = fx0 + (fx1 - fx0) * Fraction(cum, 100)
            nx = x1 if i == len(node["columns"]) - 1 else x0 + round(Fraction(cum, 100) * (x1 - x0))
            if nx - px < 3:
                raise Reject("column collapsed")
            if "panel" in c:
                drawn_share[c["panel"]] = 100 * (nx - px) / (x1 - x0)
            go(c, pf, nf, px, nx, y0, y1)
            pf, px = nf, nx

    go(root, Fraction(0), Fraction(1), 0, W - 1, 0, height(root))
    return rects, drawn_share


def render_layout(root, W):
    rects, _ = place_layout(root, W)
    H = height(root)
    hs, vs = set(), set()
    for r in rects.values():
        for x in range(r["x0"], r["x1"]):
            hs.add((r["y0"], x))
            hs.add((r["y1"], x))
        for y in range(r["y0"], r["y1"]):
            vs.add((y, r["x0"]))
            vs.add((y, r["x1"]))
    grid = [[" "] * W for _ in range(H + 1)]
    for y in range(H + 1):
        for x in range(W):
            arms = {a for a, on in (("L", (y, x - 1) in hs), ("R", (y, x) in hs),
                                    ("U", (y - 1, x) in vs), ("D", (y, x) in vs)) if on}
            if arms:
                grid[y][x] = ARM_CHAR[frozenset(arms)]
    notes = []
    for name, r in rects.items():
        room = r["x1"] - r["x0"] - 3
        label = name
        if len(name) > room:
            if room < 3:
                raise Reject("no room for a label")
            label = name[:room - 1] + "…"
            notes.append(f"note: {label} = {name}")
        for k, ch in enumerate(label):
            grid[r["y0"] + 1][r["x0"] + 2 + k] = ch
    abbrevs = [n.split(" = ")[0][6:] for n in notes]
    if len(set(abbrevs)) != len(abbrevs):
        raise Reject("two abbreviations collide")
    return ["".join(row) for row in grid], sorted(notes)


def layout_index(root):
    parent = {}

    def go(node, p, i):
        parent[id(node)] = (p, i)
        for j, c in enumerate(node.get("rows", node.get("columns", []))):
            go(c, node, j)
    go(root, None, None)
    return parent


def top_leaves(node):
    if "panel" in node:
        return [node]
    if "rows" in node:
        return top_leaves(node["rows"][0])
    return [x for c in node["columns"] for x in top_leaves(c)]


def layout_right_of(root, parent, leaf):
    cur = leaf
    while True:
        p, i = parent[id(cur)]
        if p is None:
            return None
        if "columns" in p and i < len(p["columns"]) - 1:
            sib = p["columns"][i + 1]
            return sib["panel"] if "panel" in sib else None
        cur = p


def layout_below(root, parent, leaf, rect_sets):
    """The unique panel whose top touches leaf's bottom, overlapping it, in the abstract and in every drawing."""
    cur = leaf
    while True:
        p, i = parent[id(cur)]
        if p is None:
            return None
        if "rows" in p and i < len(p["rows"]) - 1:
            cands = [t["panel"] for t in top_leaves(p["rows"][i + 1])]
            answers = []
            for rects, drawn in rect_sets:
                me = rects[leaf["panel"]]
                if drawn:
                    hit = [c for c in cands if min(me["x1"], rects[c]["x1"]) - max(me["x0"], rects[c]["x0"]) >= 2]
                else:
                    hit = [c for c in cands if min(me["fx1"], rects[c]["fx1"]) > max(me["fx0"], rects[c]["fx0"])]
                answers.append(tuple(hit))
            if len(set(answers)) == 1 and len(answers[0]) == 1:
                return answers[0][0]
            return None
        cur = p


def make_layout(rng, n, harness=HARNESS):
    for _ in range(400):
        root = {"rows": build_layout(rng, n, "rows", 0)["rows"]}
        if not assign_shares(rng, root, 59):
            continue
        names = rng.sample(LAYOUT_NAMES, n)
        for leaf, name in zip(leaves(root), names):
            leaf["panel"] = name
        try:
            drawings = {W: render_layout(root, W) for W in WIDTHS}
            placed = {W: place_layout(root, W) for W in WIDTHS}
        except Reject:
            continue
        parent = layout_index(root)
        rect_sets = [(placed[100][0], False)] + [(placed[W][0], True) for W in WIDTHS]
        right, below, prop = [], [], []
        for leaf in leaves(root):
            name = leaf["panel"]
            r = layout_right_of(root, parent, leaf)
            if r:
                right.append((name, r))
            b = layout_below(root, parent, leaf, rect_sets)
            if b:
                below.append((name, b))
            p, _ = parent[id(leaf)]
            if p is not None and "columns" in p:
                if all(abs(placed[W][1][name] - leaf["share"]) <= 2.5 for W in WIDTHS):
                    prop.append((name, leaf["share"]))
        if not (right and below and prop):
            continue
        x, y = rng.choice(right)
        qs = [q("spatial", "right_of", f"Which panel is directly to the right of {x}?", y, "name", x=x)]
        x, y = rng.choice(below)
        qs.append(q("spatial", "below", f"Which panel is directly below {x}?", y, "name", x=x))
        x, s = rng.choice(prop)
        qs.append(q("proportion", "share", f"What percentage of its row's width does {x} take up? Answer with a "
                    f"number.", s, "percent", x=x))
        data = ordered(root) if harness == 1 else ordered_widths(root, node_spans(root, PROPORTION_WIDTH))
        return data, drawings, qs, len(leaves(root)), ordered(root)
    raise HarnessBug("could not draw a layout in 400 tries")


def layout_prose(data):
    out = [f"The screen is split into {len(data['rows'])} rows, top to bottom."]

    def size(c, total):
        if "share" in c:
            return f"{c['share']}% of the row's width"
        return f"{c['width']} of the row's {total} characters"

    def describe(node, label):
        if "panel" in node:
            out.append(f"{label} is the {node['panel']} panel, at full width.")
        elif "columns" in node:
            total = node.get("width")
            parts = [f"{c['panel']} ({size(c, total)})" if "panel" in c
                     else f"column {j} ({size(c, total)})" for j, c in enumerate(node["columns"], 1)]
            wide = f", {total} characters wide in all" if total is not None else ""
            out.append(f"{label} is split into {len(parts)} columns, left to right{wide}: {oxford(parts)}.")
            for j, c in enumerate(node["columns"], 1):
                if "panel" not in c:
                    describe(c, f"{label}, column {j}")
        else:
            parts = [f"{c['panel']}" if "panel" in c else f"row {j}" for j, c in enumerate(node["rows"], 1)]
            out.append(f"{label} is split into {len(parts)} rows, top to bottom: {oxford(parts)}.")
            for j, c in enumerate(node["rows"], 1):
                if "panel" not in c:
                    describe(c, f"{label}, row {j}")

    for i, row in enumerate(data["rows"], 1):
        describe(row, f"Row {i}")
    return " ".join(out)


def layout_list(data):
    out = ["- screen: rows, top to bottom"]

    def go(node, label, depth, total=None):
        pad = "  " * depth
        if "share" in node:
            share = f": {node['share']}%"
        elif total is not None:
            share = f": {node['width']} of {total} characters"
        else:
            share = ""
        if "panel" in node:
            out.append(f"{pad}- {node['panel']}{share}")
        elif "rows" in node:
            out.append(f"{pad}- {label}{share}, rows, top to bottom")
            for j, c in enumerate(node["rows"], 1):
                go(c, f"row {j}", depth + 1)
        else:
            wide = f", {node['width']} characters wide" if "width" in node and total is None else ""
            out.append(f"{pad}- {label}{share}, columns, left to right{wide}")
            for j, c in enumerate(node["columns"], 1):
                go(c, f"column {j}", depth + 1, node.get("width"))

    for j, row in enumerate(data["rows"], 1):
        go(row, f"row {j}", 1)
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------
# Graph: a layered DAG with labelled edges, drawn left to right
# ---------------------------------------------------------------------------------------------------------

def graph_layers(data):
    nodes = data["nodes"]
    preds = {n: [] for n in nodes}
    for e in data["edges"]:
        preds[e["to"]].append(e["from"])
    layer = {}

    def lay(n):
        if n not in layer:
            layer[n] = 1 + max((lay(p) for p in preds[n]), default=-1)
        return layer[n]
    for n in nodes:
        lay(n)
    return layer


def distances(data):
    succ = {n: [] for n in data["nodes"]}
    for e in data["edges"]:
        succ[e["from"]].append(e["to"])
    dist = {}
    for s in data["nodes"]:
        d = {s: 0}
        qd = deque([s])
        while qd:
            u = qd.popleft()
            for v in succ[u]:
                if v not in d:
                    d[v] = d[u] + 1
                    qd.append(v)
        dist[s] = d
    return dist


def draw_graph(data, W):
    nodes = data["nodes"]
    idx = {n: i for i, n in enumerate(nodes)}
    layer = graph_layers(data)
    L = max(layer.values()) + 1
    by_layer = [[n for n in nodes if layer[n] == k] for k in range(L)]
    preds = {n: sorted((e["from"] for e in data["edges"] if e["to"] == n), key=idx.get) for n in nodes}
    slot, occ = {}, set()
    for k in range(L):
        for v in by_layer[k]:
            chosen = None
            for u in preds[v]:
                s = slot[u]
                if (k, s) not in occ and not any((m, s) in occ for m in range(layer[u] + 1, k)):
                    chosen = s
                    break
            if chosen is None:
                chosen = next(s for s in range(len(nodes) + 1) if (k, s) not in occ)
            slot[v] = chosen
            occ.add((k, chosen))
    bw = max(len(n) for n in nodes) + 4
    gap = 7
    per = max(1, (W - 4 + gap) // (bw + gap))
    if bw + 4 > W:
        raise HarnessBug("graph box wider than the diagram")
    band = {n: layer[n] // per for n in nodes}
    xpos = {n: 2 + (layer[n] % per) * (bw + gap) for n in nodes}

    drawn, listed = [], []
    for i, e in enumerate(data["edges"]):
        u, v = e["from"], e["to"]
        straight = (band[u] == band[v] and slot[u] == slot[v]
                    and not any((m, slot[u]) in occ for m in range(layer[u] + 1, layer[v])))
        (drawn if straight else listed).append(i)
    slugs = {i: f"█R{k:02d}" for k, i in enumerate(drawn, 1)}
    if len(drawn) > 99:
        raise HarnessBug("more than 99 drawn edges: widen the gap for 3-digit slugs")

    lines = ["┌" + "─" * (W - 2) + "┐"]
    nbands = max(band.values()) + 1
    for b in range(nbands):
        if b:
            lines.append("├" + "─" * (W - 2) + "┤")
        members = [n for n in nodes if band[n] == b]
        for s in sorted({slot[n] for n in members}):
            rows = [[" "] * W for _ in range(3)]
            for r in rows:
                r[0] = r[W - 1] = "│"
            for n in (m for m in members if slot[m] == s):
                x = xpos[n]
                box = ["┌" + "─" * (bw - 2) + "┐", "│ " + n.ljust(bw - 4) + " │", "└" + "─" * (bw - 2) + "┘"]
                for r, text in zip(rows, box):
                    r[x:x + bw] = list(text)
            for i in drawn:
                e = data["edges"][i]
                if band[e["from"]] == b and slot[e["from"]] == s:
                    a, z = xpos[e["from"]] + bw, xpos[e["to"]] - 1
                    length = z - a + 1
                    text = "─" + slugs[i] + "─" * (length - 2 - len(slugs[i])) + "▶"
                    rows[1][a:z + 1] = list(text)
            lines += ["".join(r) for r in rows]
    lines.append("└" + "─" * (W - 2) + "┘")
    after = [f"{slugs[i]}: {data['edges'][i]['label']}" for i in drawn]
    after += [f"note: {data['edges'][i]['from']} ─▶ {data['edges'][i]['to']} ({data['edges'][i]['label']})"
              for i in listed]
    return lines, after, {"drawn": len(drawn), "listed": len(listed), "bands": nbands}


def make_graph(rng, n, harness=HARNESS):
    for _ in range(400):
        L = rng.randint(3, 4) if n <= 8 else rng.randint(4, 5) if n <= 25 else rng.randint(6, 8)
        sizes = spread(rng, n, L)
        names = rng.sample(GRAPH_NAMES, n)
        layers, k = [], 0
        for s in sizes:
            layers.append(names[k:k + s])
            k += s
        order = [x for lay in layers for x in lay]
        idx = {x: i for i, x in enumerate(order)}
        edges = set()
        for j in range(1, L):
            for v in layers[j]:
                edges.add((rng.choice(layers[j - 1]), v))
        extra = round(0.35 * n)
        tries = 0
        while extra and tries < 1000:
            tries += 1
            a, b = sorted(rng.sample(range(L), 2))
            e = (rng.choice(layers[a]), rng.choice(layers[b]))
            if e not in edges:
                edges.add(e)
                extra -= 1
        edges = sorted(edges, key=lambda e: (idx[e[0]], idx[e[1]]))
        data = {"nodes": order, "edges": [{"from": u, "to": v, "label": rng.choice(EDGE_LABELS)} for u, v in edges]}
        dist = distances(data)
        reach = [(a, b) for a in order for b in order if a != b and b in dist[a]]
        far = [(a, b) for a, b in reach if dist[a][b] >= 2]
        layer = graph_layers(data)
        unreach = [(a, b) for a in order for b in order if a != b and b not in dist[a] and layer[b] > layer[a]]
        if not (far and unreach):
            continue
        qs = []
        if rng.random() < 0.5:
            a, b = rng.choice(far)
            gold = "yes"
        else:
            a, b = rng.choice(unreach)
            gold = "no"
        qs.append(q("path", "reach", f"Is there a directed path from {a} to {b}? Answer yes or no.", gold,
                    "yesno", a=a, b=b))
        a, b = rng.choice(far)
        qs.append(q("path", "path_length", f"How many edges are on the shortest directed path from {a} to {b}? "
                    f"Answer with a number.", dist[a][b], "int", a=a, b=b))
        sources = sorted(x for x in order if layer[x] == 0)
        if harness == 1:
            qs.append(q("aggregate", "no_dependents", "Which nodes have no dependents, that is, no edge pointing to "
                        "them? List them all, separated by commas.", sources, "set"))
        else:
            # A2: one number, not a list the model can loop on
            qs.append(q("aggregate", "no_incoming", "How many nodes have no incoming edge, that is, no edge pointing "
                        "to them? Answer with a number.", len(sources), "int"))
        drawings = {W: draw_graph(data, W) for W in WIDTHS}
        return data, drawings, qs, n
    raise HarnessBug("could not make a graph in 400 tries")


def graph_prose(data):
    out = [f"The graph has {len(data['nodes'])} nodes: {oxford(data['nodes'])}."]
    out += [f"{e['from']} {e['label']} {e['to']}." for e in data["edges"]]
    return " ".join(out)


def graph_list(data):
    return "\n".join(["Nodes: " + ", ".join(data["nodes"]), "Edges:"]
                     + [f"- {e['from']} -> {e['to']} ({e['label']})" for e in data["edges"]])


# ---------------------------------------------------------------------------------------------------------
# Containment: groups holding items, a few subgroups, some items in two groups
# ---------------------------------------------------------------------------------------------------------

def all_groups(data):
    out = []
    for g in data["groups"]:
        out.append(g)
        out += g.get("groups", [])
    return out


def holders(data):
    h = {}
    for g in all_groups(data):
        for it in g["items"]:
            h.setdefault(it, []).append(g["name"])
    return h


def contents(g):
    """Distinct items in g, including its subgroups."""
    s = set(g["items"])
    for sub in g.get("groups", []):
        s |= set(sub["items"])
    return s


def make_containment(rng, n):
    for _ in range(400):
        if n <= 8:
            ntop, nsub = 2, 0
        elif n <= 25:
            ntop, nsub = rng.randint(3, 4), rng.randint(1, 2)
        else:
            ntop, nsub = rng.randint(6, 8), rng.randint(2, 4)
        gnames = rng.sample(GROUP_NAMES, ntop + nsub)
        nitems = n - ntop - nsub
        items = rng.sample(ITEM_NAMES, nitems)
        tops = [{"name": g, "items": [], "groups": []} for g in gnames[:ntop]]
        subs = []
        for g in gnames[ntop:]:
            parent = rng.choice(tops)
            sub = {"name": g, "items": []}
            parent["groups"].append(sub)
            subs.append((sub, parent))
        groups = tops + [s for s, _ in subs]
        if nitems < len(groups):
            continue
        anc = {s["name"]: p["name"] for s, p in subs}
        for i, it in enumerate(items):
            g = groups[i] if i < len(groups) else rng.choice(groups)
            g["items"].append(it)
            if i >= len(groups) and rng.random() < 0.2:
                others = [o for o in groups if o is not g and anc.get(o["name"]) != g["name"]
                          and anc.get(g["name"]) != o["name"]]
                if others:
                    rng.choice(others)["items"].append(it)
        order = {it: i for i, it in enumerate(items)}
        for g in groups:
            g["items"].sort(key=order.get)
        for t in tops:
            if not t["groups"]:
                del t["groups"]
        data = {"groups": tops}
        h = holders(data)
        allg = all_groups(data)
        qs = []
        x = rng.choice(items)
        want_yes = rng.random() < 0.5
        yes = [g["name"] for g in allg if x in contents(g)]
        no = [g["name"] for g in allg if x not in contents(g)]
        pool = yes if want_yes and yes else no if no else yes
        y = rng.choice(pool)
        qs.append(q("containment", "inside", f"Is {x} inside {y}, directly or through a subgroup? Answer yes or no.",
                    "yes" if y in yes else "no", "yesno", x=x, y=y))
        duals = [it for it in items if len(h[it]) > 1]
        x = rng.choice(duals) if duals and rng.random() < 0.5 else rng.choice(items)
        qs.append(q("containment", "holders", f"Which groups directly hold {x}? List them all, separated by commas.",
                    sorted(h[x]), "set", x=x))
        withsub = [g for g in tops if g.get("groups")]
        g = rng.choice(withsub) if withsub and rng.random() < 0.7 else rng.choice(tops)
        qs.append(q("count", "count", f"How many distinct items are in {g['name']}, counting items in its "
                    f"subgroups? Answer with a number.", len(contents(g)), "int", g=g["name"]))
        drawings = {W: draw_containment(data, W) for W in WIDTHS}
        return data, drawings, qs, ntop + nsub + nitems
    raise HarnessBug("could not make a containment structure in 400 tries")


def pack(words, width):
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 2 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur}  {w}" if cur else w
    if cur:
        lines.append(cur)
    return lines


def group_min(g):
    w = max([len(g["name"])] + [len(i) for i in g["items"]]) + 4
    for s in g.get("groups", []):
        w = max(w, group_min(s) + 4)
    return w


def render_group(g, w):
    blank = "│" + " " * (w - 2) + "│"
    out = ["┌" + "─" * (w - 2) + "┐", "│ " + g["name"].ljust(w - 4) + " │", "├" + "─" * (w - 2) + "┤"]
    out += ["│ " + line.ljust(w - 4) + " │" for line in pack(g["items"], w - 4)]
    for s in g.get("groups", []):
        out += ["│ " + line + " │" for line in render_group(s, w - 4)]
    if len(out) == 3:
        out.append(blank)
    return out + ["└" + "─" * (w - 2) + "┘"]


def draw_containment(data, W):
    tops = data["groups"]
    mw = max(group_min(g) for g in tops)
    inner = W - 4
    if mw > inner:
        raise HarnessBug("group wider than the diagram")
    c = max(1, min(len(tops), (inner + 1) // (mw + 1)))
    gw = (inner - (c - 1)) // c
    lines = ["┌" + "─" * (W - 2) + "┐"]
    for r in range(0, len(tops), c):
        if r:
            lines.append("│" + " " * (W - 2) + "│")
        boxes = [render_group(g, gw) for g in tops[r:r + c]]
        h = max(len(b) for b in boxes)
        for b in boxes:
            b[-1:-1] = ["│" + " " * (gw - 2) + "│"] * (h - len(b))
        for k in range(h):
            lines.append("│ " + " ".join(b[k] for b in boxes).ljust(inner) + " │")
    lines.append("└" + "─" * (W - 2) + "┘")
    return lines, [], {"per_row": c}


def containment_prose(data):
    tops = data["groups"]
    out = [f"There are {len(tops)} top-level groups: {oxford([g['name'] for g in tops])}."]
    for g in tops:
        out.append(f"{g['name']} holds {oxford(g['items'])}.")
        subs = g.get("groups", [])
        if subs:
            word = "subgroup" if len(subs) == 1 else "subgroups"
            out.append(f"{g['name']} also contains the {word} {oxford([s['name'] for s in subs])}.")
            for s in subs:
                out.append(f"{s['name']}, inside {g['name']}, holds {oxford(s['items'])}.")
    return " ".join(out)


def containment_list(data):
    out = []
    for g in data["groups"]:
        out.append(f"- {g['name']} (group)")
        out += [f"  - {i}" for i in g["items"]]
        for s in g.get("groups", []):
            out.append(f"  - {s['name']} (group)")
            out += [f"    - {i}" for i in s["items"]]
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------
# Noise, lint, assembly
# ---------------------------------------------------------------------------------------------------------

def q(kind, sub, text, gold, atype, **args):
    return {"kind": kind, "sub": sub, "text": text, "gold": gold, "answer_type": atype, "args": args}


def add_noise(rng, rows):
    """One ragged row (a space before its last character) and one broken join (an inner │ gapped)."""
    rows = list(rows)
    content = [i for i in range(1, len(rows) - 1) if any(ch.isalpha() for ch in rows[i])]
    r1 = rng.choice(content)
    spots = [(i, x) for i in content for x, ch in enumerate(rows[i])
             if ch == "│" and 0 < x < len(rows[i]) - 1
             and rows[i][x - 1] not in "─▶" and rows[i][x + 1] not in "─▶"]
    if not spots:
        raise HarnessBug("no inner │ to break")
    i, x = rng.choice(spots)
    rows[i] = rows[i][:x] + " " + rows[i][x + 1:]
    rows[r1] = rows[r1][:-1] + " " + rows[r1][-1]
    return rows


def lint(text):
    return oph_lint.check_text("generated.oph", text)


def make_structure(seed, typ, size, i, harness=HARNESS):
    rng = random.Random(f"{seed}:{typ}:{size}:{i}")
    n = rng.randint(*SIZES[size])
    if typ == "layout":
        data, drawings, qs, count, pct = make_layout(rng, n, harness)
        drawn = {W: (rows, notes, {}) for W, (rows, notes) in drawings.items()}
        prose, lst = layout_prose(data), layout_list(data)
    elif typ == "graph":
        data, drawn, qs, count = make_graph(rng, n, harness)
        prose, lst = graph_prose(data), graph_list(data)
    else:
        data, drawn, qs, count = make_containment(rng, n)
        prose, lst = containment_prose(data), containment_list(data)
    sid = f"{seed}-{typ}-{size}-{i:02d}"
    enc, meta = {}, {}
    for W, (rows, after, info) in drawn.items():
        for row in rows:
            if oph_lint.width(row) != W:
                raise HarnessBug(f"{sid}@{W}: row is {oph_lint.width(row)} wide, not {W}")
        clean = "\n".join(rows + after)
        problems = lint(clean)
        if problems:
            raise HarnessBug(f"{sid}@{W} fails the lint: {[(p.line, p.kind, p.message) for p in problems]}")
        noisy = "\n".join(add_noise(rng, rows) + after)
        kinds = {p.kind for p in lint(noisy)}
        if kinds != {"width", "joins"}:
            raise HarnessBug(f"{sid}@{W}: noise variant lints as {kinds}, expected width and joins")
        enc[f"ophanic@{W}"] = clean
        enc[f"ophanic-noise@{W}"] = noisy
        meta[f"ophanic@{W}"] = info
    enc["prose"] = prose
    enc["json"] = json.dumps(data, indent=2, ensure_ascii=False)
    enc["list"] = lst
    if harness >= 3 and typ == "layout":
        enc[LOOKUP_ARM] = layout_list(pct)   # the pilot's list: shares stated as percentages
    if harness >= 2:
        enc["json-compact"] = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    for k, qq in enumerate(qs):
        qq["id"] = f"q{k}"
    out = {"id": sid, "seed": seed, "type": typ, "size": size, "index": i, "elements": count,
           "data": data, "encodings": enc, "draw_info": meta, "questions": qs}
    if harness >= 2:
        out["harness"] = harness
    if harness >= 3 and typ == "layout":
        out["share_pair"] = SHARE_PAIR
    return out


def prompt(encoding_text, question_text):
    """The pilot's prompt: the encoding, the question, the instruction. No framing, no fence."""
    return f"{encoding_text}\n\n{question_text}\n{INSTRUCTION}"


# ---------------------------------------------------------------------------------------------------------
# Framing (A3): one neutral sentence per arm saying what the structure is and how to read it
# ---------------------------------------------------------------------------------------------------------

# Pilot 2's framing (harness 2, `--framing pilot2`): one sentence per arm, written separately for each
FRAMING = {
    ("ophanic", "layout"): "The diagram below is a screen layout drawn with box-drawing characters: each box is a "
        "panel labelled with its name, and a box's width in characters, border to border, measured against the "
        "width of the row it sits in gives its share of that row; a label cut short with … is spelled out in a "
        "note under the diagram.",
    ("ophanic", "graph"): "The diagram below is a directed graph drawn with box-drawing characters: each box is a "
        "node, an arrow such as ─█R01─▶ is an edge from the box on its left to the box on its right, the legend "
        "under the diagram gives each slug's edge label, and edges not drawn as arrows are listed under it as "
        "note: A ─▶ B (label).",
    ("ophanic", "containment"): "The diagram below shows groups drawn with box-drawing characters: each box is a "
        "group with its name above the divider and its items below it, a box inside a box is a subgroup, and an "
        "item drawn in two boxes belongs to both groups.",
    ("prose", "layout"): "The text below describes a screen layout of nested rows and columns in sentences, giving "
        "each column's width in characters and the width of the row it divides.",
    ("prose", "graph"): "The text below describes a directed graph in sentences: it names the nodes, then states "
        "each edge as \"A label B\", an edge from A to B.",
    ("prose", "containment"): "The text below describes groups and the items they hold in sentences, including "
        "subgroups inside groups.",
    ("json", "layout"): "The JSON below describes a screen layout: \"rows\" run top to bottom, \"columns\" run "
        "left to right, each panel is named, and \"width\" is a width in characters, so a column's share of its "
        "row is its width over the width of the columns it belongs to.",
    ("json", "graph"): "The JSON below describes a directed graph: a list of nodes, and a list of edges, each from "
        "one node to another with a label.",
    ("json", "containment"): "The JSON below describes groups: each group has a name, the items it holds directly, "
        "and any subgroups.",
    ("list", "layout"): "The outline below describes a screen layout: indentation shows nesting, rows run top to "
        "bottom and columns left to right, and each column's width is given in characters out of its row's width.",
    ("list", "graph"): "The list below describes a directed graph: its nodes, then its edges, each written "
        "A -> B (label) for an edge from A to B.",
    ("list", "containment"): "The outline below describes groups: an entry marked (group) is a group, and the "
        "entries indented under it are what it holds.",
}
# The pilot's tasks (harness 1) state shares as percentages in the text arms
FRAMING_V1_LAYOUT = {
    "prose": "The text below describes a screen layout of nested rows and columns in sentences, giving each "
        "column's share of its row as a percentage.",
    "json": "The JSON below describes a screen layout: \"rows\" run top to bottom, \"columns\" run left to right, "
        "each panel is named, and \"share\" is a column's percentage of its row's width.",
    "list": "The outline below describes a screen layout: indentation shows nesting, rows run top to bottom and "
        "columns left to right, and each column's share of its row is given as a percentage.",
}
# A13: matched framing. Every arm of a structure type gets the same sentence: the same description of the
# structure and the same rule for the share, differing only in the name of the form and how that form marks
# things (a box, a sentence, a key, an indented line).
MATCHED_FORM = {"ophanic": "The diagram below, drawn with box-drawing characters,", "prose": "The text below",
                "json": "The JSON below", "list": "The outline below", "list-lookup": "The outline below"}
MATCHED_BODY = {
    "layout": "describes a screen layout of named panels in nested rows, top to bottom, and columns, left to "
              "right; a column's share of its row is its width in characters divided by the row's width in "
              "characters, {key}.",
    "graph": "describes a directed graph of named nodes joined by labelled edges; {key}.",
    "containment": "describes named groups, the items each group holds directly, and subgroups inside groups; an "
                   "item can belong to more than one group, and {key}.",
}
MATCHED_KEY = {
    ("ophanic", "layout"): "each box is a panel, and widths are measured border to border in the drawing (a label "
                           "cut short with … is spelled out in a note under it)",
    ("prose", "layout"): "and the text states each column's width and its row's width",
    ("json", "layout"): "and \"width\" gives each column's width and its row's width",
    ("list", "layout"): "and each column's line states its width and its row's width",
    ("list-lookup", "layout"): "and each column's line states that share as a percentage",
    ("ophanic", "graph"): "each box is a node, an arrow ─█Rnn─▶ is an edge from the box on its left to the box on "
                          "its right with its label in the legend under the diagram, and every other edge is listed "
                          "there as note: A ─▶ B (label)",
    ("prose", "graph"): "each edge is a sentence \"A label B\", an edge from A to B",
    ("json", "graph"): "each edge has a from node, a to node and a label",
    ("list", "graph"): "each edge is a line A -> B (label), an edge from A to B",
    ("ophanic", "containment"): "each box is a group with its name above the divider, its items below it, and its "
                                "subgroups as boxes inside it",
    ("prose", "containment"): "each sentence says what one group holds",
    ("json", "containment"): "each group has a name, its items, and any groups inside it",
    ("list", "containment"): "an entry marked (group) is a group and the entries indented under it are what it holds",
}
FRAMING_STYLES = ("matched", "pilot2", "off")
MODIFIERS = ("fenced", "unframed")


def parse_arm(arm: str) -> tuple[str, set[str]]:
    """'ophanic@100+fenced' -> ('ophanic@100', {'fenced'}). Modifiers: fenced (ophanic only), unframed."""
    base, *mods = arm.split("+")
    bad = set(mods) - set(MODIFIERS)
    if bad:
        raise ValueError(f"unknown arm modifier(s) {sorted(bad)} in {arm!r}")
    if "fenced" in mods and not base.startswith("ophanic"):
        raise ValueError(f"fenced applies to ophanic arms only, not {arm!r}")
    return base, set(mods)


def family(base: str) -> str:
    return "ophanic" if base.startswith("ophanic") else "json" if base.startswith("json") else base


def matched_framing(task: dict, base: str) -> str:
    fam = family(base)
    key = MATCHED_KEY[(fam, task["type"])]
    if task["type"] == "layout" and fam not in ("ophanic", "list-lookup") and task.get("harness", 1) == 1:
        key = "and the text states each column's share as a percentage"
    return f"{MATCHED_FORM[fam]} " + MATCHED_BODY[task["type"]].format(key=key)


def framing_for(task: dict, base: str, style: str = "pilot2") -> str:
    if style == "matched":
        return matched_framing(task, base)
    fam = family(base)
    if fam == "list-lookup":
        return FRAMING_V1_LAYOUT["list"]
    if task["type"] == "layout" and fam != "ophanic" and task.get("harness", 1) == 1:
        return FRAMING_V1_LAYOUT[fam]
    return FRAMING[(fam, task["type"])]


def build_prompt(task: dict, arm: str, question_text: str, framing="matched") -> str:
    """The prompt for one call. With framing (A3) it starts with the arm's framing sentence; `+fenced` wraps an
    ophanic diagram in a ``` fence; `+unframed` drops the framing for that arm. Unframed and unfenced, this is
    exactly the pilot's prompt()."""
    base, mods = parse_arm(arm)
    text = task["encodings"][base]
    if "fenced" in mods:
        text = f"```\n{text}\n```"
    style = {True: "pilot2", False: "off"}.get(framing, framing)
    if style not in FRAMING_STYLES:
        raise ValueError(f"unknown framing style {framing!r}")
    if style != "off" and "unframed" not in mods:
        return f"{framing_for(task, base, style)}\n\n{text}\n\n{question_text}\n{INSTRUCTION}"
    return prompt(text, question_text)


def generate(seed, per_cell, harness=HARNESS):
    return [make_structure(seed, t, s, i, harness) for t in TYPES for s in SIZES for i in range(per_cell)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--per-cell", type=int, default=10)
    ap.add_argument("--out", default=str(HERE / "tasks"))
    ap.add_argument("--harness", type=int, choices=[1, 2, 3], default=HARNESS,
                    help="task format: 1 and 2 reproduce pilots 1 and 2; 3 adds the share lookup control (A12)")
    a = ap.parse_args(argv)
    if CONFIRMATORY_SEEDS[0] <= a.seed <= CONFIRMATORY_SEEDS[1]:
        print(f"note: seed {a.seed} is in the range reserved for confirmatory runs (README, Seeds)", file=sys.stderr)
    tasks = generate(a.seed, a.per_cell, a.harness)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{a.seed}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"wrote {len(tasks)} structures, {sum(len(t['questions']) for t in tasks)} questions to {path}")


if __name__ == "__main__":
    main()
