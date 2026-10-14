"""Edict 0001 (amended) and 0003: approved intent, failing closed, dissent, done transitions.

Approved intent is an accepted edict's Intent and Acceptance criteria, or an approved plan's work
package. Everything else goes to NEEDS_REVIEW in every autonomy mode, without asking the judge.
"""

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.ariadne.diff_bus import AriadneBus, Diff, DiffStatus
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.planner import FeatureRequest, Planner
from daedalus.ariadne.semantic_review import ReviewVerdict, SemanticReviewResult
from daedalus.ariadne.verification import CausalSliceVerifier
from daedalus.cli.main import main
from daedalus.edicts import dispatch_block, file_dissent, list_dissents, load_edict, resolve_dissent

from ariadne_intent import approved_plan, tag

EDICT = """# Edict 0007: Square things
Status: accepted

## Intent
Make a() return 42.

## Constraints
- Keep it small.

## Acceptance criteria
- a() returns 42.
"""


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@e.com")
    git(r, "config", "user.name", "T")
    (r / "file_a.py").write_text("def a():\n    return 1\n")
    (r / "notes.txt").write_text("human notes\n")
    (r / "docs/edicts").mkdir(parents=True)
    (r / "docs/edicts/0007-square.md").write_text(EDICT)
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    return r


@pytest.fixture
def bus(tmp_path):
    b = AriadneBus(root=tmp_path / "bus")
    b.initialize()
    return b


class Recorder:
    def __init__(self, verdict=ReviewVerdict.APPROVED):
        self.verdict, self.calls = verdict, []

    def review(self, diff, intent, verification=None):
        self.calls.append(intent)
        return SemanticReviewResult(diff_id=diff.id, verdict=self.verdict, reasoning="stub", reviewer="stub")


def diff_for(repo, content="def a():\n    return 42\n", filename="file_a.py"):
    (repo / filename).write_text(content)
    git(repo, "add", "-N", filename)
    text = git(repo, "diff", "--", filename)
    git(repo, "checkout", "--", filename) if filename == "file_a.py" else (repo / filename).unlink()
    git(repo, "reset", "-q")
    return Diff.from_git_diff("work-1", "worker-1", text, "worker says: does everything right")


def orchestrate(repo, bus, reviewer, autonomy="full"):
    o = AriadneOrchestrator(repo, bus=bus, auto_commit=True, autonomy=autonomy, semantic_reviewer=reviewer)
    noop = ["python", "-c", "pass"]
    o.verifier = CausalSliceVerifier(repo, typecheck_cmd=noop, lint_cmd=noop, test_cmd=noop)
    return o.process_pending()


def review_of(bus, diff):
    return bus.get_diff(diff.id)


# ---------- failing closed ----------


@pytest.mark.parametrize("autonomy", ["full", "hybrid", "supervised"])
def test_ad_hoc_diff_needs_review_in_every_mode_without_asking_the_judge(repo, bus, autonomy):
    d = diff_for(repo)
    d.metadata["intent"] = "Anything goes"       # a worker-supplied intent is not approved intent
    bus.submit_diff(d)
    judge = Recorder()
    result = orchestrate(repo, bus, judge, autonomy)
    assert result.commits_created == 0 and judge.calls == []
    stored = review_of(bus, d)
    assert stored.status == DiffStatus.NEEDS_REVIEW
    assert stored.semantic_review["reviewer"] == "intent-gate"
    assert "not tied to an edict" in stored.semantic_review["reasoning"]


def test_no_fallback_to_the_worker_description(repo):
    o = AriadneOrchestrator(repo, bus=AriadneBus(root=repo / ".bus"))
    assert o._diff_intent(Diff.from_git_diff("w", "i", "", "worker description")) == ""


# ---------- intent from an edict ----------


def test_intent_comes_from_the_edict_file(repo, bus):
    d = diff_for(repo)
    d.metadata.update(edict="0007", intent="Delete everything")   # metadata is never trusted
    bus.submit_diff(d)
    judge = Recorder()
    result = orchestrate(repo, bus, judge)
    assert result.commits_created == 1
    assert "Make a() return 42." in judge.calls[0] and "a() returns 42." in judge.calls[0]
    assert "Delete everything" not in judge.calls[0]


def test_edicts_off_means_no_edict_intent(repo, bus):
    (repo / ".daedalus").mkdir()
    (repo / ".daedalus/config.json").write_text(json.dumps({"edicts": {"enabled": False}}))
    d = diff_for(repo)
    d.metadata["edict"] = "0007"
    bus.submit_diff(d)
    assert orchestrate(repo, bus, Recorder()).commits_created == 0
    assert "edicts are off" in review_of(bus, d).semantic_review["reasoning"]


def test_edicts_off_still_allows_approved_plans(repo, bus):
    (repo / ".daedalus").mkdir()
    (repo / ".daedalus/config.json").write_text(json.dumps({"edicts": {"enabled": False}}))
    bus.submit_diff(tag(diff_for(repo), approved_plan(repo, "Return 42")))
    assert orchestrate(repo, bus, Recorder()).commits_created == 1


@pytest.mark.parametrize("status", ["proposed", "done"])
def test_only_accepted_edicts_give_intent(repo, bus, status):
    path = repo / "docs/edicts/0007-square.md"
    path.write_text(EDICT.replace("Status: accepted", f"Status: {status}"))
    d = diff_for(repo)
    d.metadata["edict"] = "0007"
    bus.submit_diff(d)
    assert orchestrate(repo, bus, Recorder()).commits_created == 0


# ---------- intent from an approved plan ----------


def test_approved_plan_package_is_the_intent(repo, bus):
    plan = approved_plan(repo, "Return 42", approved_by="main-session")
    bus.submit_diff(tag(diff_for(repo), plan))
    judge = Recorder()
    assert orchestrate(repo, bus, judge).commits_created == 1
    assert "Approved plan" in judge.calls[0] and "approved by main-session" in judge.calls[0]
    assert "Work package wp-1: Return 42 (wp-1)" in judge.calls[0]


def test_unapproved_plan_needs_review(repo, bus):
    d = tag(diff_for(repo), approved_plan(repo, "Return 42", approve=False))
    bus.submit_diff(d)
    assert orchestrate(repo, bus, Recorder()).commits_created == 0
    assert "is not approved" in review_of(bus, d).semantic_review["reasoning"]


def test_editing_a_plan_after_approval_voids_it(repo, bus):
    plan = approved_plan(repo, "Return 42")
    planner = Planner(repo)
    stored = planner.load_plan(plan.id)
    stored.work_packages[0].description = "Also delete the tests."
    planner.save_plan(stored)
    d = tag(diff_for(repo), plan)
    bus.submit_diff(d)
    assert orchestrate(repo, bus, Recorder()).commits_created == 0
    assert "changed after it was approved" in review_of(bus, d).semantic_review["reasoning"]


def test_approving_an_edited_plan_object_covers_the_edits(repo, bus):
    """A planner that rewrites packages after analyze_feature: approve the object it will dispatch."""
    planner = Planner(repo)
    plan = planner.analyze_feature(FeatureRequest.create("Return 42", "Make a() return 42."))
    plan.work_packages[0].description = "Rewritten by an LLM planner"
    planner.approve_plan(plan, approved_by="kohl")
    assert planner.load_plan(plan.id).approval_valid()
    assert planner.load_plan(plan.id).work_packages[0].description == "Rewritten by an LLM planner"


def test_plan_from_an_edict_follows_the_edict(repo, bus):
    planner = Planner(repo)
    plan = planner.analyze_feature(FeatureRequest.from_edict(repo, "7"))
    assert plan.edict == "0007" and all(wp.edict == "0007" for wp in plan.work_packages)
    assert "Make a() return 42." in plan.source
    planner.approve_plan(plan, approved_by="kohl")
    file_dissent(repo, "7", "daedalus", "x", "y", "z")
    d = tag(diff_for(repo), plan, plan.work_packages[0].id)
    d.metadata["edict"] = "0007"
    bus.submit_diff(d)
    assert orchestrate(repo, bus, Recorder()).commits_created == 0
    assert "open dissent" in review_of(bus, d).semantic_review["reasoning"]


# ---------- dissent (0003) ----------


def test_dissent_lifecycle_pauses_and_keeps_history(repo):
    assert dispatch_block(repo, "7") is None
    path = file_dissent(repo, "7", "Daedalus", "The criteria", "They contradict", "Split it")
    assert path.name == "0007-daedalus.md"
    assert "open dissent" in dispatch_block(repo, "7")
    with pytest.raises(ValueError, match="open dissent"):
        FeatureRequest.from_edict(repo, "7")
    assert load_edict(repo, "7").text == EDICT                    # never edits the edict

    second = file_dissent(repo, "7", "Daedalus", "a", "b", "c")
    assert second.name == "0007-daedalus-2.md"
    resolve_dissent(repo, "0007-daedalus", "overruled", "Criteria are fine as written.")
    resolve_dissent(repo, "0007-daedalus-2", "withdrawn", "Agent withdrew it.")
    assert dispatch_block(repo, "7") is None
    text = path.read_text()
    assert "Status: resolved" in text and "## Objection\nThe criteria" in text and "Outcome: overruled" in text
    assert [d.outcome for d in list_dissents(repo, open_only=False)] == ["overruled", "withdrawn"]
    assert list_dissents(repo) == []


def test_dissent_requires_all_three_parts(repo):
    from daedalus.edicts import EdictError
    with pytest.raises(EdictError, match="instead"):
        file_dissent(repo, "7", "daedalus", "x", "y", " ")


def test_dissent_cli(repo, monkeypatch):
    monkeypatch.chdir(repo)
    r = CliRunner()
    out = r.invoke(main, ["edict", "dissent", "7", "--objection", "o", "--why", "w", "--instead", "i"])
    assert out.exit_code == 0 and "paused" in out.output
    assert "0007-daedalus  edict 0007  open" in r.invoke(main, ["edict", "dissents"]).output
    out = r.invoke(main, ["edict", "resolve-dissent", "0007-daedalus", "--outcome", "amended", "--note", "Fixed."])
    assert out.exit_code == 0
    assert "No open dissents." in r.invoke(main, ["edict", "dissents"]).output
    assert "resolved (amended)" in r.invoke(main, ["edict", "dissents", "--all"]).output


def test_hydrate_adds_an_ask_rule_for_resolving(repo, monkeypatch):
    monkeypatch.chdir(repo)
    CliRunner().invoke(main, ["hydrate", "--no-agents", "--no-template", "--no-skills"])
    settings = json.loads((repo / ".claude/settings.json").read_text())
    assert "Bash(daedalus edict resolve-dissent:*)" in settings["permissions"]["ask"]


# ---------- done transitions and exact commits ----------


def test_edict_moves_to_done_when_all_planned_work_has_merged(repo, bus):
    planner = Planner(repo)
    plan = planner.analyze_feature(FeatureRequest.from_edict(repo, "7"))
    from daedalus.ariadne.planner import WorkPackageSpec
    plan.work_packages = [WorkPackageSpec(id="wp-1", title="a", description="a", edict="0007"),
                          WorkPackageSpec(id="wp-2", title="b", description="b", edict="0007")]
    planner.approve_plan(plan, approved_by="kohl")

    d1 = tag(diff_for(repo), plan, "wp-1")
    d1.metadata["edict"] = "0007"
    bus.submit_diff(d1)
    result = orchestrate(repo, bus, Recorder())
    assert result.commits_created == 1 and result.edicts_done == 0
    assert load_edict(repo, "7").status == "accepted"

    d2 = tag(diff_for(repo, "x = 1\n", "new_module.py"), plan, "wp-2")
    d2.metadata["edict"] = "0007"
    bus.submit_diff(d2)
    result = orchestrate(repo, bus, Recorder())
    assert result.commits_created == 1 and result.edicts_done == 1
    assert load_edict(repo, "7").status == "done"
    assert "Edict 0007: done" in git(repo, "log", "-1", "--format=%s")
    assert git(repo, "status", "--porcelain", "docs/") == ""


def test_commit_contains_only_the_diff(repo, bus):
    (repo / "notes.txt").write_text("human work in progress\n")          # tracked, modified, unrelated
    plan = approved_plan(repo, "Add a module")
    bus.submit_diff(tag(diff_for(repo, "x = 1\n", "new_module.py"), plan))
    assert orchestrate(repo, bus, Recorder()).commits_created == 1
    committed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert committed == ["new_module.py"]                                   # new file included
    assert "human work in progress" in (repo / "notes.txt").read_text()     # left alone, uncommitted
    assert " M notes.txt" in git(repo, "status", "--porcelain")
    assert ".daedalus" not in git(repo, "ls-files")                          # plan files never committed
