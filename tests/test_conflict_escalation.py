"""Escalated conflicts are recorded and hold their diffs out of commits (gameplan T-e14).

Before: process_pending detected conflicts but never stored the escalated ones, so its check for
unresolved conflicts was always empty, and incompatible diffs merged into one commit. Cases are the
Ariadne session's no-model repro (exp/ariadne-local, gate_exp/repro_conflict_escalation.py).
"""

import subprocess
import sys

import pytest

from daedalus import config as config_module
from daedalus.ariadne import orchestrator as orch_mod
from daedalus.ariadne.diff_bus import AriadneBus, Diff, DiffStatus
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.ariadne.semantic_review import ReviewVerdict, SemanticReviewResult
from daedalus.ariadne.verification import CausalSliceVerifier

from ariadne_intent import approved_plan, tag

CALC = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"


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
    (r / "calc.py").write_text(CALC)
    (r / "notes.md").write_text("notes\n")
    git(r, "add", ".")
    git(r, "commit", "-q", "-m", "init")
    return r


@pytest.fixture
def bus(tmp_path):
    b = AriadneBus(root=tmp_path / "bus")
    b.initialize()
    return b


class ApproveAll:
    def review(self, diff, intent, verification=None):
        return SemanticReviewResult(diff_id=diff.id, verdict=ReviewVerdict.APPROVED, reasoning="stub", reviewer="stub")


def change(repo, path, content):
    original = (repo / path).read_text()
    (repo / path).write_text(content)
    text = git(repo, "diff", "--", path)
    (repo / path).write_text(original)
    return text


def submit(repo, bus, plan, spec, path, content):
    d = tag(Diff.from_git_diff(f"work-{spec}", "worker", change(repo, path, content), spec), plan, spec)
    bus.submit_diff(d)
    return d


def process(repo, bus):
    o = AriadneOrchestrator(repo, bus=bus, auto_commit=True, autonomy="full", semantic_reviewer=ApproveAll())
    noop = [sys.executable, "-c", "pass"]
    o.verifier = CausalSliceVerifier(repo, typecheck_cmd=noop, lint_cmd=noop, test_cmd=noop,
                                     require_tests=False)
    return o.process_pending()


REJECTS_NEGATIVES = CALC.replace("    return a + b", "    if a < 0 or b < 0:\n        raise ValueError\n    return a + b")
RELIES_ON_NEGATIVES = CALC + "\n\ndef sum_all(xs):\n    total = 0\n    for x in xs:\n        total = add(total, x)\n    return total\n"


def test_incompatible_different_line_pair_is_held_not_merged(repo, bus):
    plan = approved_plan(repo, "calc changes", packages=("wp-a", "wp-b"))
    a = submit(repo, bus, plan, "wp-a", "calc.py", REJECTS_NEGATIVES)
    b = submit(repo, bus, plan, "wp-b", "calc.py", RELIES_ON_NEGATIVES)
    result = process(repo, bus)
    assert result.conflicts_detected == 1 and result.commits_created == 0 and result.diffs_held == 2
    (conflict,) = bus.list_conflicts(resolved=False)
    assert {conflict.diff_a_id, conflict.diff_b_id} == {a.id, b.id}
    assert git(repo, "log", "--oneline").count("\n") == 1

    again = process(repo, bus)                         # the held pair stays held, and isn't re-recorded
    assert again.commits_created == 0 and again.conflicts_detected == 0 and again.diffs_held == 2


def test_unrelated_diff_still_lands_while_a_pair_is_held(repo, bus):
    plan = approved_plan(repo, "changes", packages=("wp-a", "wp-b", "wp-c"))
    submit(repo, bus, plan, "wp-a", "calc.py", REJECTS_NEGATIVES)
    submit(repo, bus, plan, "wp-b", "calc.py", RELIES_ON_NEGATIVES)
    c = submit(repo, bus, plan, "wp-c", "notes.md", "notes, updated\n")
    result = process(repo, bus)
    assert result.commits_created == 1 and result.diffs_held == 2
    assert bus.get_diff(c.id).status == DiffStatus.MERGED
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["notes.md"]


def test_a_new_diff_is_checked_against_one_held_from_an_earlier_cycle(repo, bus):
    plan = approved_plan(repo, "changes", packages=("wp-a", "wp-b", "wp-c"))
    submit(repo, bus, plan, "wp-a", "calc.py", REJECTS_NEGATIVES)
    submit(repo, bus, plan, "wp-b", "calc.py", RELIES_ON_NEGATIVES)
    process(repo, bus)
    submit(repo, bus, plan, "wp-c", "calc.py", CALC.replace("return a * b", "return b * a"))
    result = process(repo, bus)
    assert result.conflicts_detected >= 1 and result.commits_created == 0


def test_resolving_with_reject_lets_the_earlier_diff_land(repo, bus, monkeypatch, capsys):
    plan = approved_plan(repo, "calc changes", packages=("wp-a", "wp-b"))
    a = submit(repo, bus, plan, "wp-a", "calc.py", REJECTS_NEGATIVES)
    b = submit(repo, bus, plan, "wp-b", "calc.py", RELIES_ON_NEGATIVES)
    process(repo, bus)
    (conflict,) = bus.list_conflicts(resolved=False)

    monkeypatch.setattr(orch_mod, "AriadneBus", lambda *x, **k: bus)
    monkeypatch.setattr(sys, "argv", ["ariadne", "--repo", str(repo), "conflicts", "list"])
    orch_mod.main()
    assert "UNRESOLVED: holding both diffs" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["ariadne", "--repo", str(repo), "conflicts", "resolve", conflict.id,
                                      "--strategy", "reject", "--note", "b relies on old add()"])
    orch_mod.main()

    result = process(repo, bus)
    assert result.commits_created == 1
    assert bus.get_diff(a.id).status == DiffStatus.MERGED
    assert bus.get_diff(b.id).status == DiffStatus.REJECTED
    assert "raise ValueError" in (repo / "calc.py").read_text() and "sum_all" not in (repo / "calc.py").read_text()


def test_conflict_ids_are_unique_per_pair_and_order_independent():
    from daedalus.ariadne.diff_bus import make_conflict_id
    assert make_conflict_id("diff-3aaaaaaaaaaa", "diff-3bbbbbbbbbbb") != make_conflict_id("diff-3aaaaaaaaaaa", "diff-3ccccccccccc")
    assert make_conflict_id("diff-1", "diff-2") == make_conflict_id("diff-2", "diff-1")



def test_a_touched_but_unchanged_file_still_commits(repo, bus):
    """git apply --index trusts cached stat data; a rewritten-but-identical file must not block a commit."""
    import os
    import time
    plan = approved_plan(repo, "calc change")
    submit(repo, bus, plan, "wp-1", "calc.py", REJECTS_NEGATIVES)
    path = repo / "calc.py"
    path.write_text(path.read_text())                      # same bytes, new mtime
    later = time.time() + 5
    os.utime(path, (later, later))
    result = process(repo, bus)
    assert result.errors == [] and result.commits_created == 1
