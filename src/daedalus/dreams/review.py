"""
The dream review (edict 0013, amended F7): ideas that keep coming back across dreams.

The model's only job is grouping: which ideas say the same thing. Everything that decides something is
code:
- the bundle (every idea since the last review, plus the ideas of earlier themes, the roadmap and the plan);
- verifying that every idea and roadmap ID a theme names exists (a theme naming an unknown ID is dropped);
- counting distinct dreams, and distinct seed sets (order-free), per theme;
- an idea named by two themes stays with the first; a theme left with no ideas is dropped, not written;
- theme IDs: a theme takes the ID of the earlier theme it shares the most idea IDs with, or a new one. An
  earlier ID goes to at most one theme per review: when several themes overlap the same earlier theme,
  the largest overlap keeps the ID (ties: the one listed first), and the rest get new IDs with only their
  own ideas. The theme keeping an ID inherits the earlier theme's ideas, except those another theme in
  this review claimed;
- earlier themes this review didn't reproduce (merged or renamed away) are kept but superseded: `elevated`
  false, `superseded` true, and `superseded_by` the theme now holding one of their ideas, if any;
- elevation: at least dream.recur_min dreams with different seed sets, and nothing applied covers it.

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


def _seed_set(project_dir: Path, dream_id: str) -> Optional[str]:
    """The dream's seeds as an order-free signature, or None when it had none."""
    seeds = (read_json(store.dream_dir(project_dir, dream_id) / "seeds.json", {}) or {}).get("seeds", [])
    return "|".join(sorted(s["id"] for s in seeds)) if seeds else None


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
    valid, dropped = [], []
    for t in proposed:
        title = str(t.get("title", ""))[:80]
        ids = [i for i in (t.get("ideas") or []) if isinstance(i, str)]
        unknown = [i for i in ids if i not in known]
        covered = t.get("integrated_by")
        if unknown or (covered and covered not in plan) or not ids:
            dropped.append({"title": title, "unknown": unknown + ([covered] if covered and covered not in plan else []),
                            "reason": "unknown" if unknown or (covered and covered not in plan) else "empty"})
            continue
        ids = list(dict.fromkeys(i for i in ids if i not in used))  # an idea stays with the first theme
        if not ids:
            dropped.append({"title": title, "unknown": [], "reason": "empty"})
            continue
        used |= set(ids)
        valid.append((t, ids, covered or None))

    # Each earlier theme ID is claimed at most once: largest overlap first, then the order themes were listed
    pairs = sorted(((len(set(old.get("ideas", [])) & set(ids)), n, tid)
                    for n, (_, ids, _) in enumerate(valid) for tid, old in registry["themes"].items()),
                   key=lambda x: (-x[0], x[1], x[2]))
    claimed: dict[int, str] = {}
    for overlap, n, tid in pairs:
        if overlap and n not in claimed and tid not in claimed.values():
            claimed[n] = tid
    numbers = [int(k[1:]) for k in registry["themes"] if k[:1] == "t" and k[1:].isdigit()]
    next_n = max(numbers, default=0) + 1

    kept = []
    for n, (t, ids, integrated) in enumerate(valid):
        tid = claimed.get(n)
        if tid is None:
            tid, next_n = f"t{next_n}", next_n + 1
        old = registry["themes"].get(tid, {}) if n in claimed else {}
        # Ideas this theme inherits: the earlier theme's, less any another theme claimed in this review
        all_ids = sorted(set(ids) | (set(old.get("ideas", [])) - (used - set(ids))))
        all_dreams = sorted({i.rsplit(".", 1)[0] for i in all_ids})
        # Independence is by seed *set*, not top seed: the same seeds in another order (the recency penalty
        # rotates the top seed on unchanged state) are the same material, so they count once (Momus N1)
        all_tops = sorted({_seed_set(project_dir, d) or d for d in all_dreams})
        # Only something applied covers a theme. Pending proposals aren't in the roadmap or the plan, so
        # anything `plan` holds is applied: a dream pick that is still pending covers nothing.
        kept.append({"id": tid, "new": n not in claimed, "title": str(t.get("title", ""))[:120],
                     "summary": str(t.get("summary", ""))[:300], "ideas": all_ids, "dreams": len(all_dreams),
                     "distinct_top_seeds": len(all_tops), "integrated_by": integrated,
                     "elevated": len(all_tops) >= recur_min and len(all_dreams) >= recur_min and not integrated,
                     "independent": len(all_tops) == len(all_dreams)})
    for t in kept:
        registry["themes"][t["id"]] = {k: v for k, v in t.items() if k != "new"} | {
            "first_review": registry["themes"].get(t["id"], {}).get("first_review", today.isoformat()),
            "last_review": today.isoformat(), "superseded": False, "superseded_by": None}
    # Earlier themes this review didn't reproduce stop being elevated
    reproduced = {t["id"] for t in kept}
    holder = {i: t["id"] for t in kept for i in t["ideas"]}
    superseded = []
    for tid, old in registry["themes"].items():
        if tid in reproduced:
            continue
        by = next((holder[i] for i in old.get("ideas", []) if i in holder), None)
        if old.get("elevated") or not old.get("superseded") or by:
            old.update(elevated=False, superseded=True, superseded_by=by or old.get("superseded_by"))
            superseded.append({"id": tid, "title": old.get("title", ""), "by": old["superseded_by"]})
    if bundle["dreams"]:
        registry["last_review_dream"] = bundle["dreams"][-1]
    write_json(themes_path(project_dir), registry)
    name = today.isoformat()
    n = 2
    while (reviews_dir(project_dir) / f"{name}.md").exists():
        name, n = f"{today.isoformat()}-{n}", n + 1
    atomic_write_text(reviews_dir(project_dir) / f"{name}.md", render(kept, dropped, recur_min, name, superseded))
    store.log(project_dir, {"record": "review", "review": name, "dreams": len(bundle["dreams"]),
                            "themes": len(kept), "recurring": sum(1 for t in kept if t["dreams"] >= recur_min),
                            "elevated": sum(1 for t in kept if t["elevated"])})
    return {"review": name, "themes": kept, "dropped": dropped, "superseded": superseded}


def render(themes: list[dict], dropped: list[dict], recur_min: int, name: str,
           superseded: Optional[list[dict]] = None) -> str:
    lines = [store.LABEL.rstrip(), "", f"# Dream review {name}", "",
             "How often an idea came back says nothing about whether it's right.", ""]
    for t in sorted(themes, key=lambda t: (-t["distinct_top_seeds"], t["id"])):
        state = ("elevated: proposed through the dream source" if t["elevated"] else
                 f"covered by {t['integrated_by']}" if t["integrated_by"] else
                 f"below {recur_min} dreams with different top seeds")
        indep = "" if t["independent"] else " (some dreams shared their seeds)"
        lines += [f"## {t['id']}: {t['title']}", "", t["summary"], "",
                  f"- In {t['dreams']} dream(s), {t['distinct_top_seeds']} distinct seed set(s){indep}",
                  f"- {state}", f"- Ideas: {', '.join(t['ideas'])}", ""]
    if superseded:
        lines += ["## Earlier themes this review didn't reproduce (no longer elevated)", ""]
        lines += [f"- {s['id']}: {s['title']}" + (f" (its ideas are now in {s['by']})" if s["by"] else "")
                  for s in superseded]
        lines.append("")
    if dropped:
        lines += ["## Dropped from this review", ""]
        lines += [f"- {d['title'] or '(untitled)'}: " + (f"names unknown IDs {', '.join(map(str, d['unknown']))}"
                  if d.get("reason") != "empty" else "no ideas of its own (each was already in another theme)")
                  for d in dropped]
    return "\n".join(lines) + "\n"


def elevated(project_dir: Path) -> list[dict]:
    return [{"id": tid, **t} for tid, t in sorted(load_themes(project_dir)["themes"].items()) if t.get("elevated")]
