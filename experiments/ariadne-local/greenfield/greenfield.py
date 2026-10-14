"""Greenfield: can local Ariadne get the rough shape down for free, for a frontier model to polish?

Local conditions (runnable any time):
  gf_single     one local agent builds the whole spec (80-turn budget)
  gf_llmplan    the local LLM planner plans it, Ariadne dispatches to local workers, gate, commit
Claude conditions (RUNBOOK.md, from 2026-10-23):
  claude_solo   Claude builds it alone
  polish        Claude polishes a gf_llmplan artifact
  claudeplan    Claude writes the plan plus acceptance tests, local Ariadne builds, Claude polishes

Every run's final tree is kept under results/artifacts/<feature>/<condition>/rep<k>/ (the input to polish).
  python3 greenfield.py --reps 3
  python3 greenfield.py --conditions claudeplan --reps 3     # after results/plans/<feature>.claudeplan.json exists
"""
import argparse, json, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "gate_exp"))
import exp, feature, specs  # noqa: E402

RESULTS = HERE / "results"
FEATURES = {
    "units": dict(title="units: a small unit-conversion library", description=specs.UNITS_SPEC, oracle=specs.UNITS_ORACLE),
    "kvstore": dict(title="kvstore: an in-memory key-value store with TTLs and transactions", description=specs.KVSTORE_SPEC,
                    oracle=specs.KVSTORE_ORACLE),
}
for name, f in FEATURES.items():
    f["name"] = name
    f["files"] = {"README.md": f["description"]}

CURRENT = {}
_score = feature.run_oracle


def score_and_keep(repo, oracle):
    dest = RESULTS / "artifacts" / CURRENT["feature"] / CURRENT["condition"] / f"rep{CURRENT['rep']}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(repo, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    return _score(repo, oracle)


def install():
    feature.PLANS = RESULTS / "plans"
    feature.run_oracle = score_and_keep
    _work = feature.work
    feature.work = lambda model, repo, prompt, max_steps=30, system=None: _work(
        model, repo, prompt, max_steps=80 if CURRENT.get("condition") == "gf_single" else max_steps, system=system)


def claudeplan_feature(feat):
    """Claude's plan + acceptance tests -> a feature whose base has the tests committed, dispatched as a reviewed plan."""
    src = json.loads((RESULTS / "plans" / f"{feat['name']}.claudeplan.json").read_text())
    name = f"{feat['name']}__claudeplan"
    plans = RESULTS / "plans"
    (plans / f"{name}.json").write_text(json.dumps(dict(raw=src["packages"], fixups=["claude plan"], planner_secs=0)))
    (plans / f"{name}.reviewed.json").write_text(json.dumps(dict(packages=src["packages"], notes=["claude plan"])))
    return dict(feat, name=name, files={**feat["files"], **src.get("seed_files", {})})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", default="qwen3:8b")
    ap.add_argument("--judge", default="qwen3-coder:30b")
    ap.add_argument("--planner", default="qwen3-coder:30b")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--features", default=",".join(FEATURES))
    ap.add_argument("--conditions", default="gf_single,gf_llmplan")
    a = ap.parse_args()
    install()
    (RESULTS / "plans").mkdir(parents=True, exist_ok=True)
    out = RESULTS / "greenfield.jsonl"
    done = {(r["feature"], r["condition"], r["rep"]) for r in exp.load(out)}
    for rep in range(1, a.reps + 1):
        for fname in a.features.split(","):
            for cond in a.conditions.split(","):
                if (fname, cond, rep) in done:
                    continue
                CURRENT.update(feature=fname, condition=cond, rep=rep)
                feat, t0 = FEATURES[fname], time.time()
                exp.USAGE.clear()
                try:
                    if cond == "gf_single":
                        rec = feature.run_single(feat, a.worker, a.judge)
                    elif cond == "gf_llmplan":
                        rec = feature.run_ariadne(feat, a.worker, a.judge, "ariadne+llmplan", a.planner)
                    elif cond == "claudeplan":
                        rec = feature.run_ariadne(claudeplan_feature(feat), a.worker, a.judge, "ariadne+llmplan+review", a.planner)
                    else:
                        raise ValueError(cond)
                except Exception as e:
                    rec = dict(error=f"{type(e).__name__}: {e}", oracle_pass=False, oracle_tests={})
                rec.update(feature=fname, condition=cond, rep=rep, worker=a.worker, judge=a.judge, secs=round(time.time() - t0),
                           usage={m: dict(u) for m, u in exp.USAGE.items()})
                exp.append(out, rec)
                passed = sum(v == "PASSED" for v in rec.get("oracle_tests", {}).values())
                print(f"rep{rep} {fname:8} {cond:11} oracle={rec['oracle_pass']!s:5} ({passed}/{len(rec.get('oracle_tests', {}))}) "
                      f"{rec.get('error', '')} {rec['secs']}s", flush=True)
