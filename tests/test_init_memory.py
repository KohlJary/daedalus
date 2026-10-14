"""init creates no empty optional memory files and makes the gameplan committable (edict 0007)."""

import os
import subprocess

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli.main import main
from daedalus.config import DaedalusConfig
from daedalus.templates import injector


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path_factory):
    cfg = tmp_path_factory.mktemp("cfg")
    monkeypatch.setattr(config_module, "get_config_file", lambda: cfg / "config.json")
    monkeypatch.setattr("daedalus.cli.commands.get_config_dir", lambda: cfg)
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")


def ignored(repo, rel):
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=repo).returncode == 0


def init(repo, monkeypatch):
    monkeypatch.chdir(repo)
    result = CliRunner().invoke(main, ["init"])
    assert result.exit_code == 0, result.output
    return result.output


def test_no_empty_optional_files(tmp_path, monkeypatch):
    init(tmp_path, monkeypatch)
    memory = tmp_path / ".daedalus"
    for name in ("observations.json", "lessons.md", "warnings.md"):
        assert not (memory / name).exists()
    assert (memory / "roadmap" / "gameplan.json").exists()


def test_ignored_gameplan_gets_unignored_and_rest_stays_local(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("# Daedalus project memory (local, not shared)\n.daedalus/\n")
    out = init(tmp_path, monkeypatch)
    assert "Un-ignored the gameplan" in out
    assert not ignored(tmp_path, ".daedalus/roadmap/gameplan.json")
    assert not ignored(tmp_path, ".daedalus/gameplans/kohl.json")
    assert ignored(tmp_path, ".daedalus/gameplans/kohl.pending.json")
    assert ignored(tmp_path, ".daedalus/session-summaries.md")
    assert ignored(tmp_path, ".daedalus/roadmap/index.json")

    before = (tmp_path / ".gitignore").read_text()
    init(tmp_path, monkeypatch)
    assert (tmp_path / ".gitignore").read_text() == before


def test_existing_gitignore_gets_the_block_appended(tmp_path, monkeypatch):
    """A project with its own .gitignore but nothing Daedalus-related: plans committed, the rest local."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    init(tmp_path, monkeypatch)
    text = (tmp_path / ".gitignore").read_text()
    assert text.startswith("*.pyc\n")
    assert ignored(tmp_path, ".daedalus/session-summaries.md")
    assert not ignored(tmp_path, ".daedalus/roadmap/gameplan.json")
    assert ignored(tmp_path, ".daedalus/config.json") and ignored(tmp_path, ".daedalus/board/state.json")


def test_fresh_repo_without_gitignore_keeps_memory_local(tmp_path, monkeypatch):
    """Found in the two-person trial: a fresh repo committed session notes and decisions."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    init(tmp_path, monkeypatch)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    tracked = subprocess.run(["git", "ls-files", ".daedalus"], cwd=tmp_path, capture_output=True,
                             text=True).stdout.split()
    assert tracked == [".daedalus/roadmap/gameplan.json"]
    assert not ignored(tmp_path, ".daedalus/gameplans/alice.json")


def test_repo_that_already_commits_memory_keeps_doing_so(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".daedalus").mkdir()
    (tmp_path / ".daedalus/decisions.md").write_text("# Decisions\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    init(tmp_path, monkeypatch)
    assert not ignored(tmp_path, ".daedalus/session-summaries.md")
    assert ignored(tmp_path, ".daedalus/config.json") and ignored(tmp_path, ".daedalus/board/state.json")
