"""Real tasks on the daedalus codebase itself (snapshot in base/, commit in BASE_COMMIT).

Each oracle is a test module added next to the ORIGINAL test suite (the worker's own test edits are
discarded), so the oracle also catches regressions. Oracles test boundaries, not internals: what reaches
the stubbed SDK's options, what the submitted Diff carries, what the CLI prints.
"""

COMMON = '''
import asyncio, json, subprocess, sys, types
from pathlib import Path
import pytest
from daedalus.ariadne.diff_bus import AriadneBus
from daedalus.bus.icarus_bus import IcarusBus, WorkPackage
from daedalus.worker import harness


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@t")
    git(r, "config", "user.name", "t")
    (r / "app.py").write_text("def f():\\n    return 1\\n")
    git(r, "add", ".")
    git(r, "commit", "-qm", "init")
    return r


@pytest.fixture
def buses(tmp_path, monkeypatch):
    icarus = IcarusBus(root=tmp_path / "icarus"); icarus.initialize()
    ariadne = AriadneBus(root=tmp_path / "ariadne"); ariadne.initialize()
    monkeypatch.setattr(harness, "IcarusBus", lambda *a, **k: icarus)
    monkeypatch.setattr(harness, "AriadneBus", lambda *a, **k: ariadne)
    return icarus, ariadne


@pytest.fixture
def fake_sdk(monkeypatch):
    """Scripted model in the harness; records the options each query() got."""
    scripts, calls = [], []

    async def fake_query(prompt, options):
        if not isinstance(prompt, str):
            async for _ in prompt:
                pass
        calls.append(options)
        if scripts:
            scripts.pop(0)(Path(options.cwd))
        yield types.SimpleNamespace(type="result", result="done")

    monkeypatch.setattr(harness, "HAS_AGENT_SDK", True)
    monkeypatch.setattr(harness, "query", fake_query, raising=False)
    monkeypatch.setattr(harness, "ClaudeAgentOptions", lambda **kw: types.SimpleNamespace(**kw))
    monkeypatch.setattr(harness, "HookMatcher", lambda **kw: types.SimpleNamespace(**kw))
    return types.SimpleNamespace(scripts=scripts, calls=calls)


def run_package(icarus, repo, description, **worker_kwargs):
    work = WorkPackage(id="", type="implementation", description=description, inputs={"ariadne_mode": True}, outputs={})
    icarus.post_work(work)
    worker = harness.IcarusWorker(project_root=str(repo), bus=icarus, stream_output=False, use_ariadne=True, **worker_kwargs)
    try:
        return asyncio.run(worker.execute_work_package(work))
    finally:
        asyncio.run(worker.unregister())
'''

TASKS = {}

# ---------------------------------------------------------------------------------------------------
TASKS["pycache"] = dict(
    title="Keep build artifacts out of Ariadne diffs",
    description="""IcarusWorker.submit_diff_to_ariadne in `src/daedalus/worker/harness.py` stages the working tree with `git add -A` and diffs the index against HEAD. A worker that runs the tests leaves `__pycache__/` directories, `.pyc` files and `.pytest_cache/` in its worktree. In a project whose .gitignore doesn't cover them, they end up in the submitted diff as binary patches; `git apply` refuses those, so Ariadne's verifier rejects every diff from that worker.

Change the diff collection so `__pycache__/` directories, `*.pyc` files and `.pytest_cache/` are never part of a submitted diff, whether or not the project has a .gitignore. New source files and edits to existing files must still be included, and the working tree must still be reset afterwards as it is now. Add tests in `tests/test_worker_harness.py`.""",
    oracle=COMMON + '''

def test_artifacts_never_in_diff_without_gitignore(repo, buses, fake_sdk):
    icarus, ariadne = buses

    def script(cwd):
        (cwd / "app.py").write_text("def f():\\n    return 2\\n")
        (cwd / "new_mod.py").write_text("X = 1\\n")
        (cwd / "__pycache__").mkdir()
        (cwd / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\\x00\\x01binary\\xff" * 20)
        (cwd / "pkg").mkdir()
        (cwd / "pkg" / "__pycache__").mkdir()
        (cwd / "pkg" / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"\\x00\\xfe" * 30)
        (cwd / "loose.pyc").write_bytes(b"\\x00\\xaa" * 10)
        (cwd / ".pytest_cache" / "v" / "cache").mkdir(parents=True)
        (cwd / ".pytest_cache" / "v" / "cache" / "lastfailed").write_text("{}")
    fake_sdk.scripts.append(script)
    result = run_package(icarus, repo, "Change f")
    diff = ariadne.get_diff(result["diff_id"])
    assert diff is not None
    assert "__pycache__" not in diff.content and ".pyc" not in diff.content and ".pytest_cache" not in diff.content
    assert "new_mod.py" in diff.content and "return 2" in diff.content


def test_diff_applies_cleanly(repo, buses, fake_sdk, tmp_path):
    icarus, ariadne = buses

    def script(cwd):
        (cwd / "app.py").write_text("def f():\\n    return 3\\n")
        (cwd / "__pycache__").mkdir()
        (cwd / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\\x00\\x01" * 50)
    fake_sdk.scripts.append(script)
    diff = ariadne.get_diff(run_package(icarus, repo, "Change f")["diff_id"])
    patch = tmp_path / "c.diff"
    patch.write_text(diff.content)
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=repo, check=True)


def test_gitignored_project_unchanged(repo, buses, fake_sdk):
    icarus, ariadne = buses
    (repo / ".gitignore").write_text("*.log\\n")
    git(repo, "add", ".gitignore"); git(repo, "commit", "-qm", "ignore")

    def script(cwd):
        (cwd / "app.py").write_text("def f():\\n    return 4\\n")
        (cwd / "debug.log").write_text("noise")
        (cwd / "docs.md").write_text("# docs\\n")
    fake_sdk.scripts.append(script)
    diff = ariadne.get_diff(run_package(icarus, repo, "Change f")["diff_id"])
    assert "docs.md" in diff.content and "return 4" in diff.content and "debug.log" not in diff.content


def test_only_artifacts_means_no_diff(repo, buses, fake_sdk):
    icarus, ariadne = buses

    def script(cwd):
        (cwd / "__pycache__").mkdir()
        (cwd / "__pycache__" / "app.cpython-313.pyc").write_bytes(b"\\x00" * 40)
    fake_sdk.scripts.append(script)
    result = run_package(icarus, repo, "Nothing real")
    assert result.get("diff_id") is None
''',
)

# ---------------------------------------------------------------------------------------------------
TASKS["judge_intent"] = dict(
    title="Give the semantic judge the full work package",
    description="""When IcarusWorker.execute_work_package (`src/daedalus/worker/harness.py`) submits a worker's changes to Ariadne, the Diff's description is set to the first line of the work package description (with leading '#' and spaces stripped), and nothing else about the task is recorded. The orchestrator's `_diff_intent` (`src/daedalus/ariadne/orchestrator.py`) returns `diff.metadata.get("intent") or diff.description`, so the semantic judge reviews the diff against a bare title such as "Task: Implement pricing changes" and never sees the requirements.

Make the worker record the work package's full description text as `diff.metadata["intent"]` on the diff it submits, so the judge reviews against the complete requirements. Keep `diff.description` as the short first-line title it is now. If the work package has constraints, include them in the intent too. Add tests in `tests/test_worker_harness.py`.""",
    oracle=COMMON + '''
from daedalus.ariadne.orchestrator import AriadneOrchestrator

DESC = """# Task: Implement pricing changes

Add apply_discount(total, code) to pricing.py.
SAVE10 takes 10% off; FLAT5 takes 5 off but never below 0; unknown codes raise ValueError."""


def edit(cwd):
    (cwd / "app.py").write_text("def f():\\n    return 9\\n")


def test_full_description_is_the_intent(repo, buses, fake_sdk):
    icarus, ariadne = buses
    fake_sdk.scripts.append(edit)
    diff = ariadne.get_diff(run_package(icarus, repo, DESC)["diff_id"])
    intent = diff.metadata.get("intent") or ""
    assert "SAVE10 takes 10% off; FLAT5 takes 5 off but never below 0" in intent
    assert "Add apply_discount(total, code) to pricing.py." in intent


def test_description_stays_the_title(repo, buses, fake_sdk):
    icarus, ariadne = buses
    fake_sdk.scripts.append(edit)
    diff = ariadne.get_diff(run_package(icarus, repo, DESC)["diff_id"])
    assert diff.description == "Task: Implement pricing changes"


def test_orchestrator_hands_the_full_intent_to_the_judge(repo, buses, fake_sdk):
    icarus, ariadne = buses
    fake_sdk.scripts.append(edit)
    diff = ariadne.get_diff(run_package(icarus, repo, DESC)["diff_id"])
    orch = AriadneOrchestrator(repo, bus=ariadne, semantic_reviewer=types.SimpleNamespace(review=None))
    assert "unknown codes raise ValueError" in orch._diff_intent(diff)


def test_constraints_are_part_of_the_intent(repo, buses, fake_sdk):
    icarus, ariadne = buses
    fake_sdk.scripts.append(edit)
    work = WorkPackage(id="", type="implementation", description=DESC, inputs={"ariadne_mode": True}, outputs={},
                       constraints=["Do not change the public API of orders.py"])
    icarus.post_work(work)
    worker = harness.IcarusWorker(project_root=str(repo), bus=icarus, stream_output=False, use_ariadne=True)
    try:
        result = asyncio.run(worker.execute_work_package(work))
    finally:
        asyncio.run(worker.unregister())
    intent = ariadne.get_diff(result["diff_id"]).metadata.get("intent") or ""
    assert "Do not change the public API of orders.py" in intent and "FLAT5" in intent
''',
)

# ---------------------------------------------------------------------------------------------------
EDICT_0002 = """Implement edict 0002, model casting for workers and judge.

## Intent
Let the human choose which model plays each role in Ariadne. The architectural bet is that a solid gate lets cheap, fast models do the work while a stronger model judges it. Right now neither role can be cast: `LLMJudge()` is constructed with no model and the worker harness's `ClaudeAgentOptions` sets none.

## Constraints
- Add `worker_model: Optional[str] = None` and `judge_model: Optional[str] = None` to `AriadneConfig`.
- `None` means "use the SDK default," so existing behavior is unchanged.
- Settable through the existing config CLI, e.g. `daedalus config ariadne.worker_model claude-haiku-5-5`.
- The orchestrator passes `judge_model` to `LLMJudge`; the dispatcher/harness passes `worker_model` to the worker's `ClaudeAgentOptions`.
- The model each role used is recorded on the diff (`metadata["worker_model"]`, and in the semantic review result for the judge), so results can be compared across castings later.

## Acceptance criteria
- With both fields unset, behavior and tests are unchanged.
- With them set, the configured model names reach both `ClaudeAgentOptions` constructions (verified by tests that stub the SDK).
- `ariadne review show` displays which models produced and judged the diff.

## Non-goals
- No per-task or per-complexity routing yet. One model per role.
- No backends other than the Claude Agent SDK.
- No automatic escalation from worker model to judge model.

## Interface notes
- The configured worker model applies to work packages that Ariadne's Dispatcher posts and a worker runs (`python -m daedalus.worker`, i.e. `run_worker`).
- `AriadneOrchestrator`, when constructed without a `semantic_reviewer`, builds its `LLMJudge` with the configured `judge_model`.
- `SemanticReviewResult.to_dict()` includes the judge's model.
- Add tests (stub the SDK the way `tests/test_ariadne_worker_loop.py` does)."""

TASKS["model_casting"] = dict(
    title="Edict 0002: model casting for workers and judge",
    description=EDICT_0002,
    oracle=COMMON + '''
from daedalus import config as cfg
from daedalus.ariadne import semantic_review
from daedalus.ariadne.diff_bus import Diff
from daedalus.ariadne.dispatcher import Dispatcher
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.planner import WorkPackageSpec, ImplementationPlan


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return tmp_path / "xdg"


def set_models(worker=None, judge=None):
    from click.testing import CliRunner
    from daedalus.cli.main import main
    runner = CliRunner()
    if worker:
        r = runner.invoke(main, ["config", "ariadne.worker_model", worker])
        assert r.exit_code == 0 and "Unknown" not in r.output, r.output
    if judge:
        r = runner.invoke(main, ["config", "ariadne.judge_model", judge])
        assert r.exit_code == 0 and "Unknown" not in r.output, r.output


def test_fields_default_none():
    c = cfg.AriadneConfig()
    assert c.worker_model is None and c.judge_model is None


def test_settable_through_config_cli(config_home):
    set_models("claude-haiku-5-5", "claude-opus-5-5")
    loaded = cfg.load_config()
    assert loaded.ariadne.worker_model == "claude-haiku-5-5"
    assert loaded.ariadne.judge_model == "claude-opus-5-5"


def dispatch_and_run(icarus, repo, tmp_path):
    spec = WorkPackageSpec(id="wp-1", title="Change f", description="Make f return 5", files=["app.py"])
    plan = ImplementationPlan(id="plan-1", feature_id="f", feature_title="t", summary="", affected_files=["app.py"],
                              affected_modules=[], complexity_score=1, work_packages=[spec], dependencies={},
                              total_estimated_lines=1, requires_approval=False, approval_reasons=[])
    d = Dispatcher(icarus_bus=icarus, state_dir=tmp_path / "dispatch", use_ariadne=True)
    state = d.create_dispatch_state(plan)
    work_id = d.dispatch_package(spec, state)
    asyncio.run(harness.run_worker(work_id=work_id, project_root=str(repo), use_ariadne=True))


def edit(cwd):
    (cwd / "app.py").write_text("def f():\\n    return 5\\n")


def test_worker_model_reaches_options_and_diff(config_home, repo, buses, fake_sdk, tmp_path):
    icarus, ariadne = buses
    set_models(worker="m-worker")
    fake_sdk.scripts.append(edit)
    dispatch_and_run(icarus, repo, tmp_path)
    assert fake_sdk.calls and getattr(fake_sdk.calls[0], "model", None) == "m-worker"
    (diff,) = ariadne.list_pending_diffs()
    assert diff.metadata.get("worker_model") == "m-worker"


def test_unset_worker_model_passes_none(config_home, repo, buses, fake_sdk, tmp_path):
    icarus, ariadne = buses
    fake_sdk.scripts.append(edit)
    dispatch_and_run(icarus, repo, tmp_path)
    assert getattr(fake_sdk.calls[0], "model", None) is None
    (diff,) = ariadne.list_pending_diffs()
    assert diff.metadata.get("worker_model") is None


@pytest.fixture
def fake_judge_sdk(monkeypatch):
    calls = []

    async def fake_query(prompt, options):
        calls.append(options)
        yield types.SimpleNamespace(text="APPROVE\\nLooks right.")

    monkeypatch.setattr(semantic_review, "HAS_AGENT_SDK", True)
    monkeypatch.setattr(semantic_review, "query", fake_query, raising=False)
    monkeypatch.setattr(semantic_review, "ClaudeAgentOptions", lambda **kw: types.SimpleNamespace(**kw))
    return calls


def a_diff():
    return Diff.from_git_diff(work_id="w", instance_id="i", description="Change f",
                              diff_content="diff --git a/app.py b/app.py\\n--- a/app.py\\n+++ b/app.py\\n@@ -1,2 +1,2 @@\\n def f():\\n-    return 1\\n+    return 5\\n")


def test_judge_model_reaches_options_and_result(config_home, repo, tmp_path, fake_judge_sdk):
    set_models(judge="m-judge")
    orch = AriadneOrchestrator(repo, bus=AriadneBus(root=tmp_path / "ab"))
    result = orch.semantic_reviewer.review(a_diff(), "Make f return 5")
    assert getattr(fake_judge_sdk[0], "model", None) == "m-judge"
    assert "m-judge" in json.dumps(result.to_dict())


def test_unset_judge_model_passes_none(config_home, repo, tmp_path, fake_judge_sdk):
    orch = AriadneOrchestrator(repo, bus=AriadneBus(root=tmp_path / "ab"))
    orch.semantic_reviewer.review(a_diff(), "Make f return 5")
    assert getattr(fake_judge_sdk[0], "model", None) is None


def test_review_show_displays_both_models(config_home, repo, tmp_path, fake_judge_sdk, monkeypatch, capsys):
    from daedalus.ariadne import orchestrator as orch_mod
    set_models(judge="m-judge")
    bus = AriadneBus(root=tmp_path / "ab"); bus.initialize()
    diff = a_diff()
    diff.metadata["worker_model"] = "m-worker"
    review = AriadneOrchestrator(repo, bus=bus).semantic_reviewer.review(diff, "Make f return 5")
    diff.semantic_review = review.to_dict()
    bus.submit_diff(diff)
    monkeypatch.setattr(orch_mod, "AriadneBus", lambda *a, **k: bus)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["ariadne", "--repo", str(repo), "review", "show", diff.id])
    orch_mod.main()
    out = capsys.readouterr().out
    assert "m-worker" in out and "m-judge" in out
''',
)
