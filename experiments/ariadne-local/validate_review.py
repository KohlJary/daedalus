"""Validate a reviewer's plan (schema, dependency DAG) and install it as condition E's plan."""
import json, sys, shutil
from pathlib import Path
name = sys.argv[1]
src = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("review_inputs") / name / "reviewed.json"
suffix = sys.argv[3] if len(sys.argv) > 3 else "reviewed"
r = json.loads(src.read_text())
pk = r["packages"]
ids = [p["id"] for p in pk]
problems = []
for p in pk:
    for k in ("id", "title", "files", "description", "depends_on"):
        if k not in p: problems.append(f"{p.get('id')}: missing {k}")
    for d in p.get("depends_on", []):
        if d not in ids: problems.append(f"{p['id']}: unknown dep {d}")
done, left = set(), {p["id"]: set(p["depends_on"]) for p in pk}
while True:
    ready = [i for i, d in left.items() if d <= done]
    if not ready: break
    for i in ready: done.add(i); left.pop(i)
if left: problems.append(f"cycle: {sorted(left)}")
# same-file packages must be ordered (one an ancestor of the other)
anc = {}
def ancestors(i):
    if i not in anc:
        anc[i] = set()
        for d in next(p for p in pk if p["id"] == i)["depends_on"]:
            anc[i] |= {d} | ancestors(d)
    return anc[i]
for a in pk:
    for b in pk:
        if a["id"] < b["id"] and set(a["files"]) & set(b["files"]) and a["id"] not in ancestors(b["id"]) and b["id"] not in ancestors(a["id"]):
            problems.append(f"{a['id']} and {b['id']} share {set(a['files']) & set(b['files'])} and can run in parallel")
print(name, r.get("verdict"), len(pk), "packages", [(p["id"], p["files"], p["depends_on"]) for p in pk])
print("problems:", problems or "none")
if not problems:
    shutil.copy(src, Path("gate_exp/results/plans") / f"{name}.{suffix}.json"); print("installed")
