"""reconstruct check: the deterministic gate on a proposal (edict 0006).

The cases are the mistakes the first, hand-run reconstruction made (wonderland-ai, 2026-10-13):
a referenced file that didn't exist, commits nothing cited, 'done' proposed on weaker evidence,
plus fabricated and out-of-window hashes.
"""

import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.reconstruct import PROPOSAL_SCHEMA, check_proposal, gather, write_bundle

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t", "PATH": os.environ["PATH"]}


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def commit(repo, msg, files=None):
    for name, text in (files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    shas = {"before": commit(tmp_path, "old work, before the plan")}
    data = gp.empty_gameplan()
    gp.add_phase(data, "p20", "Pilot")
    gp.activate_phase(data, "p20")
    gp.add_task(data, "T-a1", "Trace milestone deletion")
    gp.add_task(data, "T-a6", "Coherence review")
    gp.save_gameplan(tmp_path, data)
    (tmp_path / ".daedalus/roadmap/index.json").write_text(json.dumps(
        {"items": [{"id": "r1", "title": "Release", "status": "backlog"},
                   {"id": "r2", "title": "Something else", "status": "backlog"}]}))
    shas["gameplan"] = commit(tmp_path, "gameplan")
    shas["fix"] = commit(tmp_path, "fix(agent): decision filter must not delete milestone files",
                         {"src/agent.py": "x = 1\n", "analyses/048.md": "# 048\n"})
    shas["release"] = commit(tmp_path, "release 0.12.1")
    shas["diagrams"] = commit(tmp_path, "feat(diagrams): registry")
    bundle = gather(tmp_path)
    shas["_bundle"] = str(write_bundle(tmp_path, bundle).relative_to(tmp_path))
    shas["_window"] = bundle.window
    return tmp_path, shas


def proposal(shas, **overrides):
    base = {
        "schema": PROPOSAL_SCHEMA,
        "bundle": shas["_bundle"],
        "window": dict(shas["_window"]),
        "evidence_scope": "git",
        "updates": [{
            "task": "T-a1", "proposed_status": "needs-confirmation", "confidence": "inferred", "basis": "both",
            "resolution": f"Probable cause fixed in {shas['fix'][:7]}; see analyses/048.md.",
            "commits": [shas["fix"]], "cheapest_check": "Replay the 03:08:49 utterance against the old code.",
        }],
        "phases": [{
            "id": "p21-diagrams", "title": "Diagrams", "status": "done", "confidence": "shown",
            "basis": "messages", "commits": [shas["diagrams"]],
            "tasks": [{"id": "R-1", "title": "Registry", "status": "done", "confidence": "shown",
                       "basis": "messages", "resolution": "Registry shipped.", "commits": [shas["diagrams"]]}],
        }],
        "roadmap": [{"item": "r1", "current_status": "backlog", "proposed_status": "done",
                     "confidence": "shown", "basis": "messages", "commits": [shas["release"]]}],
        "roadmap_unchanged": ["r2"],
        "conflicts": [],
        "context_commits": [],
        "files": [],
    }
    base.update(overrides)
    return base


def errors(repo, p):
    return check_proposal(repo, p).errors


def test_valid_proposal_passes_with_full_coverage(repo):
    path, shas = repo
    result = check_proposal(path, proposal(shas))
    assert result.errors == []
    assert result.uncited == []
    assert result.labels == {"inferred": 1, "shown": 3}


def test_uncited_commits_are_reported_by_hash(repo):
    path, shas = repo
    p = proposal(shas, roadmap=[], roadmap_unchanged=["r1", "r2"])
    result = check_proposal(path, p)
    assert result.errors == [] and result.uncited == [shas["release"]]


def test_fabricated_and_out_of_window_hashes(repo):
    path, shas = repo
    p = proposal(shas)
    p["phases"][0]["tasks"][0]["commits"] = ["deadbee1234"]
    p["roadmap"][0]["commits"] = [shas["before"]]
    errs = errors(path, p)
    assert any("deadbee1234 is not a commit" in e for e in errs)
    assert any(f"{shas['before']} is outside the window" in e for e in errs)

    p["context_commits"] = [shas["before"]]
    assert not any("outside the window" in e for e in errors(path, p))


def test_done_needs_shown_and_needs_confirmation_needs_a_check(repo):
    path, shas = repo
    p = proposal(shas)
    p["updates"][0].update(proposed_status="done")              # the T-a1 mistake
    assert any("proposes done on 'inferred' evidence" in e for e in errors(path, p))
    p["updates"][0].update(proposed_status="needs-confirmation", cheapest_check="")
    assert any("needs-confirmation without a cheapest_check" in e for e in errors(path, p))


def test_missing_referenced_file(repo):
    path, shas = repo
    p = proposal(shas, description="See REPORT.md for the critic's verdicts.")   # the hand run's REPORT.md
    p["updates"][0]["files"] = ["analyses/999-missing.md"]
    errs = errors(path, p)
    assert any("analyses/999-missing.md does not exist" in e for e in errs)
    assert any("REPORT.md is referenced but does not exist" in e for e in errs)
    # bare names that exist somewhere in the repo are fine
    p = proposal(shas, description="Details in 048.md and src/agent.py:12.")
    assert errors(path, p) == []


def test_labels_basis_and_citations_required(repo):
    path, shas = repo
    p = proposal(shas)
    p["phases"][0]["tasks"][0].update(confidence="probably", commits=[])
    p["roadmap"][0].update(basis="vibes")
    errs = errors(path, p)
    assert any("confidence is 'probably'" in e for e in errs)
    assert any("basis is 'vibes'" in e for e in errs)
    p["phases"][0]["tasks"][0].update(confidence="shown", resolution="Shipped.")
    assert any("confidence shown but cites no commit" in e for e in errors(path, p))


def test_unknown_outcome_needs_no_citation(repo):
    path, shas = repo
    p = proposal(shas)
    p["phases"][0]["tasks"].append({"id": "R-2", "title": "Pilot outcome", "status": "unknown",
                                    "confidence": "unknown", "resolution": None})
    assert errors(path, p) == []


def test_update_must_target_an_open_task(repo):
    path, shas = repo
    p = proposal(shas)
    p["updates"][0]["task"] = "T-zz"
    assert any("'T-zz' is not an open task" in e for e in errors(path, p))


def test_conflicts_record_both_sources(repo):
    path, shas = repo
    p = proposal(shas, conflicts=[{"about": "cause of the 42-minute loop", "sources": [shas["fix"]]}])
    assert any("at least two sources" in e for e in errors(path, p))


def test_cli_exit_codes(repo, monkeypatch, tmp_path_factory):
    path, shas = repo
    monkeypatch.chdir(path)
    good = tmp_path_factory.mktemp("p") / "good.json"
    good.write_text(json.dumps(proposal(shas)))
    result = CliRunner().invoke(main, ["reconstruct", "check", str(good)])
    assert result.exit_code == 0 and "Coverage: every commit in the window is cited." in result.output

    bad = proposal(shas)
    bad["updates"][0]["proposed_status"] = "done"
    good.write_text(json.dumps(bad))
    result = CliRunner().invoke(main, ["reconstruct", "check", str(good)])
    assert result.exit_code == 1 and "1 error(s)" in result.output



# ---------- holes Momus found in the first build ----------


def test_window_comes_from_the_bundle(repo):
    path, shas = repo
    p = proposal(shas)
    p["window"] = {"from": None, "from_date": "2000-01-01", "to": shas["diagrams"]}   # widened by hand
    p["roadmap"][0]["commits"] = [shas["before"]]
    errs = errors(path, p)
    assert any("window does not match the bundle" in e for e in errs)
    assert any("outside the window" in e for e in errs)

    p = proposal(shas, bundle=".daedalus/reconstruction/nope.json")
    assert any("is missing or not a gather bundle" in e for e in errors(path, p))


def test_phase_task_cannot_reuse_an_existing_task_id(repo):
    path, shas = repo
    p = proposal(shas)
    p["phases"][0]["tasks"].append({"id": "T-a1", "title": "sneaky", "status": "done",
                                    "confidence": "inferred", "basis": "both", "commits": [shas["fix"]]})
    assert any("task id 'T-a1' already exists" in e for e in errors(path, p))


def test_roadmap_done_needs_shown_and_an_existing_item(repo):
    path, shas = repo
    p = proposal(shas)
    p["roadmap"][0]["confidence"] = "inferred"
    assert any("roadmap[0] (r1): proposes done on 'inferred'" in e for e in errors(path, p))
    p = proposal(shas)
    p["roadmap"].append({"item": "r9", "current_status": "backlog", "proposed_status": "ready",
                         "confidence": "shown", "basis": "messages", "commits": [shas["fix"]]})
    assert any("roadmap item 'r9' is not in the roadmap" in e for e in errors(path, p))


def test_every_open_roadmap_item_is_accounted_for(repo):
    path, shas = repo
    p = proposal(shas, roadmap_unchanged=[])
    assert any("1 open roadmap item(s) in the bundle are neither" in e and "r2" in e for e in errors(path, p))


def test_conflict_hashes_are_validated_and_not_coverage(repo):
    path, shas = repo
    p = proposal(shas, roadmap=[], roadmap_unchanged=["r1", "r2"],
                 conflicts=[{"about": "x", "sources": ["deadbee1234", shas["release"]]}])
    result = check_proposal(path, p)
    assert any("conflicts[0]: deadbee1234 is not a commit" in e for e in result.errors)
    assert shas["release"] in result.uncited


def test_shown_phase_needs_commits_somewhere(repo):
    path, shas = repo
    p = proposal(shas)
    p["phases"][0]["commits"] = []
    p["phases"][0]["tasks"][0].update(confidence="unknown", commits=[], resolution=None)
    assert any("neither the phase nor its tasks cite a commit" in e for e in errors(path, p))


def test_no_false_alarm_for_paths_with_spaces(repo):
    path, shas = repo
    (path / "docs").mkdir()
    (path / "docs/my notes.md").write_text("x")
    git(path, "add", "-A")
    p = proposal(shas, description="Background in docs/my notes.md.")
    assert errors(path, p) == []


def test_malformed_entries_are_errors_not_crashes(repo):
    path, shas = repo
    p = proposal(shas, updates=["x"], phases=[{"id": "p", "title": "t", "confidence": "unknown", "tasks": "no"}])
    errs = errors(path, p)
    assert "updates must be a list of objects" in errs
    assert "phases[0].tasks must be a list of objects" in errs
    assert errors(path, ["not", "a", "dict"]) == ["the proposal must be a JSON object"]


def test_stale_bundle_is_detected(repo):
    path, shas = repo
    bundle_file = path / shas["_bundle"]
    data = json.loads(bundle_file.read_text())
    data["commits"] = data["commits"][1:]
    bundle_file.write_text(json.dumps(data))
    assert any("no longer match the repository" in e for e in errors(path, proposal(shas)))
