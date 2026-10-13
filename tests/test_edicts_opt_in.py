"""Edicts are opt-in (edict 0005); `daedalus edict list/show` (edict 0001)."""

import json

import pytest
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.config import DaedalusConfig, edicts_setting
from daedalus.templates import injector


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path_factory):
    cfg = tmp_path_factory.mktemp("cfg")
    monkeypatch.setattr(config_module, "get_config_file", lambda: cfg / "config.json")
    monkeypatch.setattr("daedalus.cli.commands.get_config_dir", lambda: cfg)
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")
    return cfg


def run(path, monkeypatch, *args):
    monkeypatch.chdir(path)
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def claude_md(path):
    return (path / "CLAUDE.md").read_text(encoding="utf-8")


def test_off_by_default(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, "init")
    assert not (tmp_path / "docs" / "edicts").exists()
    text = claude_md(tmp_path)
    assert "## Edicts" not in text and "edict" not in text.lower().replace("edict 0", "")
    assert "## Status handoff" in text            # the handoff stays without edicts
    assert edicts_setting(tmp_path) == (False, "default")


def test_init_edicts_enables_and_scaffolds(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, "init", "--edicts")
    assert "Edicts enabled" in out
    assert (tmp_path / "docs/edicts/README.md").read_text().startswith("# Edicts")
    assert (tmp_path / "docs/edicts/dissents").is_dir()
    assert "## Edicts" in claude_md(tmp_path)
    assert edicts_setting(tmp_path) == (True, "project")


def test_scaffolded_readme_is_generic():
    from daedalus.plugin import PLUGIN_ROOT
    text = (PLUGIN_ROOT / "templates" / "EDICTS_README.md").read_text()
    assert "Kohl" not in text and "the project owner" in text


def test_upgrade_keeps_existing_edicts_with_a_hint(tmp_path, monkeypatch):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0001-x.md").write_text("# Edict 0001: X\nStatus: accepted\n")
    out = run(tmp_path, monkeypatch, "hydrate", "--no-agents", "--no-skills", "--no-hooks")
    assert "## Edicts" in claude_md(tmp_path)
    assert "edicts.enabled is not set" in out
    assert edicts_setting(tmp_path) == (True, "detected")


def test_explicit_off_drops_the_section_even_with_edicts_on_disk(tmp_path, monkeypatch):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    run(tmp_path, monkeypatch, "config", "--project", "edicts.enabled", "false")
    out = run(tmp_path, monkeypatch, "hydrate", "--no-agents", "--no-skills", "--no-hooks")
    assert "## Edicts" not in claude_md(tmp_path)
    assert "edicts.enabled is not set" not in out


def test_global_setting_applies(tmp_path, monkeypatch, isolated):
    (isolated / "config.json").write_text(json.dumps({"edicts": {"enabled": True}}))
    assert edicts_setting(tmp_path) == (True, "global")


def test_doctor_reference_check_follows_the_setting(tmp_path, monkeypatch):
    from daedalus.doctor import run_checks
    gp.ensure_gameplan(tmp_path)
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0001-x.md").write_text("# Edict 0001: X\nStatus: accepted\n")
    assert "edict-not-in-gameplan" in [f.name for f in run_checks(tmp_path)[0]]
    run(tmp_path, monkeypatch, "config", "--project", "edicts.enabled", "false")
    assert "edict-not-in-gameplan" not in [f.name for f in run_checks(tmp_path)[0]]


def test_edict_list_and_show(tmp_path, monkeypatch):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0001-intent.md").write_text("# Edict 0001: Intent flows from edicts\nStatus: accepted\n\n## Intent\nX\n")
    (tmp_path / "docs/edicts/0002-cast.md").write_text("# Edict 0002: Model casting\nStatus: proposed\n")
    data = gp.empty_gameplan()
    gp.add_phase(data, "p1", "Edicts", edict="0001")
    gp.save_gameplan(tmp_path, data)

    out = run(tmp_path, monkeypatch, "edict", "list")
    assert "0001  accepted  Intent flows from edicts  (phase p1 [planned])" in out
    assert "0002  proposed  Model casting  (not in the gameplan)" in out

    shown = run(tmp_path, monkeypatch, "edict", "show", "1")
    assert "## Intent" in shown and shown.rstrip().endswith("Gameplan: phase p1 [planned]")

    monkeypatch.chdir(tmp_path)
    missing = CliRunner().invoke(main, ["edict", "show", "9"])
    assert missing.exit_code == 1 and "No edict 0009" in missing.output



def test_edict_cli_edge_cases(tmp_path, monkeypatch):
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0004-a.md").write_text("# Edict 0004: A\nStatus: accepted\n")
    (tmp_path / "docs/edicts/0004-b.md").write_text("# Edict 0004: B\nStatus: done\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    out = runner.invoke(main, ["edict", "list"])
    assert "warning: edict 0004 is used by 2 files" in out.output
    bad = runner.invoke(main, ["edict", "show", "abc"])
    assert bad.exit_code == 1 and "'abc' is not an edict number" in bad.output


def test_installed_skills_only_mention_edicts_conditionally():
    from daedalus.plugin import get_agents_dir, get_skills_dir
    for path in [get_skills_dir() / "inhale/SKILL.md", get_skills_dir() / "exhale/SKILL.md",
                 get_agents_dir() / "memory.md"]:
        for line in path.read_text().splitlines():
            if "edict" in line.lower():
                assert "use edicts" in line or "using edicts" in line, (path.name, line)
