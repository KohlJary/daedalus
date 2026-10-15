"""
The dream review (edict 0013, amended F7): ideas that keep coming back across dreams.

The model's only job is grouping: which ideas say the same thing. Everything that decides something is
code:
- the bundle (every idea since the last review, plus the ideas of earlier themes, the roadmap and the plan);
- verifying that every idea and roadmap ID a theme names exists (a theme naming an unknown ID is dropped);
- counting distinct dreams, and distinct top seeds, per theme;
- theme IDs: a theme takes the ID of the earlier theme it shares the most idea IDs with, or a new one;
- elevation: at least dream.recur_min dreams that don't share a top seed, and nothing applied covers it.

The review agent is not told recur_min.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from ..reflection.fsutil import atomic_write_text, read_json, write_json
from . import store

REVIEW_PROMPT = """Below are ideas from several dreams, each with an ID. Some say the same thing in
different words. Group the ideas that are the same idea into themes. An idea belongs to at most one theme.
Leave ideas that match nothing ungrouped.

For each theme, also say whether something already planned covers it: give the ID of a roadmap item,
phase or task from the plan below that does, or null.

Answer with JSON only, in this shape:
{{"themes": [{{"title": "...", "summary": "one sentence", "ideas": ["<idea id>", ...], "integrated_by": null}}]}}

Ideas:
{ideas}

The roadmap and the plan (ID: title):
{plan}"""


def reviews_dir(project_dir: Path) -> Path:
    return store.dreams_dir(project_dir) / "reviews"


def themes_path(project_dir: Path) -> Path:
    return store.dreams_dir(project_dir) / "themes.json"


def load_themes(project_dir: Path) -> dict:
    data = read_json(themes_path(project_dir), {}) or {}
    data.setdefault("themes", {})
    data.setdefault("last_review_dream", None)
    return data


def dreams_since_last_review(project_dir: Path) -> list[str]:
    last = load_themes(project_dir).get("last_review_dream")
    done = [i for i in store.list_dreams(project_dir) if store.load_meta(project_dir, i).get("status") == "done"]
    return [i for i in done if last is None or store.list_dreams(project_dir).index(i) >
            (store.list_dreams(project_dir).index(last) if last in store.list_dreams(project_dir) else -1)]


def review_due(project_dir: Path, settings: dict) -> bool:
    return len(dreams_since_last_review(project_dir)) >= int(settings.get("review_min", 4))


def _plan_ids(project_dir: Path) -> dict[str, dict]:
    """Every roadmap item, phase and task: {id: {title, kind, source}}."""
    from .. import roadmap
    from .. import workstreams as ws
    from ..cli import gameplan as gp

    out: dict[str, dict] = {}
    try:
        for item in roadmap.load_index(project_dir).get("items", []):
            out[item["id"]] = {"title": item.get("title", ""), "kind": "roadmap", "source": roadmap.origin(item)["source"],
                               "status": item.get("status")}
    except roadmap.RoadmapError:
        pass
    for wid in ws.list_ids(project_dir):
        try:
            data = gp.load_gameplan(project_dir, wid)
        except gp.GameplanError:
            continue
        for phase in data.get("phases", []):
            out.setdefault(phase["id"], {"title": phase.get("title", ""), "kind": "phase"})
        for _, task in roadmap.all_tasks(data):
            out.setdefault(task["id"], {"title": task.get("title", ""), "kind": "task"})
    return out


def build_bundle(project_dir: Path) -> dict:
    themes = load_themes(project_dir)
    new = dreams_since_last_review(project_dir)
    ideas: dict[str, str] = {}
    for dream_id in new:
        for idea in store.ideas(project_dir, dream_id):
            ideas[idea["id"]] = idea["text"]
    # Earlier themes' ideas come along, so a theme can keep growing across reviews
    for theme in themes["themes"].values():
        for iid in theme.get("ideas", []):
            dream_id = iid.rsplit(".", 1)[0]
            if iid not in ideas:
                try:
                    match = next((i for i in store.ideas(project_dir, dream_id) if i["id"] == iid), None)
                except store.DreamError:
                    match = None
                if match:
                    ideas[iid] = match["text"]
    plan = _plan_ids(project_dir)
    return {"dreams": new, "ideas": ideas, "plan": {k: v["title"] for k, v in plan.items()},
            "date": date.today().isoformat()}


def prompt(bundle: dict) -> str:
    ideas = "\n".join(f"- {iid}: {text}" for iid, text in sorted(bundle["ideas"].items()))
    plan = "\n".join(f"- {k}: {v}" for k, v in sorted(bundle["plan"].items())) or "(nothing planned)"
    return REVIEW_PROMPT.format(ideas=ideas, plan=plan)


def _top_seed(project_dir: Path, dream_id: str) -> Optional[str]:
    seeds = (read_json(store.dream_dir(project_dir, dream_id) / "seeds.json", {}) or {}).get("seeds", [])
    return seeds[0]["id"] if seeds else None


def record(project_dir: Path, bundle: dict, answer: Any, settings: dict, today: Optional[date] = None) -> dict:
    """Check the agent's grouping, count, assign theme IDs, decide elevation, and write the review."""
    today = today or date.today()
    recur_min = int(settings.get("recur_min", 3))
    if isinstance(answer, str):
        answer = json.loads(answer)
    proposed = (answer or {}).get("themes") if isinstance(answer, dict) else None
    if not isinstance(proposed, list):
        raise store.DreamError('The review answer must be {"themes": [...]}')
    plan = _plan_ids(project_dir)
    registry = load_themes(project_dir)
    known = set(bundle["ideas"])
    used: set[str] = set()
    kept, dropped = [], []
    for t in proposed:
        ids = [i for i in (t.get("ideas") or []) if isinstance(i, str)]
        unknown = [i for i in ids if i not in known]
        covered = t.get("integrated_by")
        if unknown or (covered and covered not in plan) or not ids:
            dropped.append({"title": str(t.get("title", ""))[:80], "unknown": unknown + ([covered] if covered and covered not in plan else [])})
            continue
        ids = [i for i in ids if i not in used]
        used |= set(ids)
        # Only something applied covers a theme. Pending proposals aren't in the roadmap or the plan, so
        # anything `plan` holds is applied: a dream pick that is still pending covers nothing.
        integrated = covered or None
        best, overlap = None, 0
        for tid, old in registry["themes"].items():
            n = len(set(old.get("ideas", [])) & set(ids))
            if n > overlap:
                best, overlap = tid, n
        tid = best or f"t{len(registry['themes']) + 1 + len([k for k in kept if k['new']])}"
        old = registry["themes"].get(tid, {})
        all_ids = sorted(set(old.get("ideas", [])) | set(ids))
        all_dreams = sorted({i.rsplit(".", 1)[0] for i in all_ids})
        all_tops = sorted({_top_seed(project_dir, d) or d for d in all_dreams})
        kept.append({"id": tid, "new": best is None, "title": str(t.get("title", ""))[:120],
                     "summary": str(t.get("summary", ""))[:300], "ideas": all_ids, "dreams": len(all_dreams),
                     "distinct_top_seeds": len(all_tops), "integrated_by": integrated,
                     "elevated": len(all_tops) >= recur_min and len(all_dreams) >= recur_min and not integrated,
                     "independent": len(all_tops) == len(all_dreams)})
    for t in kept:
        registry["themes"][t["id"]] = {k: v for k, v in t.items() if k != "new"} | {
            "first_review": registry["themes"].get(t["id"], {}).get("first_review", today.isoformat()),
            "last_review": today.isoformat()}
    if bundle["dreams"]:
        registry["last_review_dream"] = bundle["dreams"][-1]
    write_json(themes_path(project_dir), registry)
    name = today.isoformat()
    n = 2
    while (reviews_dir(project_dir) / f"{name}.md").exists():
        name, n = f"{today.isoformat()}-{n}", n + 1
    atomic_write_text(reviews_dir(project_dir) / f"{name}.md", render(kept, dropped, recur_min, name))
    store.log(project_dir, {"record": "review", "review": name, "dreams": len(bundle["dreams"]),
                            "themes": len(kept), "recurring": sum(1 for t in kept if t["dreams"] >= recur_min),
                            "elevated": sum(1 for t in kept if t["elevated"])})
    return {"review": name, "themes": kept, "dropped": dropped}


def render(themes: list[dict], dropped: list[dict], recur_min: int, name: str) -> str:
    lines = [store.LABEL.rstrip(), "", f"# Dream review {name}", "",
             "How often an idea came back says nothing about whether it's right.", ""]
    for t in sorted(themes, key=lambda t: (-t["distinct_top_seeds"], t["id"])):
        state = ("elevated: proposed through the dream source" if t["elevated"] else
                 f"covered by {t['integrated_by']}" if t["integrated_by"] else
                 f"below {recur_min} dreams with different top seeds")
        indep = "" if t["independent"] else " (some dreams shared a top seed)"
        lines += [f"## {t['id']}: {t['title']}", "", t["summary"], "",
                  f"- In {t['dreams']} dream(s), {t['distinct_top_seeds']} distinct top seed(s){indep}",
                  f"- {state}", f"- Ideas: {', '.join(t['ideas'])}", ""]
    if dropped:
        lines += ["## Dropped from this review", ""]
        lines += [f"- {d['title'] or '(untitled)'}: names unknown IDs {', '.join(map(str, d['unknown']))}" for d in dropped]
    return "\n".join(lines) + "\n"


def elevated(project_dir: Path) -> list[dict]:
    return [{"id": tid, **t} for tid, t in sorted(load_themes(project_dir)["themes"].items()) if t.get("elevated")]
