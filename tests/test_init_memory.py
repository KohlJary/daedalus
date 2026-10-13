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
    assert "Un-ignored .daedalus/roadmap/gameplan.json" in out
    assert not ignored(tmp_path, ".daedalus/roadmap/gameplan.json")
    assert ignored(tmp_path, ".daedalus/session-summaries.md")
    assert ignored(tmp_path, ".daedalus/roadmap/index.json")

    before = (tmp_path / ".gitignore").read_text()
    init(tmp_path, monkeypatch)
    assert (tmp_path / ".gitignore").read_text() == before


def test_unignored_project_is_left_alone(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("*.pyc\n")
    init(tmp_path, monkeypatch)
    assert (tmp_path / ".gitignore").read_text() == "*.pyc\n"
