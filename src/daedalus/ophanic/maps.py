"""
`daedalus oph map <subject>` (edict 0017): Daedalus's own state as graphs for the one renderer (render.draw).

Each map returns the graph format render.draw takes, from the same library functions the CLI uses:
- `edicts`: edicts and their `Depends on:` edges; external dependencies in the box's detail line;
- `plan`: phases as boxes, the active phase's tasks inside it, edicts as the phase's tag;
- `workstreams`: workstreams holding their claims; collisions as listed edges;
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
    numbers = {e["number"] for e in load_edicts(project_dir)}
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
        edges += [{"from": ed.number, "to": d} for d in deps if d in numbers]
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
    from .. import workstreams as ws

    nodes, edges = [], []
    owners: dict[str, list[str]] = {}
    for wid in ws.list_ids(project_dir):
        try:
            data = ws.load(project_dir, wid)
        except ws.WorkstreamError:
            continue
        nodes.append({"id": wid, "label": ws.owner(data, wid).get("kind", ""), "kind": "W",
                      "detail": ws.summary_line(data, wid).split(":", 1)[-1].strip()})
        for claim in ws.owner(data, wid).get("claims", []) or data.get("claims", []) or []:
            nodes.append({"id": f"{wid}:{claim}", "label": "", "kind": "C", "parent": wid})
            owners.setdefault(wid, []).append(claim)
    ids = sorted(owners)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if any(ws.claims_overlap(x, y) for x in owners[a] for y in owners[b]):
                edges.append({"from": a, "to": b, "label": "claims overlap"})
    return {"title": "Workstreams and their claims; overlapping claims are listed below", "nodes": nodes,
            "edges": edges}


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
