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
import run  # noqa: E402
import score  # noqa: E402

SEED = 99001   # a test-only seed; never a pilot's or a confirmatory one
TEXT_ARMS = ("prose", "json", "json-compact", "list")


@pytest.fixture(scope="module")
def tasks():
    return generate.generate(SEED, 4)


@pytest.fixture(scope="module")
def tasks_v1():
    return generate.generate(SEED, 4, harness=1)


def test_seed_rules():
    lo, hi = generate.CONFIRMATORY_SEEDS
    assert SEED not in range(lo, hi + 1)
    assert not any(lo <= s <= hi for s in generate.RESERVED_PAST)


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
                                       "prose", "json", "json-compact", "list"} | (
                                           {"list-lookup"} if t["type"] == "layout" else set())
        assert json.loads(t["encodings"]["json-compact"]) == t["data"]


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

def frac(child, parent):
    """A column's fraction of its row: the pilot's percentage share, or harness 2's width over the row's width."""
    if "share" in child:
        return Fraction(child["share"], 100)
    return Fraction(child["width"], parent["width"])


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
                nx = x + (x1 - x0) * frac(c, n)
                go(c, x, nx, y0, y1)
                x = nx
    go(node, Fraction(0), Fraction(1), 0, h(node))
    return out


def all_panels(n):
    if "panel" in n:
        return [n]
    return [p for c in n.get("rows", n.get("columns")) for p in all_panels(c)]


def share_of(data, name):
    """The panel's share of its row, in percent, from the json alone."""
    def go(n):
        for c in n.get("columns", []):
            if c.get("panel") == name:
                return 100 * frac(c, n)
        for c in n.get("rows", n.get("columns", [])):
            got = go(c)
            if got is not None:
                return got
        return None
    return go(data)


def solve_layout(data, qq, rng):
    names = [p["panel"] for p in all_panels(data)]
    if qq["sub"] == "share":
        return share_of(data, qq["args"]["x"])
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
    if qq["sub"] == "no_incoming":
        return sum(1 for d in indeg.values() if d == 0)
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
            got = solver(data, qq)
            if qq["sub"] == "share":
                # the pilot states the share exactly; harness 2's widths give it to within the drawn tolerance
                assert abs(got - qq["gold"]) <= 2.5, (t["id"], qq, float(got))
            else:
                assert got == qq["gold"], (t["id"], qq)


def test_every_answer_derivable_from_json_v1(tasks_v1):
    test_every_answer_derivable_from_json(tasks_v1)


def test_pilot_answers_derivable_from_json():
    """The pilot's own golds (seed 1015), not just the test seed's. Skipped if tasks/1015.jsonl isn't generated."""
    path = HERE / "tasks" / "1015.jsonl"
    if not path.exists():
        pytest.skip("tasks/1015.jsonl not generated")
    pilot = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    test_every_answer_derivable_from_json(pilot)


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


def test_layout_proportions_drawn_within_tolerance(tasks_v1):
    for t in (t for t in tasks_v1 if t["type"] == "layout"):
        for qq in (q for q in t["questions"] if q["sub"] == "share"):
            for W in generate.WIDTHS:
                _, drawn = generate.place_layout(t["data"], W)
                assert abs(drawn[qq["args"]["x"]] - qq["gold"]) <= 2.5


def test_layout_labels_sit_in_their_rectangles(tasks_v1):
    """Read each label's box back off the drawing: its side borders are the generator's rectangle."""
    for t in (t for t in tasks_v1 if t["type"] == "layout"):
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


# ---- harness 2 (DESIGN.md amendments, proposed) ---------------------------------------------------------------

def test_harness1_reproduces_the_pilot_tasks():
    """`--harness 1` regenerates tasks/1015.jsonl byte for byte (its sha256 is in README)."""
    import hashlib
    text = "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in generate.generate(1015, 10, harness=1))
    assert hashlib.sha256(text.encode()).hexdigest() == \
        "ebe363660187bccd6749bcfd999efa8a0977ab2bd5424cf34a5ae7f33a39524a"


def test_harness2_changes_only_the_text_arms_and_questions(tasks, tasks_v1):
    for a, b in zip(tasks, tasks_v1):
        for enc in ("ophanic@100", "ophanic@60", "ophanic-noise@100", "ophanic-noise@60"):
            assert a["encodings"][enc] == b["encodings"][enc], (a["id"], enc)
        if a["type"] == "containment":
            assert a["encodings"]["json"] == b["encodings"]["json"] and a["questions"] == b["questions"]


def stated_width(task, arm, name):
    """(width, row width) as a text arm states them for a panel, read back from the text alone."""
    text = task["encodings"][arm]
    if arm == "prose":
        m = re.search(rf"\b{re.escape(name)} \((\d+) of the row's (\d+) characters\)", text)
    elif arm == "list":
        m = re.search(rf"- {re.escape(name)}: (\d+) of (\d+) characters$", text, re.M)
    else:
        data = json.loads(text)

        def go(n):
            for c in n.get("columns", []):
                if c.get("panel") == name:
                    return c["width"], n["width"]
            for c in n.get("rows", n.get("columns", [])):
                got = go(c)
                if got:
                    return got
        return go(data)
    assert m, (task["id"], arm, name)
    return int(m.group(1)), int(m.group(2))


def test_proportion_needs_computation_in_every_arm(tasks):
    """A1: no arm states the share. Text arms give a width and its row's width; the answer is their ratio, and
    neither number on its own scores as right."""
    layouts = [t for t in tasks if t["type"] == "layout"]
    assert layouts
    for t in layouts:
        qq = next(q for q in t["questions"] if q["sub"] == "share")
        name, gold = qq["args"]["x"], qq["gold"]
        for arm in TEXT_ARMS:
            text = t["encodings"][arm]
            assert "%" not in text and "share" not in text and "percent" not in text, (t["id"], arm)
            w, total = stated_width(t, arm, name)
            assert total != 100, (t["id"], arm)
            assert abs(100 * w / total - gold) <= 2.5, (t["id"], arm, w, total, gold)
            assert score.correct(qq, str(round(100 * w / total))), (t["id"], arm)
            assert not score.correct(qq, str(w)), (t["id"], arm, w, gold)        # copying the width is wrong
            assert not score.correct(qq, str(total)), (t["id"], arm, total, gold)
        for W in generate.WIDTHS:
            diagram = t["encodings"][f"ophanic@{W}"]
            assert not re.search(r"\d", diagram), (t["id"], W)                   # a drawing states no number


def test_text_arms_state_the_widths_the_60_column_drawing_draws(tasks):
    """The text arms carry the ophanic@60 diagram's own widths, so the arms share their facts exactly."""
    for t in (t for t in tasks if t["type"] == "layout"):
        rows = t["encodings"]["ophanic@60"].splitlines()
        for qq in (q for q in t["questions"] if q["sub"] == "share"):
            w, total = stated_width(t, "json", qq["args"]["x"])
            line = next(r for r in rows if re.search(rf"│ {re.escape(qq['args']['x'])}\b", r))
            x0 = line.index(qq["args"]["x"]) - 2
            x1 = next(i for i in range(x0 + 1, len(line)) if line[i] in "│├┤┼")
            assert x1 - x0 == w, (t["id"], qq["args"]["x"])


def box_names(text):
    return set(re.findall(r"│ (\w+) +│", text))


def test_no_incoming_edge_gold_derivable_from_every_arm(tasks):
    """A2: the aggregate question is one number, and every arm gives it: count nodes no edge points to."""
    graphs = [t for t in tasks if t["type"] == "graph"]
    assert graphs
    for t in graphs:
        (qq,) = [q for q in t["questions"] if q["kind"] == "aggregate"]
        assert qq["sub"] == "no_incoming" and qq["answer_type"] == "int" and isinstance(qq["gold"], int)
        assert "Answer with a number." in qq["text"]
        nodes = t["data"]["nodes"]
        for W in generate.WIDTHS:
            text = t["encodings"][f"ophanic@{W}"]
            assert box_names(text) == set(nodes), (t["id"], W)
            targets = {b for _, b, _ in drawn_edges(text)}
            assert len(box_names(text) - targets) == qq["gold"], (t["id"], W)
        lst = t["encodings"]["list"]
        lnodes = re.search(r"^Nodes: (.*)$", lst, re.M).group(1).split(", ")
        ltargets = set(re.findall(r"^- \w+ -> (\w+) ", lst, re.M))
        assert len(set(lnodes) - ltargets) == qq["gold"]
        prose = t["encodings"]["prose"]
        ptargets = set(re.findall(r"(?:^|(?<=\. ))\w+ (?:needs|calls|feeds|extends) (\w+)\.", prose))
        assert len(set(nodes) - ptargets) == qq["gold"]
        assert solve_graph(json.loads(t["encodings"]["json"]), qq) == qq["gold"]


def test_no_dependents_only_in_harness1(tasks, tasks_v1):
    assert not any(q["sub"] == "no_dependents" for t in tasks for q in t["questions"])
    assert any(q["sub"] == "no_dependents" for t in tasks_v1 for q in t["questions"])


# ---- framing (A3) ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("style", ["matched", "pilot2"])
def test_every_arm_and_type_has_a_framing_sentence(tasks, style):
    for t in tasks:
        arms = ["ophanic@100", "ophanic-noise@60", "prose", "json", "json-compact", "list"]
        arms += ["list-lookup"] if t["type"] == "layout" else []
        for arm in arms:
            p = generate.build_prompt(t, arm, "Q?", style)
            frame = generate.framing_for(t, arm, style)
            assert p.startswith(frame + "\n\n" + t["encodings"][arm] + "\n\nQ?\n")
            assert frame.count(". ") == 0, frame     # one sentence


def test_matched_framing_says_the_same_thing_to_every_arm(tasks):
    """A13: within a structure type, every arm's sentence has the same description and the same share rule; only
    the name of the form and how it marks things differ."""
    for t in tasks:
        body = generate.MATCHED_BODY[t["type"]].split("{key}")[0]
        for arm in ("ophanic@100", "prose", "json", "list"):
            frame = generate.framing_for(t, arm, "matched")
            assert body in frame, (t["id"], arm)
            if t["type"] == "layout":
                assert "divided by the row's width in characters" in frame


@pytest.mark.parametrize("style", ["matched", "pilot2"])
def test_framing_is_neutral_on_the_answer(tasks, style):
    """A framing sentence names no panel, node, group or item, and no number."""
    for t in tasks:
        for arm in ("ophanic@100", "prose", "json", "list"):
            frame = generate.framing_for(t, arm, style)
            for n in names_of(t):
                assert not re.search(rf"\b{re.escape(n)}\b", frame), (t["id"], arm, n)
            assert not re.search(r"\d", re.sub(r"R(01|nn)", "", frame)), frame


def test_unframed_unfenced_prompt_is_the_pilots(tasks):
    t, q = tasks[0], tasks[0]["questions"][0]
    assert generate.build_prompt(t, "ophanic@100", q["text"], framing="off") == \
        generate.prompt(t["encodings"]["ophanic@100"], q["text"])
    assert generate.build_prompt(t, "json+unframed", q["text"]) == generate.prompt(t["encodings"]["json"], q["text"])


def test_fenced_variant(tasks):
    t = tasks[0]
    p = generate.build_prompt(t, "ophanic@100+fenced", "Q?")
    assert "\n\n```\n" + t["encodings"]["ophanic@100"] + "\n```\n\nQ?" in p
    with pytest.raises(ValueError):
        generate.build_prompt(t, "prose+fenced", "Q?")
    with pytest.raises(ValueError):
        generate.parse_arm("ophanic@100+shiny")


def test_v1_tasks_get_percentage_framing(tasks_v1):
    t = next(t for t in tasks_v1 if t["type"] == "layout")
    assert "percentage" in generate.framing_for(t, "list")
    assert "characters" in generate.framing_for({**t, "harness": 2}, "list")
    assert "percentage" in generate.framing_for(t, "list", "matched")


def test_harness2_reproduces_pilot2_tasks():
    import hashlib
    text = "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in generate.generate(5016, 3, harness=2))
    assert hashlib.sha256(text.encode()).hexdigest().startswith("185e2651")


def test_lookup_control_states_the_share(tasks):
    """A12: list-lookup is the pilot's list, the share stated as a percentage, on layouts only; and the text arms
    record which drawing their widths come from."""
    for t in tasks:
        if t["type"] != "layout":
            assert "list-lookup" not in t["encodings"] and "share_pair" not in t
            continue
        assert t["share_pair"] == "ophanic@60" == generate.SHARE_PAIR
        qq = next(q for q in t["questions"] if q["sub"] == "share")
        assert re.search(rf"- {re.escape(qq['args']['x'])}: {qq['gold']}%$", t["encodings"]["list-lookup"], re.M)


# ---- run.py (A2, A3, A5, A8) -------------------------------------------------------------------------------

def run_args(**kw):
    import argparse
    base = dict(model="qwen3:8b", num_ctx=4096, max_tokens=256, stop="\n\n", think=False, temperature=None,
                effort=None)
    return argparse.Namespace(**{**base, **kw})


def test_ollama_body_stops_and_has_room():
    body = run.ollama_body(run_args(), "x")
    assert body["options"]["stop"] == ["\n\n"] and body["options"]["num_predict"] >= 256
    assert body["options"]["temperature"] == 0 and body["think"] is False
    assert "stop" not in run.ollama_body(run_args(stop=""), "x")["options"]


def test_anthropic_body_for_current_models():
    body = run.anthropic_body(run_args(model="claude-haiku-5-5"), "x")
    assert body["model"] == "claude-haiku-5-5"
    assert "temperature" not in body and "stop_sequences" not in body   # whitespace-only stops stay client-side
    body = run.anthropic_body(run_args(model="claude-opus-5-5", effort="low", stop="END"), "x")
    assert body["output_config"] == {"effort": "low"} and body["stop_sequences"] == ["END"]


def test_paid_backend_refuses_without_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv("OPX_ALLOW_PAID", raising=False)
    with pytest.raises(SystemExit) as e:
        run.main(["--tasks", str(tmp_path / "none.jsonl"), "--run", "x", "--model", "claude-haiku-5-5",
                  "--backend", "anthropic"])
    assert "OPX_ALLOW_PAID" in str(e.value)


def test_plan_puts_noise_on_every_structure_by_default(tasks, tmp_path, capsys):
    encs = run.arms("ophanic@100,prose", fenced=True)
    assert encs == ["ophanic@100+fenced", "prose"]
    calls = list(run.plan(tasks, encs, 1))
    noise = [c for c in calls if c[1].startswith("ophanic-noise")]
    assert {c[0]["id"] for c in noise} == {t["id"] for t in tasks}
    assert {c[1] for c in noise} == {"ophanic-noise@100+fenced"}
    # run.py's defaults: five arms plus noise on every structure (A5)
    path = tmp_path / "t.jsonl"
    path.write_text("".join(json.dumps(t) + "\n" for t in tasks))
    run.main(["--tasks", str(path), "--run", "test-dry", "--model", "m", "--dry-run"])
    assert capsys.readouterr().out.startswith(f"{len(tasks) * 3 * 6} calls planned")


# ---- score.py (A1, A2, A4, A5, A9) -------------------------------------------------------------------------

def fake_rows(seed=1, n_tasks=12):
    """Calls for two arms over layout structures of each size, with known accuracies."""
    rng = random.Random(seed)
    rows = []
    for size in generate.SIZES:
        for i in range(n_tasks):
            for qid in ("q0", "q1", "q2"):
                for arm, p in (("ophanic@100", 0.6), ("prose", 0.5), ("list", 0.4), ("ophanic-noise@100", 0.6)):
                    rows.append({"task": f"L-{size}-{i}", "question_id": qid, "model": "m", "encoding": arm,
                                 "type": "layout", "size": size, "kind": "spatial" if qid != "q2" else "proportion",
                                 "sub": "x", "correct": rng.random() < p, "gold": "x", "answer": "x",
                                 "answer_type": "name", "tasks_file": "f.jsonl", "run": "fake"})
    return rows


def test_bootstrap_is_deterministic_under_a_seed():
    rows = fake_rows()
    a = score.paired_diff(rows, "ophanic@100", "prose", B=500, seed=7)
    b = score.paired_diff(rows, "ophanic@100", "prose", B=500, seed=7)
    c = score.paired_diff(rows, "ophanic@100", "prose", B=500, seed=8)
    assert a == b
    assert a[:3] != c[:3] and a[0] == c[0]          # another seed moves the interval, never the estimate
    assert a[1] <= a[0] <= a[2]
    s1 = score.slope(rows, "ophanic@100", ["prose", "list"], lambda r: True, B=300, seed=3)
    assert s1 == score.slope(rows, "ophanic@100", ["prose", "list"], lambda r: True, B=300, seed=3)


def test_bootstrap_point_is_the_paired_difference():
    rows = fake_rows()
    est = score.paired_diff(rows, "ophanic@100", "prose", B=50, seed=0)[0]
    o = [r["correct"] for r in rows if r["encoding"] == "ophanic@100"]
    p = [r["correct"] for r in rows if r["encoding"] == "prose"]
    assert est == pytest.approx(100 * (sum(o) - sum(p)) / len(o))


def test_bootstrap_resamples_whole_structures():
    """If every structure has the same difference, resampling structures can't move it: the interval is a point.
    Resampling calls independently would not give that."""
    rows = []
    for i in range(10):
        for qid, (a, b) in zip(("q0", "q1"), ((True, False), (False, False))):
            for arm, c in (("A", a), ("B", b)):
                rows.append({"task": f"t{i}", "question_id": qid, "model": "m", "encoding": arm, "type": "layout",
                             "size": "small", "correct": c})
    est, lo, hi, n_structs, n_pairs = score.paired_diff(rows, "A", "B", B=200, seed=0)
    assert (est, lo, hi) == (50.0, 50.0, 50.0) and (n_structs, n_pairs) == (10, 20)


def test_slope_statistic_uses_the_better_text_arm():
    # small: ophanic 5/10, prose 7/10, list 6/10 -> advantage -20; large: 9/10 vs 6/10, 8/10 -> +10
    def payload(size, ko, kp, kl):
        return [(size, [int(i < ko), int(i < kp), int(i < kl), 1]) for i in range(10)]
    assert score.slope_stat(payload("small", 5, 7, 6) + payload("large", 9, 6, 8)) == pytest.approx(30.0)
    assert score.slope_stat(payload("small", 5, 7, 6)) is None


def test_hypotheses_section_in_a_pilot_has_no_readings():
    rows = fake_rows()
    text = "\n".join(score.hypotheses(rows, ["ophanic@100", "ophanic-noise@100", "prose", "list"], [], "PILOT 2",
                                      B=100))
    assert "test nothing" in text and "Reading:" not in text
    assert "**H6** (construction): **not run.**" in text
    assert "H1a" in text and "H1b" in text and score.GRAPH_ARM in text
    conf = "\n".join(score.hypotheses(rows, ["ophanic@100", "ophanic-noise@100", "prose", "list"], [],
                                      "CONFIRMATORY", B=100))
    assert "Reading:" in conf


def test_reports_relabel_the_graph_arm():
    assert score.tl("graph") == "graph (ophanic arm: partial-edge list plus picture)"
    assert score.tl("layout") == "layout"


def test_arm_order():
    encs = ["list", "ophanic@100+fenced", "prose", "ophanic@100", "ophanic-noise@100", "json-compact", "json"]
    assert sorted(encs, key=score.enc_key) == ["ophanic@100", "ophanic@100+fenced", "ophanic-noise@100", "prose",
                                               "json", "json-compact", "list"]
    assert score.clean_partner("ophanic-noise@100+fenced") == "ophanic@100+fenced"


def test_no_incoming_scoring():
    q = {"answer_type": "int", "gold": 3}
    assert score.correct(q, "3") and score.correct(q, "3 nodes") and not score.correct(q, "Auth, Store, Cache")


# ---- pilot-2 review (Momus): anthropic safeguards, no-answer handling, per-condition reporting -------------------

def test_anthropic_token_floor_and_effort_pin(tmp_path, monkeypatch):
    monkeypatch.delenv("OPX_ALLOW_PAID", raising=False)
    with pytest.raises(SystemExit) as e:
        run.main(["--tasks", str(tmp_path / "none.jsonl"), "--run", "x", "--model", "claude-haiku-5-5",
                  "--backend", "anthropic", "--max-tokens", "256"])
    assert "--max-tokens 256" in str(e.value)
    with pytest.raises(SystemExit) as e:
        run.main(["--tasks", str(tmp_path / "none.jsonl"), "--run", "x", "--model", "claude-unknown",
                  "--backend", "anthropic"])
    assert "pinned effort" in str(e.value)
    for m in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"):
        assert run.anthropic_body(run_args(model=m), "x")["output_config"] == {"effort": run.EFFORT_PIN[m]}
    assert run.ANTHROPIC_DEFAULT_TOKENS >= run.ANTHROPIC_MIN_TOKENS == 2048


def test_no_answer_is_retried_then_an_error_never_wrong(tasks, tmp_path, monkeypatch):
    """A call that ends while thinking (or with nothing) is retried, then recorded as an error, and the scorer
    leaves it out."""
    calls = []

    def fake(a, text):
        calls.append(text)
        return {"answer": "", "done_reason": "length", "prompt_eval_count": 10, "eval_count": a.max_tokens}
    monkeypatch.setattr(run, "call_ollama", fake)
    monkeypatch.setattr(run, "HERE", tmp_path)
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps(tasks[0]) + "\n")
    run.main(["--tasks", str(path), "--run", "r", "--model", "m", "--think", "--max-tokens", "4096",
              "--encodings", "prose", "--noise-every", "0", "--limit", "1", "--retries", "2"])
    rows = [json.loads(x) for x in (tmp_path / "results" / "r" / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 3 and len(rows) == 1
    assert rows[0]["error"].startswith("no answer after 3 attempts") and "correct" not in rows[0]
    scored, errors = score.load_all([tmp_path / "results" / "r"])
    assert scored == [] and len(errors) == 1
    # a non-thinking answer cut off by the limit is an answer (a looping list), and is scored
    assert not run.is_non_answer(run_args(backend="ollama"), {"answer": "A, B, A, B", "done_reason": "length"})
    assert run.is_non_answer(run_args(backend="anthropic"), {"answer": "A", "done_reason": "max_tokens"})


def test_conditions_are_never_pooled():
    rows = fake_rows()
    thinking = [{**r, "think": True, "correct": not r["correct"]} for r in rows]
    with pytest.raises(ValueError):
        score.hypotheses(rows + thinking, ["ophanic@100", "prose", "list"], [], "PILOT", B=50)
    # pairs never cross conditions: the same task and question under two conditions are two pairs
    assert score.pkey(rows[0]) != score.pkey(thinking[0])
    text = score.report(Path("results/x"), rows + thinking, "PILOT", [], B=50, errors=[])
    assert text.count("# Condition: ") == 2 and "# Condition: m (thinking)" in text


def test_floors_ignore_the_lookup_control():
    rows = fake_rows()
    lookup = [{**r, "encoding": "list-lookup", "correct": True} for r in rows if r["encoding"] == "prose"]
    text = "\n".join(score.review_checks(rows + lookup, ["ophanic@100", "prose", "list", "list-lookup"], []))
    assert "list, list-lookup answered" not in text and "of 108" in text


def test_power_simulation_is_deterministic_and_sane():
    import power
    diffs = [0.5, -0.5, 0.0, 1.0, -1.0, 0.0, 0.5, 0.0]
    a = power.simulate(diffs, 40, 20, power.meets, 300, random.Random(4))
    b = power.simulate(diffs, 40, 20, power.meets, 300, random.Random(4))
    assert a == b
    assert power.simulate(diffs, 40, 0, power.meets, 300, random.Random(4)) < 0.1 < a
    assert power.within(0, -1, 1) and not power.within(-4, -6, -2)
