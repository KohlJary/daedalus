"""
`daedalus oph map <subject>` (edict 0017): Daedalus's own state as graphs for the one renderer (render.draw).

Each map returns the graph format render.draw takes, from the same library functions the CLI uses:
- `edicts`: edicts and their `Depends on:` edges; external dependencies in the box's detail line;
- `plan`: phases as boxes, the active phase's tasks inside it, edicts as the phase's tag;
- `workstreams`: workstreams holding their claims; each collision a `█C` box pointing at the two workstreams;
- `intake`: sources, then roadmap items by origin, then the phases that pull them in.
"""

from __future__ import annotations

from pathlib import Path

STATUS_MARK = {"done": "done", "in_progress": ">", "pending": " ", "planned": "planned", "accepted": "accepted",
               "proposed": "proposed"}
TASK_MARK = {"done": "x", "in_progress": ">", "pending": " "}


def edicts_graph(project_dir: Path) -> dict:
    from ..doctor import load_edicts
    from ..edicts import EdictError, depends_on, load_edict

    nodes, edges = [], []
    for e in load_edicts(project_dir):
        try:
            ed = load_edict(project_dir, e["number"])
        except EdictError:
            continue
        deps, external = depends_on(ed)
        node = {"id": ed.number, "label": ed.title, "kind": "E", "mark": ed.status or "?"}
        if external:
            node["detail"] = "also: " + "; ".join(external)
        nodes.append(node)
        # Every dependency, including one on an edict that doesn't exist: the renderer lists it as missing
        edges += [{"from": ed.number, "to": d} for d in deps]
    return {"title": "Edicts: each box points at the edicts it depends on", "nodes": nodes, "edges": edges}


def plan_graph(project_dir: Path, workstream: str | None = None) -> dict:
    from ..cli import gameplan as gp

    try:
        data = gp.load_gameplan(project_dir, workstream)
    except gp.GameplanError:
        data = {}
    active = data.get("activePhase") or {}
    nodes, edges = [], []
    for i, phase in enumerate(data.get("phases", [])):
        pid = f"{i + 1:02d}-{phase['id']}"
        node = {"id": pid, "label": phase.get("title", phase["id"]), "kind": "P",
                "mark": STATUS_MARK.get(phase.get("status"), phase.get("status"))}
        if phase.get("edict"):
            node["detail"] = f"edict {phase['edict']}"
        nodes.append(node)
        tasks = active.get("tasks", []) if active.get("id") == phase["id"] else phase.get("tasks") or []
        for t in tasks:
            if isinstance(t, dict) and t.get("status") != "done":
                nodes.append({"id": t["id"], "label": t.get("title", ""), "kind": "T", "parent": pid,
                              "mark": TASK_MARK.get(t.get("status"), " ")})
        done = sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "done")
        if done:
            nodes.append({"id": "~done", "label": f"and {done} done", "kind": "T", "parent": pid})
    return {"title": "Gameplan: phases in plan order; open tasks inside the active phase", "nodes": nodes,
            "edges": edges}


def workstreams_graph(project_dir: Path) -> dict:
    """Workstreams as boxes holding their path claims. Each collision doctor finds (`doctor.collisions`) is a `█C`
    box labelled "collides", pointing at the two workstreams it involves: the arrow means "involves", as it means
    "points at" everywhere, so a collision is never drawn as one workstream depending on another."""
    from .. import workstreams as ws
    from ..doctor import collisions

    nodes, edges = [], []
    plans: dict = {}
    for wid in ws.list_ids(project_dir):
        try:
            data = ws.load(project_dir, wid)
        except ws.WorkstreamError:
            continue
        plans[wid] = data
        nodes.append({"id": wid, "label": f"{wid} ({ws.owner(data, wid).get('kind', '')})", "kind": "W",
                      "detail": ws.summary_line(data, wid).split(":", 1)[-1].strip()})
        for k, claim in enumerate(data.get("claims", []) or []):
            nodes.append({"id": f"~{wid}-claim-{k:04d}", "label": f"claim {claim}", "kind": "C", "parent": wid})
    for k, (kind, a, b, detail) in enumerate(collisions(plans), 1):
        what = f"edict {detail}" if kind == "edict" else f"paths {detail}"
        cid = f"collision-{k:03d}"
        nodes.append({"id": cid, "label": f"{a} collides with {b}", "kind": "C", "detail": what})
        edges += [{"from": cid, "to": a}, {"from": cid, "to": b}]
    return {"title": "Workstreams and their claims; a collision is a box of its own, pointing at both workstreams",
            "nodes": nodes, "edges": edges}


def intake_graph(project_dir: Path) -> dict:
    from .. import roadmap
    from ..cli import gameplan as gp

    try:
        items = roadmap.load_index(project_dir).get("items", [])
    except roadmap.RoadmapError:
        items = []
    try:
        phases = gp.load_gameplan(project_dir).get("phases", [])
    except gp.GameplanError:
        phases = []
    nodes, edges = [], []
    sources = sorted({roadmap.origin(i)["source"] for i in items})
    for s in sources:
        nodes.append({"id": f"source-{s}", "label": s, "kind": "S"})
    for p in phases:
        if p.get("roadmapItems"):
            nodes.append({"id": f"phase-{p['id']}", "label": p.get("title", p["id"]), "kind": "P",
                          "mark": STATUS_MARK.get(p.get("status"), p.get("status"))})
    placed = {i for p in phases for i in (p.get("roadmapItems") or [])}
    waiting = 0
    for i in items:
        src = f"source-{roadmap.origin(i)['source']}"
        if i["id"] in placed:
            nodes.append({"id": i["id"], "label": i.get("title", ""), "kind": "R", "mark": i.get("status")})
            edges.append({"from": src, "to": i["id"]})
            for p in phases:
                if i["id"] in (p.get("roadmapItems") or []):
                    edges.append({"from": i["id"], "to": f"phase-{p['id']}"})
        else:
            waiting += 1
            nodes.append({"id": i["id"], "label": i.get("title", ""), "kind": "R", "parent": src,
                          "mark": i.get("status")})
    title = "Intake: sources hold the items no phase has pulled in yet; placed items point at their phase"
    return {"title": title + ("" if items else " (the roadmap is empty)"), "nodes": nodes, "edges": edges}


MAPS = {"edicts": edicts_graph, "plan": plan_graph, "workstreams": workstreams_graph, "intake": intake_graph}
