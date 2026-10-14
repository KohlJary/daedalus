"""Colliding pairs (pilot design): two packages for the same function with incompatible intents, dispatched
in one wave through the real Dispatcher -> IcarusWorker harness (own worktree each) -> AriadneOrchestrator
with its default conflict handler (escalate). Only the model call is local.

Outcome per run:
  escalated     conflict detected and escalated, nothing merged          (pass)
  one_merged    one diff merged, the other rejected / in review / lost   (the other intent silently lost)
  both_merged   both merged                                              (fail: incompatible intents on main)
  none          nothing merged and no conflict recorded (e.g. both rejected by the gate)

  python3 collide.py --workers qwen3:8b,qwen2.5:latest --reps 3
"""
import argparse, asyncio, json, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import exp, feature  # noqa: E402
from tasks_new import COLLIDING  # noqa: E402
from daedalus.ariadne.planner import ImplementationPlan, WorkPackageSpec  # noqa: E402
from daedalus.ariadne.dispatcher import Dispatcher  # noqa: E402
from daedalus.ariadne.diff_bus import AriadneBus  # noqa: E402
from daedalus.ariadne.orchestrator import AriadneOrchestrator  # noqa: E402
from daedalus.bus.icarus_bus import IcarusBus  # noqa: E402
from daedalus.worker.harness import IcarusWorker  # noqa: E402

OUT = Path(__import__("os").environ.get("COLLIDE_OUT", exp.RESULTS / "collide.jsonl"))


def run_pair(name, pair, worker_model, judge_model):
    repo = exp.make_repo(pair["files"])
    exp.git(repo, "config", "user.email", "t@t")
    exp.git(repo, "config", "user.name", "t")
    state = repo.parent / "state"
    icarus = IcarusBus(root=state / "icarus"); icarus.initialize()
    ariadne = AriadneBus(root=state / "ariadne"); ariadne.initialize()
    specs = [WorkPackageSpec(id=f"p{i + 1}", title=d.split(".")[0], description=d, files=list(pair["files"]))
             for i, d in enumerate(pair["packages"])]
    plan = ImplementationPlan(id=f"plan-{name}", feature_id=name, feature_title=name, summary="", affected_files=list(pair["files"]),
                              affected_modules=[], complexity_score=1, work_packages=specs, dependencies={},
                              total_estimated_lines=0, requires_approval=False, approval_reasons=[])
    dispatcher = Dispatcher(icarus_bus=icarus, state_dir=state / "dispatch", use_ariadne=True)
    dstate = dispatcher.create_dispatch_state(plan)
    intent_for = {}
    judge = feature.LocalJudge(judge_model, intent_for)
    orch = AriadneOrchestrator(repo, bus=ariadne, auto_commit=True, autonomy="full", semantic_reviewer=judge)
    orch.verifier = feature.real_verifier(repo)

    async def local_execute(self, prompt, system_prompt=None, permission_mode="default"):
        w = exp.work(worker_model, Path(self.work_dir), prompt)
        log.append(dict(work_id=self.work_id, **{k: w[k] for k in ("steps", "tool_calls", "worker_error", "worker_secs")}))
        return {"success": w["worker_error"] in (None, "max_steps"), "output": w["final"]}

    log, diff_ids = [], {}
    original = IcarusWorker.execute
    IcarusWorker.execute = local_execute
    try:
        ids = dispatcher.dispatch_ready(plan, dstate, max_parallel=4)
        assert len(ids) == 2, "both packages must be in the same wave"
        for spec_id, rec in dstate.records.items():
            wk = icarus.get_work(rec.work_id)
            intent_for[rec.work_id] = wk.description  # the judge sees each package's own intent
            worker = IcarusWorker(project_root=str(repo), bus=icarus, stream_output=False, use_ariadne=True)
            worker.ariadne_bus = ariadne
            result = asyncio.run(worker.execute_work_package(wk))
            asyncio.run(worker.unregister())
            diff_ids[spec_id] = result.get("diff_id")
        o = orch.process_pending()
    finally:
        IcarusWorker.execute = original

    statuses = {}
    for spec_id, did in diff_ids.items():
        d = ariadne.get_diff(did) if did else None
        statuses[spec_id] = getattr(d.status, "value", str(d.status)) if d else "no_diff"
    merged = [s for s, st in statuses.items() if st in ("merged", "committed")]
    conflicts = ariadne.list_conflicts()
    outcome = ("both_merged" if len(merged) == 2 else "one_merged" if len(merged) == 1
               else "escalated" if conflicts else "none")
    rec = dict(pair=name, worker=worker_model, judge=judge_model, outcome=outcome, statuses=statuses,
               conflicts_detected=o.conflicts_detected, conflicts_resolved=o.conflicts_resolved,
               conflicts=[json.loads(json.dumps(getattr(c, "__dict__", str(c)), default=str)) for c in conflicts][:3],
               verified=o.diffs_verified, rejected=o.diffs_rejected, needs_review=o.diffs_needs_review,
               commits=exp.git(repo, "log", "--oneline").stdout.strip().splitlines(), judge_log=judge.log, workers=log,
               diffs={s: (ariadne.get_diff(d).content if d and ariadne.get_diff(d) else "") for s, d in diff_ids.items()})
    import shutil
    shutil.rmtree(repo.parent, ignore_errors=True)
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="qwen3:8b,qwen2.5:latest")
    ap.add_argument("--judge", default="qwen3-coder:30b")
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    done = {(r["pair"], r["worker"], r["rep"]) for r in exp.load(OUT)}
    for worker in a.workers.split(","):
        for rep in range(1, a.reps + 1):
            for name, pair in COLLIDING.items():
                if (name, worker, rep) in done:
                    continue
                t0 = time.time()
                try:
                    rec = run_pair(name, pair, worker, a.judge)
                except Exception as e:
                    rec = dict(pair=name, worker=worker, outcome="error", error=f"{type(e).__name__}: {e}")
                rec.update(rep=rep, secs=round(time.time() - t0))
                exp.append(OUT, rec)
                print(f"{name:14} {worker:16} rep{rep} outcome={rec['outcome']:12} {rec.get('statuses')} "
                      f"conflicts={rec.get('conflicts_detected')} {rec.get('error', '')} {rec['secs']}s", flush=True)
        subprocess.run(["ollama", "stop", worker], capture_output=True)
