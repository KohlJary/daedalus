"""
Harness tests for generate.py. Run: python -m pytest test_generate.py -q

The answer solvers here are written independently of generate.py's: they read only the `json` encoding
(parsed back from its text), so a pass means every gold answer is derivable from it.
"""

from __future__ import annotations

import json
import random
import re
import sys
from collections import deque
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402
import oph_lint  # noqa: E402
import score  # noqa: E402

SEED = 99001   # a test-only seed; never the pilot's or a confirmatory one


@pytest.fixture(scope="module")
def tasks():
    return generate.generate(SEED, 4)


def test_deterministic():
    a = [json.dumps(t, sort_keys=True) for t in generate.generate(SEED, 2)]
    b = [json.dumps(t, sort_keys=True) for t in generate.generate(SEED, 2)]
    assert a == b


def test_cells_and_sizes(tasks):
    cells = {(t["type"], t["size"]) for t in tasks}
    assert cells == {(ty, s) for ty in generate.TYPES for s in generate.SIZES}
    for t in tasks:
        lo, hi = generate.SIZES[t["size"]]
        assert lo <= t["elements"] <= hi, t["id"]
        assert set(t["encodings"]) == {"ophanic@100", "ophanic@60", "ophanic-noise@100", "ophanic-noise@60",
                                       "prose", "json", "list"}


def test_clean_diagrams_pass_lint_and_are_full_width(tasks):
    for t in tasks:
        for W in generate.WIDTHS:
            text = t["encodings"][f"ophanic@{W}"]
            assert oph_lint.check_text("t.oph", text) == [], t["id"]
            rows = [r for r in text.splitlines() if oph_lint._is_row(r)]
            assert {oph_lint.width(r) for r in rows} == {W}, t["id"]


def test_noise_fails_lint_with_width_and_joins(tasks):
    for t in tasks:
        for W in generate.WIDTHS:
            kinds = {p.kind for p in oph_lint.check_text("t.oph", t["encodings"][f"ophanic-noise@{W}"])}
            assert kinds == {"width", "joins"}, t["id"]
            # noise keeps every name and letter: only box characters and spaces change
            strip = lambda s: re.sub(r"[^A-Za-z0-9…]", "", s)
            assert strip(t["encodings"][f"ophanic-noise@{W}"]) == strip(t["encodings"][f"ophanic@{W}"])


# ---- independent solvers over the json encoding ----------------------------------------------------------

def layout_rects(node, heights):
    """Leaf rectangles with fractional x and integer y; leaf heights from `heights` (any positive values)."""
    out = {}

    def h(n):
        if "panel" in n:
            return heights[n["panel"]]
        if "rows" in n:
            return sum(h(c) for c in n["rows"])
        return max(h(c) for c in n["columns"])

    def go(n, x0, x1, y0, y1):
        if "panel" in n:
            out[n["panel"]] = (x0, x1, y0, y1)
        elif "rows" in n:
            y = y0
            for i, c in enumerate(n["rows"]):
                ny = y1 if i == len(n["rows"]) - 1 else y + h(c)
                go(c, x0, x1, y, ny)
                y = ny
        else:
            x = x0
            for c in n["columns"]:
                nx = x + (x1 - x0) * Fraction(c["share"], 100)
                go(c, x, nx, y0, y1)
                x = nx
    go(node, Fraction(0), Fraction(1), 0, h(node))
    return out


def all_panels(n):
    if "panel" in n:
        return [n]
    return [p for c in n.get("rows", n.get("columns")) for p in all_panels(c)]


def solve_layout(data, qq, rng):
    names = [p["panel"] for p in all_panels(data)]
    if qq["sub"] == "share":
        return next(p["share"] for p in all_panels(data) if p["panel"] == qq["args"]["x"])
    answers = set()
    for _ in range(12):   # the answer must not depend on how tall anything is drawn
        r = layout_rects(data, {n: rng.randint(1, 4) for n in names})
        x0, x1, y0, y1 = r[qq["args"]["x"]]
        if qq["sub"] == "right_of":
            hit = [n for n, (a0, a1, b0, b1) in r.items() if a0 == x1 and max(b0, y0) < min(b1, y1)]
        else:
            hit = [n for n, (a0, a1, b0, b1) in r.items() if b0 == y1 and max(a0, x0) < min(a1, x1)]
        answers.add(tuple(sorted(hit)))
    assert len(answers) == 1, f"answer depends on heights: {answers}"
    (hit,) = answers
    assert len(hit) == 1
    return hit[0]


def solve_graph(data, qq):
    succ = {n: [] for n in data["nodes"]}
    indeg = {n: 0 for n in data["nodes"]}
    for e in data["edges"]:
        succ[e["from"]].append(e["to"])
        indeg[e["to"]] += 1
    if qq["sub"] == "no_dependents":
        return sorted(n for n, d in indeg.items() if d == 0)
    a, b = qq["args"]["a"], qq["args"]["b"]
    seen, frontier = {a: 0}, deque([a])
    while frontier:
        u = frontier.popleft()
        for v in succ[u]:
            if v not in seen:
                seen[v] = seen[u] + 1
                frontier.append(v)
    if qq["sub"] == "reach":
        return "yes" if b in seen else "no"
    return seen[b]


def solve_containment(data, qq):
    flat = []
    for g in data["groups"]:
        flat.append((g["name"], set(g["items"]), [s["name"] for s in g.get("groups", [])]))
        for s in g.get("groups", []):
            flat.append((s["name"], set(s["items"]), []))
    direct = {name: items for name, items, _ in flat}
    subs = {name: kids for name, _, kids in flat}

    def deep(name):
        out = set(direct[name])
        for k in subs[name]:
            out |= deep(k)
        return out
    if qq["sub"] == "inside":
        return "yes" if qq["args"]["x"] in deep(qq["args"]["y"]) else "no"
    if qq["sub"] == "holders":
        return sorted(name for name, items, _ in flat if qq["args"]["x"] in items)
    return len(deep(qq["args"]["g"]))


def test_every_answer_derivable_from_json(tasks):
    rng = random.Random(0)
    for t in tasks:
        data = json.loads(t["encodings"]["json"])
        assert data == t["data"]
        for qq in t["questions"]:
            solver = {"layout": lambda d, x: solve_layout(d, x, rng), "graph": solve_graph,
                      "containment": solve_containment}[t["type"]]
            assert solver(data, qq) == qq["gold"], (t["id"], qq)


# ---- the other encodings carry the same facts --------------------------------------------------------------

def names_of(t):
    d = t["data"]
    if t["type"] == "layout":
        return [p["panel"] for p in all_panels(d)]
    if t["type"] == "graph":
        return d["nodes"]
    out = []
    for g in d["groups"]:
        out += [g["name"], *g["items"]]
        for s in g.get("groups", []):
            out += [s["name"], *s["items"]]
    return out


def test_every_name_in_every_encoding(tasks):
    for t in tasks:
        for enc, text in t["encodings"].items():
            for n in names_of(t):
                abbreviated = re.search(rf"note: (\S+…) = {re.escape(n)}$", text, re.M)
                assert re.search(rf"\b{re.escape(n)}\b", text) or abbreviated, (t["id"], enc, n)


def drawn_edges(text):
    """Edges read back off a graph diagram: straight `│ A │─█Rnn─▶│ B │` runs, plus `note:` lines."""
    legend = dict(re.findall(r"^(█R\d+): (\w+)$", text, re.M))
    out = set()
    for row in text.splitlines():
        for m in re.finditer(r"│ (\w+) +│─(█R\d+)─*▶(?=│ (\w+) +│)", row):
            out.add((m.group(1), m.group(3), legend[m.group(2)]))
    out |= set(re.findall(r"^note: (\w+) ─▶ (\w+) \((\w+)\)$", text, re.M))
    return out


def test_graph_diagrams_carry_every_edge(tasks):
    for t in (t for t in tasks if t["type"] == "graph"):
        want = {(e["from"], e["to"], e["label"]) for e in t["data"]["edges"]}
        for W in generate.WIDTHS:
            assert drawn_edges(t["encodings"][f"ophanic@{W}"]) == want, (t["id"], W)
        assert set(re.findall(r"^- (\w+) -> (\w+) \((\w+)\)$", t["encodings"]["list"], re.M)) == want


def test_layout_proportions_drawn_within_tolerance(tasks):
    for t in (t for t in tasks if t["type"] == "layout"):
        for qq in (q for q in t["questions"] if q["sub"] == "share"):
            for W in generate.WIDTHS:
                _, drawn = generate.place_layout(t["data"], W)
                assert abs(drawn[qq["args"]["x"]] - qq["gold"]) <= 2.5


def test_layout_labels_sit_in_their_rectangles(tasks):
    """Read each label's box back off the drawing: its side borders are the generator's rectangle."""
    for t in (t for t in tasks if t["type"] == "layout"):
        for W in generate.WIDTHS:
            rects, _ = generate.place_layout(t["data"], W)
            rows = t["encodings"][f"ophanic@{W}"].splitlines()
            for name, r in rects.items():
                row = rows[r["y0"] + 1]
                assert row[r["x0"]] in "│├┤┼" and row[r["x1"]] in "│├┤┼", (t["id"], name)
                assert row[r["x0"] + 2:].startswith(name) or row[r["x0"] + 2:].split()[0].endswith("…")


# ---- scoring ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("atype,answer,gold,ok", [
    ("name", "Timer", "Timer", True),
    ("name", "**timer**.", "Timer", True),
    ("name", "Timer panel", "Timer", True),
    ("name", "Timer and Clock", "Timer", False),
    ("yesno", "Yes.", "yes", True),
    ("yesno", "No", "yes", False),
    ("int", "3 edges", 3, True),
    ("percent", "33%", 30, True),
    ("percent", "36", 30, False),
    ("percent", "25", 30, True),
    ("set", "Auth, Store", ["Store", "Auth"], True),
    ("set", "Auth and Store", ["Store", "Auth"], True),
    ("set", "Auth", ["Store", "Auth"], False),
    ("name", "<think>\n\n</think>\n\nTimer", "Timer", True),
])
def test_scoring(atype, answer, gold, ok):
    assert score.correct({"answer_type": atype, "gold": gold}, answer) is ok


def test_wilson():
    lo, hi = score.wilson(5, 10)
    assert 0.23 < lo < 0.24 and 0.76 < hi < 0.77
    assert score.wilson(0, 0) == (0.0, 1.0)
