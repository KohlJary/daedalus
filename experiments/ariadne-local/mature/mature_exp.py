"""Mature-codebase run: the real daedalus repo (snapshot in base/), real gameplan tasks, local models.

Reuses gate_exp/feature.py's real Ariadne path (Planner -> Dispatcher -> IcarusWorker harness with worktrees
-> AriadneOrchestrator with the real verifier and a local judge), swapping in:
  - mature_worker.work_mature (ranged reads, search, exact edits) for every condition
  - a 32k context
  - oracle.run_oracle (original suite + hidden oracle module) for scoring
  - a retrieval-based planner input (interface summaries of the files the task's identifiers point to)
The planner prompt text is feature.PLANNER_PROMPT, unchanged (frozen after the toy runs).

  python3 mature_exp.py --reps 3                      # local conditions
  python3 mature_exp.py --conditions ariadne+llmplan+review   # after Claude reviews are installed (RUNBOOK.md)
"""
import argparse, json, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "gate_exp"))
import exp, feature, interfaces  # noqa: E402
from mature_tasks import TASKS  # noqa: E402
from mature_worker import work_mature  # noqa: E402
import oracle as mature_oracle  # noqa: E402

BASE = HERE / "base"
RESULTS = HERE / "results"
CONFTEST = ("# experiment fixture: test this tree's src, not the editable install of the real repo\n"
            "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))\n")


def make_mature_repo(_files=None) -> Path:
    repo = Path(tempfile.mkdtemp(prefix="mature-")) / "project"
    shutil.copytree(BASE, repo)
    (repo / "conftest.py").write_text(CONFTEST)
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(["git", *c], cwd=repo, check=True, capture_output=True)
    return repo


def retrieve(repo: Path, text: str, cap: int = 8) -> list:
    """Files a planner should see: backticked paths, then files defining backticked identifiers, then
    files mentioning them. A stand-in for real code search; same for every planned condition."""
    found = []
    for tok in re.findall(r"`([^`]+)`", text):
        tok = tok.strip()
        if "/" in tok and (repo / tok).is_file():
            found.append(tok)
            continue
        ident = re.match(r"[A-Za-z_][A-Za-z0-9_]*", tok.split(".")[-1] if "." in tok and " " not in tok else tok.split()[0] if tok.split() else "")
        if not ident or len(ident.group(0)) < 4:
            continue
        name = ident.group(0)
        r = subprocess.run(["grep", "-rlE", f"(class|def) {name}\\b", "src"], cwd=repo, capture_output=True, text=True)
        hits = r.stdout.split() or subprocess.run(["grep", "-rlw", name, "src"], cwd=repo, capture_output=True, text=True).stdout.split()[:2]
        found += hits
    out = []
    for f in found:
        if f not in out and f.endswith(".py"):
            out.append(f)
    return out[:cap]


def mature_plan(planner_model, feat, repo):
    files = retrieve(repo, feat["description"])
    summary = interfaces.summarize({f: (repo / f).read_text() for f in files})
    listing = "\n".join(str(p.relative_to(repo)) for p in sorted(repo.rglob("*.py"))
                        if ".git" not in p.parts and "__pycache__" not in p.parts)
    files_block = (f"### Interface summaries of the most relevant modules ({', '.join(files)})\n{summary}\n\n"
                   f"### All Python files (workers can search and read any of them)\n{listing}")
    prompt = feature.PLANNER_PROMPT.format(title=feat["title"], description=feat["description"], files=files_block)
    t0 = time.time()
    import httpx
    r = httpx.post(f"{exp.OLLAMA}/api/chat", timeout=1800, json={
        "model": planner_model, "stream": False, "format": feature.PLAN_SCHEMA,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"num_ctx": exp.NUM_CTX, "temperature": 0}})
    exp.record_usage(f"{planner_model} (planner)", r.json(), len(prompt))
    raw = json.loads(r.json()["message"]["content"])["packages"]
    ids = [p["id"] for p in raw]
    fixups = []
    for p in raw:
        bad = [d for d in p["depends_on"] if d not in ids or d == p["id"]]
        if bad:
            fixups.append(f"{p['id']}: dropped unknown deps {bad}")
            p["depends_on"] = [d for d in p["depends_on"] if d not in bad]
    return raw, fixups + [f"retrieved: {files}"], round(time.time() - t0, 1)


def install():
    """Point feature.py's conditions at the mature pieces."""
    exp.NUM_CTX = 32768
    feature.work = work_mature
    feature.make_repo = make_mature_repo
    feature.run_oracle = lambda repo, src: mature_oracle.run_oracle(Path(repo), src)
    feature.llm_plan = mature_plan
    feature.PLANS = RESULTS / "plans"


FEATURES = {name: dict(name=name, title=t["title"], description=t["description"], oracle=t["oracle"], files=None)
            for name, t in TASKS.items()}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", default="qwen3:8b")
    ap.add_argument("--judge", default="qwen3-coder:30b")
    ap.add_argument("--planner", default="qwen3-coder:30b")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--tasks", default=",".join(FEATURES))
    ap.add_argument("--conditions", default="single,ariadne,ariadne+req,ariadne+llmplan")
    ap.add_argument("--out", default=str(RESULTS / "mature.jsonl"))
    a = ap.parse_args()
    install()
    RESULTS.mkdir(exist_ok=True)
    done = {(r["feature"], r["condition"], r["rep"]) for r in exp.load(Path(a.out))}
    for rep in range(1, a.reps + 1):
        for name in a.tasks.split(","):
            for cond in a.conditions.split(","):
                if (name, cond, rep) in done:
                    continue
                feat, t0 = FEATURES[name], time.time()
                exp.USAGE.clear()
                try:
                    rec = (feature.run_single(feat, a.worker, a.judge) if cond == "single"
                           else feature.run_ariadne(feat, a.worker, a.judge, cond, a.planner))
                except Exception as e:  # record and move on; one broken run shouldn't stop the night
                    rec = dict(condition=cond, error=f"{type(e).__name__}: {e}", oracle_pass=False, oracle_tests={})
                rec.update(feature=name, rep=rep, worker=a.worker, judge=a.judge, secs=round(time.time() - t0),
                           usage={m: dict(u) for m, u in exp.USAGE.items()})
                exp.append(Path(a.out), rec)
                passed = sum(v == "PASSED" for v in rec.get("oracle_tests", {}).values())
                print(f"rep{rep} {name:14} {cond:16} oracle={rec['oracle_pass']!s:5} ({passed}/{len(rec.get('oracle_tests', {}))}) "
                      f"regressions={len(rec.get('regressions', []))} {rec.get('error', '')} {rec['secs']}s", flush=True)
                subprocess.run(["ollama", "stop", a.worker], capture_output=True)
