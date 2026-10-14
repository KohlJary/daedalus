"""
Ariadne end to end through a real Icarus worker (hermetic tier).

test_ariadne_e2e_smoke.py hands diffs to the bus directly and verifies with no-op commands. These tests
drive the parts it skips: a real IcarusWorker executes a work package in Ariadne mode, its changes reach
the Ariadne bus through the worker itself, the real verifier runs the fixture project's real pytest suite
on them, and the orchestrator merges and commits what passes.

The only stand-in is the model: claude_agent_sdk.query is replaced by a script that edits files in the
worker's cwd, the way a model would through its Edit/Write tools. No model calls, no cost; a live tier with
real models is tracked in issue #16 and is not in this suite.
"""

import asyncio
import subprocess
import sys
import types
from pathlib import Path

import pytest

from ariadne_intent import approved_plan
from daedalus.ariadne.diff_bus import AriadneBus
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.semantic_review import ReviewVerdict, SemanticReviewResult
from daedalus.ariadne.verification import CausalSliceVerifier
from daedalus.bus.icarus_bus import IcarusBus, WorkPackage
from daedalus.worker import harness
from daedalus.worker.harness import IcarusWorker

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
TEST_CALC = (
    "from calc import add, mul\n\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n\n"
    "def test_mul():\n    assert mul(2, 3) == 6\n"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A tiny Python project with a real, passing test suite, committed to HEAD."""
    repo = tmp_path / "project"
    (repo / "tests").mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test Runner")
    git(repo, "config", "core.autocrlf", "false")
    (repo / "calc.py").write_text(CALC, encoding="utf-8")
    (repo / "tests" / "test_calc.py").write_text(TEST_CALC, encoding="utf-8")
    (repo / "conftest.py").write_text("", encoding="utf-8")  # puts the repo root on sys.path for pytest
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture
def buses(tmp_path: Path):
    icarus = IcarusBus(root=tmp_path / "icarus")
    icarus.initialize()
    ariadne = AriadneBus(root=tmp_path / "ariadne")
    ariadne.initialize()
    return icarus, ariadne


@pytest.fixture
def fake_sdk(monkeypatch):
    """
    Replace the agent SDK in the harness with a scripted model. Each call to query() pops the next
    script: a function that edits files under the worker's cwd. Records the options it was called with.
    """
    scripts = []
    calls = []

    async def fake_query(prompt, options):
        async for _ in prompt:  # the harness streams the prompt; consume it like the SDK does
            pass
        calls.append(options)
        scripts.pop(0)(Path(options.cwd))
        yield types.SimpleNamespace(type="result", result="done")

    monkeypatch.setattr(harness, "HAS_AGENT_SDK", True)
    monkeypatch.setattr(harness, "query", fake_query, raising=False)  # absent without the SDK
    monkeypatch.setattr(harness, "ClaudeAgentOptions", lambda **kw: types.SimpleNamespace(**kw))
    monkeypatch.setattr(harness, "HookMatcher", lambda **kw: types.SimpleNamespace(**kw))
    return types.SimpleNamespace(scripts=scripts, calls=calls)


def edit(relpath: str, old: str, new: str):
    def script(cwd: Path):
        p = cwd / relpath
        p.write_text(p.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return script


def create(relpath: str, content: str):
    def script(cwd: Path):
        p = cwd / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return script


class ApproveAll:
    def review(self, diff, intent, verification=None):
        return SemanticReviewResult(diff_id=diff.id, verdict=ReviewVerdict.APPROVED,
                                    reasoning="stub", reviewer="stub")


def real_verifier(repo: Path) -> CausalSliceVerifier:
    # Real tests; type checking and lint off so the result doesn't depend on which tools are installed
    noop = [sys.executable, "-c", "pass"]
    return CausalSliceVerifier(repo, typecheck_cmd=noop, lint_cmd=noop,
                               test_cmd=[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"])


async def run_work(project: Path, buses, description: str, inputs=None, **worker_kwargs) -> dict:
    icarus, ariadne = buses
    work = WorkPackage(id="", type="implementation", description=description,
                       inputs={"ariadne_mode": True, **(inputs or {})}, outputs={})
    icarus.post_work(work)
    worker = IcarusWorker(project_root=str(project), bus=icarus, stream_output=False,
                          use_ariadne=True, **worker_kwargs)
    worker.ariadne_bus = ariadne
    try:
        return await worker.execute_work_package(work)
    finally:
        await worker.unregister()


def process(project: Path, ariadne: AriadneBus):
    orchestrator = AriadneOrchestrator(project, bus=ariadne, auto_commit=True, semantic_reviewer=ApproveAll())
    orchestrator.verifier = real_verifier(project)
    return orchestrator.process_pending()


# --- the worker -> Ariadne handoff ----------------------------------------------------------------

def test_worker_changes_reach_the_ariadne_bus(project, buses, fake_sdk):
    fake_sdk.scripts.append(edit("calc.py", "return a * b", "return b * a"))

    result = asyncio.run(run_work(project, buses, "Swap mul operands"))

    assert result["success"], result
    pending = buses[1].list_pending_diffs()
    assert len(pending) == 1
    assert "+    return b * a" in pending[0].content
    # The worker's edit is handed off, not left in the project's working tree
    assert git(project, "status", "--porcelain") == ""


def test_new_files_are_part_of_the_diff(project, buses, fake_sdk):
    fake_sdk.scripts.append(create("geometry.py", "def area(w, h):\n    return w * h\n"))

    asyncio.run(run_work(project, buses, "Add geometry.area"))

    pending = buses[1].list_pending_diffs()
    assert len(pending) == 1
    assert "geometry.py" in pending[0].content
    assert not (project / "geometry.py").exists()  # handed off, not left behind untracked


# --- through verification and merge ---------------------------------------------------------------

def test_good_change_is_verified_by_real_tests_and_committed(project, buses, fake_sdk):
    fake_sdk.scripts.append(edit("calc.py", "def mul(a, b):", "def mul(a, b):  # commutative"))
    plan = approved_plan(project, "Document mul")

    asyncio.run(run_work(project, buses, "Document mul", inputs={"plan_id": plan.id, "spec_id": "wp-1"}))
    result = process(project, buses[1])

    assert result.errors == [] and result.commits_created == 1, result
    assert "# commutative" in (project / "calc.py").read_text(encoding="utf-8")
    assert len(git(project, "log", "--oneline").splitlines()) == 2


def test_change_that_breaks_a_test_is_rejected_by_the_real_verifier(project, buses, fake_sdk):
    fake_sdk.scripts.append(edit("calc.py", "return a + b", "return a - b"))

    asyncio.run(run_work(project, buses, "Refactor add"))
    result = process(project, buses[1])

    assert result.diffs_rejected == 1 and result.commits_created == 0, result
    assert "return a + b" in (project / "calc.py").read_text(encoding="utf-8")
    assert len(git(project, "log", "--oneline").splitlines()) == 1


# --- isolation -----------------------------------------------------------------------------------

def test_parallel_workers_do_not_see_each_others_edits(project, buses, fake_sdk):
    seen = {}

    def worker_one(cwd: Path):
        edit("calc.py", "return a + b", "return b + a")(cwd)
        seen["one"] = (cwd, (cwd / "calc.py").read_text(encoding="utf-8"))

    def worker_two(cwd: Path):
        create("notes.md", "two\n")(cwd)
        seen["two"] = (cwd, (cwd / "calc.py").read_text(encoding="utf-8"))

    fake_sdk.scripts.extend([worker_one, worker_two])
    async def both():
        await asyncio.gather(run_work(project, buses, "one"), run_work(project, buses, "two"))

    asyncio.run(both())

    assert seen["one"][0] != seen["two"][0], "both workers ran in the same directory"
    assert "return a + b" in seen["two"][1], "worker two saw worker one's uncommitted edit"
    assert len(buses[1].list_pending_diffs()) == 2


def test_verifier_still_applies_the_diff_when_temp_is_inside_another_repo(project, buses, fake_sdk, tmp_path, monkeypatch):
    """
    If the temp directory sits inside some other git repository (a dotfiles repo in the home directory,
    say), 'git apply' in the verification copy used to resolve the patch against that outer repository,
    skip every file and exit 0, so the unchanged code was tested and a breaking change passed.
    """
    import tempfile

    outer = tmp_path / "outer"
    (outer / "tmp").mkdir(parents=True)
    git(outer, "init", "-q")
    monkeypatch.setattr(tempfile, "tempdir", str(outer / "tmp"))

    fake_sdk.scripts.append(edit("calc.py", "return a + b", "return a - b"))
    asyncio.run(run_work(project, buses, "Refactor add"))
    result = process(project, buses[1])

    assert result.diffs_rejected == 1 and result.commits_created == 0, result


# --- edict 0001 (amended): plan approval is intent approval, through the full path -----------------

def dispatch_and_run(project: Path, buses, plan, tmp_path: Path):
    """Planner plan -> Dispatcher -> Icarus bus -> real worker harness -> Ariadne -> orchestrator."""
    from daedalus.ariadne.dispatcher import Dispatcher

    icarus, ariadne = buses
    dispatcher = Dispatcher(icarus_bus=icarus, state_dir=tmp_path / "dispatch", repo_path=project)
    state = dispatcher.create_dispatch_state(plan)
    work_id = dispatcher.dispatch_package(plan.work_packages[0], state, project_root=project)
    work = icarus.get_work(work_id)
    worker = IcarusWorker(project_root=str(project), bus=icarus, stream_output=False, use_ariadne=True)
    worker.ariadne_bus = ariadne

    async def run():
        try:
            return await worker.execute_work_package(work)
        finally:
            await worker.unregister()

    asyncio.run(run())
    return process(project, ariadne)


def mul_plan(project: Path, approve: bool):
    from daedalus.ariadne.planner import FeatureRequest, Planner

    planner = Planner(project)
    plan = planner.analyze_feature(FeatureRequest.create("Document mul", "Add a comment to calc.mul. Files: calc.py"))
    if approve:
        planner.approve_plan(plan, approved_by="main-session")
    return plan


def test_package_from_an_approved_plan_auto_commits(project, buses, fake_sdk, tmp_path):
    """Fresh repo (no .daedalus/ before planning): approve the plan once, no human per diff."""
    assert not (project / ".daedalus").exists()
    fake_sdk.scripts.append(edit("calc.py", "def mul(a, b):", "def mul(a, b):  # commutative"))

    result = dispatch_and_run(project, buses, mul_plan(project, approve=True), tmp_path)

    assert result.errors == [] and result.commits_created == 1, result
    assert "# commutative" in (project / "calc.py").read_text(encoding="utf-8")
    merged = buses[1].list_all_diffs()[0]
    assert merged.metadata["plan_id"] and merged.metadata["spec_id"]
    assert "Work package" in merged.metadata["package"]          # the full package, not just a title
    assert ".daedalus" not in git(project, "ls-files")


def test_same_package_from_an_unapproved_plan_needs_review(project, buses, fake_sdk, tmp_path):
    fake_sdk.scripts.append(edit("calc.py", "def mul(a, b):", "def mul(a, b):  # commutative"))

    result = dispatch_and_run(project, buses, mul_plan(project, approve=False), tmp_path)

    assert result.commits_created == 0 and result.diffs_needs_review == 1, result
    diff = buses[1].list_needs_review_diffs()[0]
    assert "is not approved" in diff.semantic_review["reasoning"]


def test_dispatch_refuses_an_edict_with_an_open_dissent(project, buses, tmp_path):
    from daedalus.ariadne.dispatcher import Dispatcher
    from daedalus.ariadne.planner import FeatureRequest, Planner
    from daedalus.edicts import file_dissent

    (project / "docs/edicts").mkdir(parents=True)
    (project / "docs/edicts/0001-doc.md").write_text(
        "# Edict 0001: Document mul\nStatus: accepted\n\n## Intent\nComment mul.\n\n## Acceptance criteria\n- Commented.\n")
    plan = Planner(project).analyze_feature(FeatureRequest.from_edict(project, "1"))
    file_dissent(project, "1", "icarus", "o", "w", "i")
    dispatcher = Dispatcher(icarus_bus=buses[0], state_dir=tmp_path / "dispatch", repo_path=project)
    with pytest.raises(RuntimeError, match="open dissent"):
        dispatcher.dispatch_package(plan.work_packages[0], dispatcher.create_dispatch_state(plan), project_root=project)


def test_judge_prompt_includes_the_full_package(monkeypatch):
    from daedalus.ariadne import semantic_review
    from daedalus.ariadne.diff_bus import Diff

    seen = []
    monkeypatch.setattr(semantic_review, "HAS_AGENT_SDK", True)
    monkeypatch.setattr(semantic_review.LLMJudge, "_run_query", lambda self, prompt: seen.append(prompt) or "APPROVE\nok")
    diff = Diff.from_git_diff("w", "i", "", "title only")
    diff.metadata["package"] = "Work package wp-1: Orders\n\nAdd orders with validation and tests."
    semantic_review.LLMJudge().review(diff, "Edict 0009: approved intent")
    assert "## Work package as dispatched to the worker" in seen[0]
    assert "Add orders with validation and tests." in seen[0]
