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


def fake_gh(tmp_path, monkeypatch, payload=None, hang=False, fail=False):
    """A gh on PATH that prints `payload` as JSON (or fails, or hangs). Replaces any earlier fake."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    if hang:
        body = "import time; time.sleep(30)"
    elif fail:
        body = "import sys; sys.stderr.write('not a github repo'); sys.exit(1)"
    else:
        body = f"print({json.dumps(json.dumps(payload or {}))})"
    gh.write_text(f"#!{sys.executable}\n{body}\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    if str(bindir) not in os.environ["PATH"]:
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture(autouse=True)
def no_real_gh(tmp_path, monkeypatch):
    """No test reaches GitHub: by default gh fails, so the gate falls back to session state."""
    fake_gh(tmp_path, monkeypatch, fail=True)


def gh_says(tmp_path, monkeypatch, repo, number=7, files=("a.py",), body="", head=None, branch="feat/x"):
    fake_gh(tmp_path, monkeypatch, {"number": number, "headRefName": branch,
                                    "headRefOid": head or git(repo, "rev-parse", "HEAD"),
                                    "files": [{"path": f} for f in files], "body": body})


# ---------- parsing ----------


@pytest.mark.parametrize("command, target", [
    ("gh pr merge 12 --merge", "12"), ("cd x && gh pr merge 12", "12"), ("FOO=1 gh pr merge 12", "12"),
    ("gh pr merge https://github.com/o/r/pull/34 --squash", "34"), ("gh pr merge --merge", ""),
    ("echo gh pr merge", None), ('DAEDALUS_MOMUS_SKIP="two words" gh pr merge 5', "5"),
    ("if ok; then gh pr merge 53 --merge; fi", "53"), ("gh pr merge --subject 'x y' 12", "12"),
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


def test_a_docs_only_pr_passes_and_an_empty_one_does_not(repo, tmp_path, monkeypatch):
    gh_says(tmp_path, monkeypatch, repo, 10, files=["docs/guide/setup.txt", "README.md"])
    assert call(repo, "PreToolUse", "gh pr merge 10") == {}
    gh_says(tmp_path, monkeypatch, repo, 10, files=["src/docs.py"])
    assert call(repo, "PreToolUse", "gh pr merge 10")["permissionDecision"] == "deny"
    gh_says(tmp_path, monkeypatch, repo, 10, files=[])
    assert call(repo, "PreToolUse", "gh pr merge 10")["permissionDecision"] == "deny"


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


def test_the_gh_timeout_is_five_seconds():
    assert momus_gate.GH_TIMEOUT == 5


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


# ---------- Momus's review of the first version (trial 2026-10-15-momus-gate.md) ----------


def test_d1_a_commit_after_create_is_checked_at_merge_time(repo, tmp_path, monkeypatch):
    create(repo)
    reviewed = git(repo, "rev-parse", "HEAD")
    trial(repo, "feat/x", reviewed)
    newer = commit(repo, "b.py", "y = 2\n")
    gh_says(tmp_path, monkeypatch, repo, head=newer)
    out = call(repo, "PreToolUse", "gh pr merge 7")
    assert out["permissionDecision"] == "deny" and "1 commit since the trial" in out["permissionDecisionReason"]
    trial(repo, "feat/x", newer, name="t2.md")
    assert call(repo, "PreToolUse", "gh pr merge 7") == {}


def test_d2_the_then_form_and_every_merge_on_a_line_are_gated(repo, tmp_path, monkeypatch):
    gh_says(tmp_path, monkeypatch, repo)
    out = call(repo, "PreToolUse", "if ! gh pr checks 7 | grep -q fail; then gh pr merge 7 --merge; fi")
    assert out["permissionDecision"] == "deny"
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    assert call(repo, "PreToolUse", "gh pr merge 7 && gh pr merge 7") == {}
    assert kit_state.load("s1")["gate"]["passes"] == 2


def test_d3_placeholder_and_quoted_skip_phrases_are_not_skips(repo, tmp_path, monkeypatch):
    pr76 = "- Passes: `momus: skip <reason>` in the PR body.\nmomus: skip <reason>\nmomus: skip ..."
    gh_says(tmp_path, monkeypatch, repo, body=pr76)
    assert call(repo, "PreToolUse", "gh pr merge 7")["permissionDecision"] == "deny"
    out = call(repo, "PreToolUse", 'echo "set DAEDALUS_MOMUS_SKIP=x"; gh pr merge 7')
    assert out["permissionDecision"] == "deny"
    assert call(repo, "PreToolUse", 'DAEDALUS_MOMUS_SKIP="<reason>" gh pr merge 7')["permissionDecision"] == "deny"
    gh_says(tmp_path, monkeypatch, repo, body="Fixes a typo.\n\nmomus: skip one-word typo in a comment")
    assert call(repo, "PreToolUse", "gh pr merge 7") == {}
    assert kit_state.load("s1")["skips"][-1]["reason"] == "one-word typo in a comment"


def test_a_rebased_trial_says_it_is_not_in_the_heads_history(repo, tmp_path, monkeypatch):
    old = git(repo, "rev-parse", "HEAD")
    trial(repo, "feat/x", old)
    git(repo, "commit", "-q", "--amend", "-m", "change (rebased)")
    gh_says(tmp_path, monkeypatch, repo)
    out = call(repo, "PreToolUse", "gh pr merge 7")
    assert f"a trial at {old[:7]} exists but isn't in the head's history" in out["permissionDecisionReason"]


def test_a_merge_of_the_current_branch_asks_gh_about_it(repo, tmp_path, monkeypatch):
    gh_says(tmp_path, monkeypatch, repo, number=31)
    out = call(repo, "PreToolUse", "gh pr merge --squash")
    assert out["permissionDecision"] == "deny" and "PR #31" in out["permissionDecisionReason"]


def test_gh_with_no_head_and_no_state_allows_with_a_notice(repo, tmp_path, monkeypatch):
    fake_gh(tmp_path, monkeypatch, {})
    out = call(repo, "PreToolUse", "gh pr merge 62")
    assert "permissionDecision" not in out and "didn't run" in out["additionalContext"]


def test_create_nudges_in_nudge_mode_and_not_when_off(repo):
    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": "nudge"}}))
    assert "no Momus trial covers" in create(repo, 40)["additionalContext"]
    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": "off"}}))
    assert create(repo, 41) == {}


def test_create_says_nothing_once_a_trial_covers_the_head(repo):
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    assert create(repo, 42) == {}


@pytest.mark.parametrize("value, mode", [("Gate", "gate"), ("deny", "gate"), ("NUDGE", "nudge"), ("off", "off"),
                                         (True, "gate")])
def test_hand_edited_modes_are_normalized(repo, value, mode):
    from daedalus_hookkit.core import Ctx
    from daedalus_hookkit.settings import Settings

    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": value}}))
    assert momus_gate.mode(Ctx("PreToolUse", {}, repo, Settings(repo), 0)) == mode


def test_false_turns_the_gate_off(repo):
    create(repo)
    (repo / ".daedalus/config.json").write_text(json.dumps({"hooks": {"momus_gate": False}}))
    assert call(repo, "PreToolUse", "gh pr merge 7") == {}


def test_trials_are_read_from_a_submodule_project(repo, tmp_path, monkeypatch):
    """The project's .git is a gitlink file into another git dir, as in a submodule."""
    gitdir = tmp_path / "modules" / "proj"
    gitdir.parent.mkdir()
    (repo / ".git").rename(gitdir)
    (repo / ".git").write_text(f"gitdir: {gitdir}\n")
    git(repo, "config", "core.worktree", str(repo))
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    gh_says(tmp_path, monkeypatch, repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    p = {"session_id": "s1", "cwd": str(tmp_path), "tool_name": "Bash", "tool_input": {"command": "gh pr merge 7"}}
    assert dispatch("PreToolUse", p, GATE) == ""


# ---------- Momus's final pass (trial 2026-10-15-momus-gate.md, 2nd section) ----------


def test_g1_pflag_repo_forms_reach_gh(repo, tmp_path, monkeypatch):
    log = tmp_path / "gh-args.txt"
    bindir = tmp_path / "bin"
    gh = bindir / "gh"
    gh.write_text(f"#!{sys.executable}\nimport sys, json\nopen({str(log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
                  "print(json.dumps({'number': 12, 'headRefName': 'feat/x', 'headRefOid': 'f' * 40, "
                  "'files': [{'path': 'a.py'}], 'body': ''}))\n")
    for command in ("gh pr merge -Ro/r 12", "gh pr merge -R=o/r 12", "gh pr merge --repo o/r 12",
                    "gh pr merge https://github.com/o/r/pull/12"):
        call(repo, "PreToolUse", command)
    assert [line.split(" --json")[0] for line in log.read_text().splitlines()] == ["pr view 12 -R o/r"] * 4


def test_g2_with_gh_down_the_branch_head_is_read_locally(repo):
    create(repo)
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    commit(repo, "b.py", "z = 1\n")
    out = call(repo, "PreToolUse", "gh pr merge 7")
    assert out["permissionDecision"] == "deny" and "session state" in out["permissionDecisionReason"]


def test_g3_a_placeholder_with_trailing_text_is_no_reason(repo, tmp_path, monkeypatch):
    gh_says(tmp_path, monkeypatch, repo, body="- momus: skip <reason> in the PR body")
    assert call(repo, "PreToolUse", "gh pr merge 7")["permissionDecision"] == "deny"


def test_passes_are_counted(repo, tmp_path, monkeypatch):
    gh_says(tmp_path, monkeypatch, repo, files=["docs/a.md"])
    call(repo, "PreToolUse", "gh pr merge 7")
    trial(repo, "feat/x", git(repo, "rev-parse", "HEAD"))
    gh_says(tmp_path, monkeypatch, repo)
    call(repo, "PreToolUse", "gh pr merge 7")
    assert kit_state.load("s1")["gate"] == {"blocks": 0, "passes": 2, "skips": 0, "allowed_by_error": 0}


def test_a_body_skip_at_create_suppresses_the_nudge(repo):
    assert create(repo, 50, body="momus: skip reverting a typo") == {}
    assert kit_state.load("s1")["prs"]["50"]["skip"] == "reverting a typo"


def test_the_nearest_trial_sets_the_count(repo, tmp_path, monkeypatch):
    first = git(repo, "rev-parse", "HEAD")
    commit(repo, "b.py", "1\n")
    second = commit(repo, "c.py", "2\n")
    commit(repo, "d.py", "3\n")
    trial(repo, "feat/x", first, name="a.md")
    trial(repo, "feat/x", second, name="b.md")
    gh_says(tmp_path, monkeypatch, repo)
    assert "1 commit since the trial" in call(repo, "PreToolUse", "gh pr merge 7")["permissionDecisionReason"]


def test_a_detached_head_records_nothing(repo):
    git(repo, "checkout", "-q", "--detach")
    assert create(repo, 51) == {}
    assert "51" not in kit_state.load("s1").get("prs", {})
