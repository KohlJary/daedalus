"""Score staged Claude runs against the hidden oracles and append them to results/claude.jsonl.
  python3 score_claude.py solo <task> <subagent_tokens> <tool_uses> <secs>
  python3 score_claude.py review <task> <subagent_tokens> <tool_uses> <secs>   (validates + installs the reviewed plan)"""
import json, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "gate_exp"))
import mature_exp as m
from oracle import run_oracle
kind, task, toks, tools, secs = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
rec = dict(kind=kind, task=task, subagent_tokens=toks, tool_uses=tools, secs=secs)
if kind == "solo":
    r = run_oracle(HERE / "claude" / "solo" / task / "project", m.FEATURES[task]["oracle"])
    rec.update(oracle_pass=r["oracle_pass"], oracle_tests=r["oracle_tests"], regressions=r["regressions"], summary=r["summary"])
    print(task, "oracle", r["oracle_pass"], r["summary"], r["regressions"][:3])
else:
    reviewed = json.loads((HERE / "claude" / "review" / task / "reviewed.json").read_text())
    ids = [p["id"] for p in reviewed["packages"]]
    problems = [f"{p['id']}: unknown dep {d}" for p in reviewed["packages"] for d in p["depends_on"] if d not in ids]
    rec.update(verdict=reviewed.get("verdict"), notes=reviewed.get("notes"), problems=problems)
    if not problems:
        (HERE / "results" / "plans").mkdir(parents=True, exist_ok=True)
        shutil.copy(HERE / "claude" / "review" / task / "reviewed.json", HERE / "results" / "plans" / f"{task}.reviewed.json")
    print(task, reviewed.get("verdict"), "problems:", problems or "none", "-> installed" if not problems else "")
with open(HERE / "results" / "claude.jsonl", "a") as f:
    f.write(json.dumps(rec) + "\n")
