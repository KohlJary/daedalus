"""
Reading the dream experiment back (edict 0013): per mode, how many picks were synced, applied and
built, against the build rate of everything else in the roadmap. Joined with the roadmap's state when
read, so an outcome that happens later never needs a record rewritten.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median

from .. import roadmap
from . import store


def summary(project_dir: Path) -> list[str]:
    records = store.load_log(project_dir)
    runs = [r for r in records if r.get("record") == "run"]
    if not runs:
        return ["No dreams finished yet."]
    mode_of = {r["dream"]: r.get("mode") for r in records if r.get("record") in ("start", "run")}
    outcomes: dict[str, str] = {}
    for r in records:
        if r.get("record") == "resolution" and r.get("item"):
            outcomes[r["item"]] = r["outcome"]  # the latest outcome wins
    try:
        items = roadmap.load_index(project_dir).get("items", [])
    except roadmap.RoadmapError:
        items = []
    built_at = {}
    for item in items:
        o = roadmap.origin(item)
        if o["source"] == "dream" and item.get("status") == "done":
            built_at[str(o.get("external_id"))] = item.get("status_changed_at")

    per = defaultdict(Counter)
    days = defaultdict(list)
    for r in runs:
        per[r.get("mode")]["dreams"] += 1
        per[r.get("mode")]["picks"] += int(r.get("picks") or 0)
        per[r.get("mode")]["truncated"] += bool(r.get("truncated"))
    for ext, outcome in outcomes.items():
        m = store.ITEM_ID.match(ext)
        if not m or m.group(2) != "p":
            continue
        mode = mode_of.get(m.group(1))
        per[mode][outcome] += 1
        if ext in built_at:
            per[mode]["built"] += 1
            try:
                days[mode].append((date.fromisoformat(str(built_at[ext])[:10]) - date.fromisoformat(m.group(1)[:10])).days)
            except ValueError:
                pass

    lines = ["Dreams per mode (picks: synced / applied / dropped / built):"]
    for mode in sorted(per, key=str):
        c = per[mode]
        applied_share = f"{c['applied'] / c['picks']:.0%}" if c["picks"] else "-"
        built_share = f"{c['built'] / c['applied']:.0%}" if c["applied"] else "-"
        med = f", median {median(days[mode]):.0f} days to done" if days[mode] else ""
        lines.append(f"  {mode}: {c['dreams']} dream(s), {c['picks']} picks; {c['synced']} / {c['applied']} / "
                     f"{c['dropped']} / {c['built']}; applied {applied_share} of picks, built {built_share} of "
                     f"applied{med}" + (f"; {c['truncated']} truncated" if c["truncated"] else ""))
    others = [i for i in items if roadmap.origin(i)["source"] != "dream"]
    if others:
        done = sum(1 for i in others if i.get("status") == "done")
        lines.append(f"Baseline: non-dream roadmap items built {done}/{len(others)} ({done / len(others):.0%}).")
    reviews = [r for r in records if r.get("record") == "review"]
    if reviews:
        lines.append(f"Reviews: {len(reviews)}; themes elevated {sum(int(r.get('elevated') or 0) for r in reviews)}.")
    lines.append("Whether dreaming beats its baseline is untested until each mode has enough dreams (the benchmark sets how many).")
    return lines
