"""A multi-part feature through Ariadne's real planner -> dispatcher -> worker harness -> orchestrator.

Only the model call is swapped: IcarusWorker.execute runs the local tool loop in the worker's own
worktree; the harness still creates the worktree, collects and submits the diff. The orchestrator
verifies with the real CausalSliceVerifier, reviews with the real judge prompt on a local model, and
commits. Hidden oracle tests are run on the final HEAD.

Conditions (same feature, same worker model):
  single     one worker gets the whole feature; nothing gates it (the plain qwen3 baseline)
  single+gate  the single worker's diff through verifier + judge (scored from the same run)
  ariadne    Ariadne as built: packages get the planner's prompt ("Modify X for <title>")
  ariadne+req  same, but each package's prompt (and the judge's intent) carries the full feature text

  python3 feature.py --worker qwen3:8b --judge qwen3-coder:30b --reps 3
"""
import argparse, asyncio, json, shutil, subprocess, sys, tempfile, time

import httpx
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "refs"))
sys.path.insert(0, str(HERE))
import exp  # noqa: E402
from exp import make_repo, git, work, harness_diff, judge_one, PYTEST  # noqa: E402

from daedalus.ariadne.planner import Planner, FeatureRequest, AriadneConfig, WorkPackageSpec  # noqa: E402
from daedalus.ariadne.dispatcher import Dispatcher  # noqa: E402
from daedalus.ariadne.diff_bus import AriadneBus  # noqa: E402
from daedalus.ariadne.orchestrator import AriadneOrchestrator  # noqa: E402
from daedalus.ariadne.semantic_review import SemanticReviewResult, ReviewVerdict  # noqa: E402
from daedalus.ariadne.verification import CausalSliceVerifier  # noqa: E402
from daedalus.bus.icarus_bus import IcarusBus  # noqa: E402
from daedalus.worker.harness import IcarusWorker  # noqa: E402

FILES = {
    "conftest.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))\n",
    "src/shop/__init__.py": "",
    "src/shop/pricing/__init__.py": "",
    "src/shop/pricing/discounts.py": '''def subtotal(items):
    """items: list of (name, unit_price, qty)."""
    return sum(price * qty for _, price, qty in items)
''',
    "src/shop/inventory/__init__.py": "",
    "src/shop/inventory/stock.py": '''class Stock:
    def __init__(self, levels):
        self.levels = dict(levels)

    def available(self, name):
        return self.levels.get(name, 0)

    def take(self, name, qty):
        self.levels[name] = self.available(name) - qty
''',
    "src/shop/orders/__init__.py": "",
    "src/shop/orders/order.py": '''from shop.pricing.discounts import subtotal


class Order:
    def __init__(self, items):
        self.items = items

    def total(self):
        return subtotal(self.items)


def place_order(order, stock):
    for name, _, qty in order.items:
        stock.take(name, qty)
''',
    "tests/test_pricing.py": '''from shop.pricing.discounts import subtotal


def test_subtotal():
    assert subtotal([("a", 2.0, 3), ("b", 1.5, 2)]) == 9.0
''',
    "tests/test_inventory.py": '''from shop.inventory.stock import Stock


def test_take():
    s = Stock({"a": 5})
    s.take("a", 2)
    assert s.available("a") == 3
''',
    "tests/test_orders.py": '''from shop.orders.order import Order, place_order
from shop.inventory.stock import Stock


def test_total():
    assert Order([("a", 2.0, 3)]).total() == 6.0


def test_place_order():
    s = Stock({"a": 5})
    place_order(Order([("a", 2.0, 3)]), s)
    assert s.available("a") == 2
''',
}

TITLE = "Discount codes and stock-checked orders"
DESCRIPTION = """Add discount codes, and make placing an order check stock first.

1. In `src/shop/pricing/discounts.py` add apply_discount(total, code). "SAVE10" takes 10% off. "FLAT5" takes 5 off but never goes below 0. code=None returns the total unchanged. Any other code raises ValueError.
2. In `src/shop/orders/order.py`, Order takes an optional discount_code (default None), and Order.total() applies it to the subtotal using apply_discount.
3. In `src/shop/inventory/stock.py`, Stock.take(name, qty) raises ValueError if fewer than qty are available, leaving the level unchanged.
4. place_order(order, stock) in `src/shop/orders/order.py` checks every line before taking anything: if any line can't be fulfilled it raises ValueError and the stock is left unchanged.
5. Add tests for all of this in `tests/test_pricing.py`, `tests/test_inventory.py`, and `tests/test_orders.py`.
"""

ORACLE = '''import pytest
from shop.pricing.discounts import apply_discount, subtotal
from shop.inventory.stock import Stock
from shop.orders.order import Order, place_order


def test_apply_discount():
    assert apply_discount(100, None) == 100
    assert apply_discount(100, "SAVE10") == pytest.approx(90)
    assert apply_discount(20, "FLAT5") == 15
    assert apply_discount(3, "FLAT5") == 0
    with pytest.raises(ValueError):
        apply_discount(100, "BOGUS")


def test_order_total_with_discount():
    items = [("a", 10.0, 2)]
    assert Order(items).total() == 20.0
    assert Order(items, discount_code="SAVE10").total() == pytest.approx(18.0)
    assert Order(items, "FLAT5").total() == 15.0


def test_take_checks_stock():
    s = Stock({"a": 2})
    with pytest.raises(ValueError):
        s.take("a", 3)
    assert s.available("a") == 2
    s.take("a", 2)
    assert s.available("a") == 0


def test_place_order_is_all_or_nothing():
    s = Stock({"a": 5, "b": 1})
    with pytest.raises(ValueError):
        place_order(Order([("a", 1.0, 2), ("b", 1.0, 3)]), s)
    assert s.available("a") == 5 and s.available("b") == 1
    place_order(Order([("a", 1.0, 2), ("b", 1.0, 1)]), s)
    assert s.available("a") == 3 and s.available("b") == 0
'''


import todo_app  # noqa: E402

PLANS = HERE / "results" / "plans"

FEATURES = {
    "shop": dict(files=FILES, title=TITLE, description=DESCRIPTION, oracle=ORACLE),
    "todo_priority": dict(files=todo_app.TODO_FILES, title="Task priorities",
                          description=todo_app.PRIORITY_DESCRIPTION, oracle=todo_app.PRIORITY_ORACLE),
    "todo_due": dict(files=todo_app.TODO_FILES, title="Due dates and overdue tasks",
                     description=todo_app.DUE_DESCRIPTION, oracle=todo_app.DUE_ORACLE),
}
for _name, _feat in FEATURES.items():
    _feat["name"] = _name


def run_oracle(repo: Path, oracle: str = ORACLE) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="feat-oracle-"))
    try:
        shutil.copytree(repo, tmp / "p", ignore=shutil.ignore_patterns(".git", "__pycache__"))
        shutil.rmtree(tmp / "p" / "tests", ignore_errors=True)
        (tmp / "p" / "tests").mkdir()
        (tmp / "p" / "tests" / "test_oracle.py").write_text(oracle)
        r = subprocess.run(PYTEST + ["-rA"], cwd=tmp / "p", capture_output=True, text=True, timeout=60)
        per_test = {line.split("::")[-1].split()[0]: line.split()[0]
                    for line in r.stdout.splitlines() if line.startswith(("PASSED", "FAILED", "ERROR")) and "::" in line}
        return dict(oracle_pass=r.returncode == 0, oracle_tests=per_test,
                    oracle_out=r.stdout.strip().splitlines()[-1][:200] if r.stdout.strip() else r.stderr[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def real_verifier(repo):
    noop = [sys.executable, "-c", "pass"]
    return CausalSliceVerifier(repo, typecheck_cmd=noop, lint_cmd=noop, test_cmd=PYTEST)


class LocalJudge:
    """SemanticReviewer on a local model, using semantic_review.py's real prompt and parser.
    intent_for maps work_id -> intent to use instead of the one the orchestrator passes."""

    def __init__(self, model, intent_for=None):
        self.model, self.intent_for, self.log = model, intent_for if intent_for is not None else {}, []

    def review(self, diff, intent, verification=None):
        used = self.intent_for.get(diff.work_id, intent)
        verdict, text = judge_one(self.model, used, diff.content, verification.to_dict() if verification else None)
        self.log.append(dict(work_id=diff.work_id, intent_seen=used[:300], verdict=verdict, reasoning=text[:1000]))
        return SemanticReviewResult(diff_id=diff.id, verdict=ReviewVerdict(verdict), reasoning=text,
                                    reviewer=f"local:{self.model}")


# ---------- condition D: an LLM planner ----------

PLANNER_PROMPT = """You are the planner for a team of small, cheap coding models. Split the feature below into work packages.

Each worker gets exactly one package. It can read the project's files, but it never sees the feature request or the other packages: your package description is all it knows about the task. A package runs only after every package in its depends_on has been merged, so it can use their code.

Rules:
- Keep packages small: usually one source module plus its test file.
- Each description must be complete on its own. Restate every requirement from the feature that applies to this package, with exact names, signatures, output formats, defaults and error cases. Name any functions or fields from other packages it uses, with their signatures.
- If a package imports or calls code that another package adds or changes, list that package in depends_on.
- Each package updates or adds tests for what it changes in the matching tests/test_<module>.py. In its "tests" field, name that file, list the behaviors the tests must cover, and name any existing test whose expected output this change alters, saying how it must be updated.
- Two packages that change the same file must not run in parallel: make one depend on the other.
- Use ids p1, p2, p3, ...

## Feature: {title}
{description}

## Project files
{files}
"""

PLAN_SCHEMA = {"type": "object", "required": ["packages"], "properties": {"packages": {"type": "array", "items": {
    "type": "object", "required": ["id", "title", "files", "description", "tests", "depends_on"], "properties": {
        "id": {"type": "string"}, "title": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
        "description": {"type": "string"},
        "tests": {"type": "object", "required": ["file", "must_cover", "existing_tests_to_update"], "properties": {
            "file": {"type": "string"},
            "must_cover": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "existing_tests_to_update": {"type": "array", "items": {"type": "string"}}}},
        "depends_on": {"type": "array", "items": {"type": "string"}}}}}}}


def format_tests(t):
    if not t:
        return ""
    if isinstance(t, str):
        return f"\n\n## Tests\n{t}"
    lines = [f"\n\n## Tests (in {t.get('file')})", "Cover:"] + [f"- {c}" for c in t.get("must_cover", [])]
    if t.get("existing_tests_to_update"):
        lines += ["Existing tests this change breaks, update them:"] + [f"- {c}" for c in t["existing_tests_to_update"]]
    return "\n".join(lines)


def llm_plan(planner_model, feat, repo):
    files = "\n".join(f"### {p.relative_to(repo)}\n```\n{p.read_text()}```" for p in sorted(repo.rglob("*"))
                      if p.is_file() and ".git" not in p.parts and p.name != ".gitignore")
    prompt = PLANNER_PROMPT.format(title=feat["title"], description=feat["description"], files=files)
    t0 = time.time()
    r = httpx.post(f"{exp.OLLAMA}/api/chat", timeout=900, json={
        "model": planner_model, "stream": False, "format": PLAN_SCHEMA,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"num_ctx": exp.NUM_CTX, "temperature": 0}})
    exp.record_usage(f"{planner_model} (planner)", r.json(), len(prompt) + len(json.dumps(PLAN_SCHEMA)))
    raw = json.loads(r.json()["message"]["content"])["packages"]
    ids = [p["id"] for p in raw]
    fixups = []
    for p in raw:  # drop dependencies on unknown ids or on itself
        bad = [d for d in p["depends_on"] if d not in ids or d == p["id"]]
        if bad:
            fixups.append(f"{p['id']}: dropped unknown deps {bad}")
            p["depends_on"] = [d for d in p["depends_on"] if d not in bad]
    # break cycles: Kahn; anything left over keeps only dependencies on earlier packages
    remaining, order = {p["id"]: set(p["depends_on"]) for p in raw}, []
    while True:
        ready = [i for i, deps in remaining.items() if not deps - set(order)]
        if not ready:
            break
        for i in ready:
            order.append(i); remaining.pop(i)
    if remaining:
        fixups.append(f"cycle among {sorted(remaining)}: kept only deps on earlier packages")
        for p in raw:
            if p["id"] in remaining:
                p["depends_on"] = [d for d in p["depends_on"] if ids.index(d) < ids.index(p["id"])]
    return raw, fixups, round(time.time() - t0, 1)


# ---------- conditions ----------

def run_single(feat, worker_model, judge_model):
    repo = make_repo(feat["files"])
    intent = f"{feat['title']}\n\n{feat['description']}"
    try:
        w = work(worker_model, repo, intent, max_steps=60)  # a whole feature needs far more turns than a package
        diff = harness_diff(repo)
        rec = dict(condition="single", **w, diff=diff, **run_oracle(repo, feat["oracle"]))
        rec["gated_landed"] = False
        if diff.strip():
            from daedalus.ariadne.diff_bus import Diff
            from daedalus.ariadne.verification import extract_causal_chain
            d = Diff.from_git_diff(work_id="single", instance_id="exp", diff_content=diff, description=feat["title"])
            base = make_repo(feat["files"])
            v = real_verifier(base).verify(d, extract_causal_chain(d, repo))
            shutil.rmtree(base.parent, ignore_errors=True)
            rec["verifier_pass"] = v.passed
            rec["verification"] = v.to_dict()
            if v.passed:
                rec["verdict"], rec["reasoning"] = judge_one(judge_model, intent, diff, v.to_dict())
            rec["gated_landed"] = v.passed and rec.get("verdict") == "approved"
        return rec
    finally:
        shutil.rmtree(repo.parent, ignore_errors=True)


def run_ariadne(feat, worker_model, judge_model, mode, planner_model=None):
    """mode: 'ariadne' (as built), 'ariadne+req' (feature text appended to every package and used as the
    judge's intent), 'ariadne+llmplan' (packages written by an LLM planner; judge's intent = the package)."""
    repo = make_repo(feat["files"])
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    state_root = repo.parent / "state"
    icarus = IcarusBus(root=state_root / "icarus"); icarus.initialize()
    ariadne = AriadneBus(root=state_root / "ariadne"); ariadne.initialize()

    plan = Planner(repo, config=AriadneConfig(autonomy="full"), plans_dir=state_root / "plans").analyze_feature(
        FeatureRequest.create(feat["title"], feat["description"]))
    planner_info = {}
    if mode == "ariadne+req":
        for wp in plan.work_packages:
            wp.description += "\n\n## Feature requirements (this package is one part of them)\n" + feat["description"]
    elif mode in ("ariadne+llmplan", "ariadne+llmplan+review", "ariadne+llmplan+leanreview"):
        # One plan per feature, generated once (planner at temperature 0) and cached, so D and E dispatch
        # the same plan and differ only by the review. E uses plans/<feature>.reviewed.json, written by a
        # Claude reviewer that saw the feature request, the code and the plan, nothing else.
        cache = PLANS / f"{feat['name']}.json"
        if not cache.exists():
            raw, fixups, secs = llm_plan(planner_model, feat, repo)
            PLANS.mkdir(exist_ok=True)
            cache.write_text(json.dumps(dict(raw=raw, fixups=fixups, planner_secs=secs,
                                             usage=exp.USAGE.get(f"{planner_model} (planner)")), indent=2))
        cached = json.loads(cache.read_text())
        raw, fixups, secs = cached["raw"], cached["fixups"], cached["planner_secs"]
        planner_info = dict(planner=planner_model, raw=raw, fixups=fixups, planner_secs=secs,
                            planner_usage=cached.get("usage"))
        if mode in ("ariadne+llmplan+review", "ariadne+llmplan+leanreview"):
            suffix = "reviewed" if mode == "ariadne+llmplan+review" else "leanreviewed"
            reviewed = json.loads((PLANS / f"{feat['name']}.{suffix}.json").read_text())
            raw = reviewed["packages"]
            planner_info.update(review_notes=reviewed.get("notes"), reviewed=raw)
        plan.work_packages = [WorkPackageSpec(id=p["id"], title=p["title"],
                                              description=p["description"] + format_tests(p.get("tests")),
                                              files=p["files"], depends_on=p["depends_on"]) for p in raw]
        plan.dependencies = {p["id"]: p["depends_on"] for p in raw if p["depends_on"]}
        subprocess.run(["ollama", "stop", planner_model], capture_output=True)

    dispatcher = Dispatcher(icarus_bus=icarus, state_dir=state_root / "dispatch", use_ariadne=True)
    dstate = dispatcher.create_dispatch_state(plan)
    intent_for = {}
    judge = LocalJudge(judge_model, intent_for)
    orch = AriadneOrchestrator(repo, bus=ariadne, auto_commit=True, autonomy="full", semantic_reviewer=judge)
    orch.verifier = real_verifier(repo)

    async def local_execute(self, prompt, system_prompt=None, permission_mode="default"):
        w = work(worker_model, Path(self.work_dir), prompt)
        packages_log.append(dict(work_id=self.work_id, prompt=prompt, **w))
        return {"success": w["worker_error"] in (None, "max_steps"), "output": w["final"]}

    packages_log, waves = [], []
    original_execute = IcarusWorker.execute
    IcarusWorker.execute = local_execute
    try:
        while not dstate.all_completed():
            ids = dispatcher.dispatch_ready(plan, dstate, max_parallel=4)
            if not ids:
                break  # remaining packages blocked
            wave = []
            for spec_id, rec in list(dstate.records.items()):
                if rec.work_id in ids:
                    wk = icarus.get_work(rec.work_id)
                    if mode != "ariadne":
                        intent_for[rec.work_id] = wk.description
                    worker = IcarusWorker(project_root=str(repo), bus=icarus, stream_output=False, use_ariadne=True)
                    worker.ariadne_bus = ariadne
                    result = asyncio.run(worker.execute_work_package(wk))
                    asyncio.run(worker.unregister())
                    wave.append(dict(spec_id=spec_id, work_id=rec.work_id, diff_id=result.get("diff_id")))
                    # The dispatcher counts a package complete when its worker finishes, whether or not
                    # its diff later merges: dependents start from whatever HEAD has by then.
                    dispatcher.mark_completed(dstate, spec_id, diff_id=result.get("diff_id"))
            o = orch.process_pending()  # verify, judge, commit this wave before dependents start
            waves.append(dict(packages=wave, verified=o.diffs_verified, rejected=o.diffs_rejected,
                              needs_review=o.diffs_needs_review, commits=o.commits_created,
                              conflicts=o.conflicts_detected, conflicts_resolved=o.conflicts_resolved,
                              errors=o.errors))
    finally:
        IcarusWorker.execute = original_execute

    diffs = []
    for d in (ariadne.get_diff(p["diff_id"]) for w in waves for p in w["packages"] if p["diff_id"]):
        if d is not None:
            diffs.append(dict(work_id=d.work_id, status=getattr(d.status, "value", str(d.status)),
                              files=sorted(d.all_affected_files()), diff=d.content))
    rec = dict(condition=mode, planner_info=planner_info,
               plan=dict(packages=[dict(id=wp.id, title=wp.title, files=wp.files, depends_on=wp.depends_on)
                                   for wp in plan.work_packages], complexity=plan.complexity_score),
               packages=packages_log, waves=waves, judge_log=judge.log, diffs=diffs,
               commits=git(repo, "log", "--oneline").stdout.strip().splitlines(),
               **run_oracle(repo, feat["oracle"]))
    shutil.rmtree(repo.parent, ignore_errors=True)
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--worker", default="qwen3:8b")
    ap.add_argument("--judge", default="qwen3-coder:30b")
    ap.add_argument("--planner", default="qwen3-coder:30b")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--features", default=",".join(FEATURES))
    ap.add_argument("--conditions", default="single,ariadne,ariadne+req,ariadne+llmplan,ariadne+llmplan+review")
    ap.add_argument("--out", default=str(exp.RESULTS / "feature.jsonl"))
    a = ap.parse_args()
    done = {(r["feature"], r["condition"], r["rep"]) for r in exp.load(Path(a.out))}
    for rep in range(1, a.reps + 1):
        for fname in a.features.split(","):
            for cond in a.conditions.split(","):
                if (fname, cond, rep) in done:
                    continue
                feat, t0 = FEATURES[fname], time.time()
                exp.USAGE.clear()
                rec = (run_single(feat, a.worker, a.judge) if cond == "single"
                       else run_ariadne(feat, a.worker, a.judge, cond, a.planner))
                rec.update(feature=fname, rep=rep, worker=a.worker, judge=a.judge, secs=round(time.time() - t0),
                           usage={m: dict(u) for m, u in exp.USAGE.items()})
                exp.append(Path(a.out), rec)
                passed = sum(v == "PASSED" for v in rec["oracle_tests"].values())
                extra = (f"gated_landed={rec.get('gated_landed')}" if cond == "single" else
                         f"packages={len(rec['plan']['packages'])} commits={len(rec['commits']) - 1} "
                         f"waves={[(w['verified'], w['rejected'], w['needs_review'], w['conflicts']) for w in rec['waves']]}")
                print(f"rep{rep} {fname:14} {cond:16} oracle={rec['oracle_pass']!s:5} ({passed}/{len(rec['oracle_tests'])}) "
                      f"{extra} {rec['secs']}s", flush=True)
