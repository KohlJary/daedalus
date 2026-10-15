"""The Momus gate (edict 0016, T-h3): Daedalus's own `gh pr merge` needs a trial covering the branch."""

import json
import os
import stat
import subprocess
import sys

import pytest

from daedalus import hooks
from daedalus_hookkit import state as kit_state
from daedalus_hookkit.core import dispatch
from daedalus_hookkit.features import FEATURES, momus_gate
from daedalus_hookkit.features.momus_gate import merge_target

GATE = [f for f in FEATURES if f.name.startswith("momus gate")]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """main with one commit, then feat/x with a code commit; .daedalus present."""
    r = tmp_path / "proj"
    r.mkdir()
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                 "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    git(r, "init", "-q", "-b", "main")
    (r / ".daedalus").mkdir()
    (r / "a.py").write_text("x = 1\n")
    git(r, "add", "a.py")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-qb", "feat/x")
    (r / "a.py").write_text("x = 2\n")
    git(r, "commit", "-qam", "change")
    return r


def commit(r, path, text):
    (r / path).parent.mkdir(parents=True, exist_ok=True)
    (r / path).write_text(text)
    git(r, "add", path)
    git(r, "commit", "-qm", f"edit {path}")
    return git(r, "rev-parse", "HEAD")


def trial(r, branch, sha, name="t.md"):
    d = r / ".daedalus/momus/trials"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(f"# Trial: something\n\nCovers: {branch} @ {sha}\n\nVERDICT: contradicted\n")


def call(r, event, command, response=None, sid="s1"):
    p = {"session_id": sid, "cwd": str(r), "tool_name": "Bash", "tool_input": {"command": command}}
    if response is not None:
        p["tool_response"] = response
    out = dispatch(event, p, GATE)
    return json.loads(out)["hookSpecificOutput"] if out else {}


def create(r, number=7, body=""):
    return call(r, "PostToolUse", f'gh pr create --title t --body "{body}"',
                {"stdout": f"https://github.com/o/r/pull/{number}\n", "stderr": ""})


def fake_gh(tmp_path, monkeypatch, payload=None, hang=False):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    body = "import time; time.sleep(30)" if hang else f"print({json.dumps(json.dumps(payload or {}))})"
    gh.write_text(f"#!{sys.executable}\n{body}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


# ---------- parsing ----------


@pytest.mark.parametrize("command, target", [
    ("gh pr merge 12 --merge", "12"), ("cd x && gh pr merge 12", "12"), ("FOO=1 gh pr merge 12", "12"),
    ("gh pr merge https://github.com/o/r/pull/34 --squash", "34"), ("gh pr merge --merge", ""),
    ("echo gh pr merge", None), ('DAEDALUS_MOMUS_SKIP="two words" gh pr merge 5', "5"),
    ("git commit -m 'then gh pr merge 3'", None), ("cat <<'EOF'\ngh pr merge 4\nEOF", None), ("gh pr view 12", None), ("git commit -m 'gh pr merge 3'", None),
])
def test_merge_target(command, target):
    assert merge_target(command) == target


# ---------- the gate ----------


def test_no_trial_denies_naming_the_branch_and_pr(repo):
    create(repo)
    out = call(repo, "PreToolUse", "gh pr merge 7 --merge")
    assert out["permissionDecision"] == "deny"
    assert "PR #7" in out["permissionDecisionReason"] and "feat/x" in out["permissionDecisionReason"]
    assert kit_state.load("s1")["gate"]["blocks"] == 1


def test_a_trial_at_the_head_allows(repo):
    create(repo)
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    assert call(repo, "PreToolUse", "cd x && gh pr merge 7 --merge") == {}
    assert kit_state.load("s1")["gate"]["passes"] == 1


def test_a_trial_for_another_branch_denies(repo):
    create(repo)
    trial(repo, "feat/other", git(repo, "rev-parse", "HEAD"))
    assert call(repo, "PreToolUse", "gh pr merge 7")["permissionDecision"] == "deny"


def test_an_older_trial_covers_only_docs_commits_after_it(repo):
    reviewed = git(repo, "rev-parse", "HEAD")
    trial(repo, "feat/x", reviewed)
    commit(repo, "docs/notes.md", "n")
    create(repo, 8)
    assert call(repo, "PreToolUse", "gh pr merge 8") == {}
    commit(repo, "b.py", "y = 1\n")
    create(repo, 9)
    out = call(repo, "PreToolUse", "gh pr merge 9")
    assert out["permissionDecision"] == "deny" and "2 commits since the trial" in out["permissionDecisionReason"]


def test_a_docs_only_pr_passes(repo):
    git(repo, "checkout", "-q", "main")
    git(repo, "checkout", "-qb", "docs/y")
    commit(repo, "docs/a.md", "a")
    create(repo, 10)
    assert call(repo, "PreToolUse", "gh pr merge 10") == {}


def test_skips_pass_and_are_logged_with_their_reason(repo):
    create(repo)
    assert call(repo, "PreToolUse", 'DAEDALUS_MOMUS_SKIP="typo fix" gh pr merge 7') == {}
    create(repo, 11, body="momus: skip reverting a bad merge")
    assert call(repo, "PreToolUse", "gh pr merge 11") == {}
    st = kit_state.load("s1")
    assert st["gate"]["skips"] == 2
    assert [s["reason"] for s in st["skips"]] == ["typo fix", "reverting a bad merge"]


def test_a_pr_not_in_session_state_comes_from_gh(repo, tmp_path, monkeypatch):
    head = git(repo, "rev-parse", "HEAD")
    fake_gh(tmp_path, monkeypatch, {"number": 21, "headRefName": "feat/x", "headRefOid": head,
                                    "files": [{"path": "a.py"}], "body": ""})
    assert call(repo, "PreToolUse", "gh pr merge 21")["permissionDecision"] == "deny"
    trial(repo, "feat/x", head)
    assert call(repo, "PreToolUse", "gh pr merge 21") == {}


def test_a_hanging_gh_allows_the_merge_and_says_so(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, hang=True)
    monkeypatch.setattr(momus_gate, "GH_TIMEOUT", 0.5)
    out = call(repo, "PreToolUse", "gh pr merge 99")
    assert "permissionDecision" not in out and "didn't run" in out["additionalContext"]
    assert kit_state.load("s1")["gate"]["allowed_by_error"] == 1


def test_modes(repo):
    create(repo)
    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": "off"}}))
    assert call(repo, "PreToolUse", "gh pr merge 7") == {}
    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": "nudge"}}))
    out = call(repo, "PreToolUse", "gh pr merge 7")
    assert "permissionDecision" not in out and "merge gate" in out["additionalContext"]


def test_create_nudges_only_when_nothing_covers_the_branch(repo):
    out = create(repo)
    assert "no Momus trial covers feat/x" in out["additionalContext"]
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    assert create(repo, 12) == {}


def test_trials_are_read_from_the_claude_project_dir(repo, tmp_path, monkeypatch):
    """A submodule's .git is a file pointing into the parent; trials come from the project dir itself."""
    create(repo)
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    p = {"session_id": "s1", "cwd": str(elsewhere), "tool_name": "Bash", "tool_input": {"command": "gh pr merge 7"}}
    assert dispatch("PreToolUse", p, GATE) == ""


# ---------- registration and config ----------


def test_the_gate_registers_pre_and_post_tool_use_and_off_removes_them(tmp_path):
    hooks.register_hooks(tmp_path, enabled={"session_start": True, "momus_gate": "gate"}, kit=True)
    s = json.loads((tmp_path / ".claude/settings.json").read_text())["hooks"]
    assert s["PreToolUse"] == [{"matcher": "Bash", "hooks": [{"type": "command", "command": "daedalus-hook PreToolUse"}]}]
    assert "PostToolUse" in s
    hooks.register_hooks(tmp_path, enabled={"session_start": True, "momus_gate": "off"}, kit=True)
    s = json.loads((tmp_path / ".claude/settings.json").read_text())["hooks"]
    assert "PreToolUse" not in s and "PostToolUse" not in s


def test_config_accepts_the_modes_and_refuses_others(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from daedalus.cli.main import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".daedalus").mkdir()
    assert CliRunner().invoke(main, ["config", "--project", "hooks.momus_gate", "nudge"]).exit_code == 0
    assert CliRunner().invoke(main, ["config", "--project", "hooks.momus_gate", "maybe"]).exit_code != 0


def test_momus_constitution_requires_the_covers_line():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "src/daedalus/plugin/agents/momus.md").read_text()
    assert "Covers: <branch> @ <full head sha>" in text
    parsed = momus_gate.COVERS.findall("# Trial\n\nCovers: feat/0016-hook-kit @ f04d4b23e9b5226c8989676b4636a3e78a05b1bd\n")
    assert parsed == [("feat/0016-hook-kit", "f04d4b23e9b5226c8989676b4636a3e78a05b1bd")]
