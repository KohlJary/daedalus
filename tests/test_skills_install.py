"""Plugin skills ship with the package and hydrate installs them into projects (edict 0004)."""

import re

import pytest
import yaml
from click.testing import CliRunner

from daedalus import config as config_module
from daedalus.cli.main import main
from daedalus.config import DaedalusConfig
from daedalus.plugin import PLUGIN_ROOT, get_skills_dir, list_skills
from daedalus.templates import injector

# Names that must never appear in a shipped, generic skill
DENY = ["UBC", "ADO", "Azure DevOps", "Jira", "crystal-pas", "Crystal PAS", "CrystalPAS", "Kohl"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(config_module, "get_config_file", lambda: tmp_path_factory.mktemp("cfg") / "config.json")
    monkeypatch.setattr(injector, "load_daedalus_config", lambda config_path=None: {})
    monkeypatch.setattr(injector, "load_config", lambda: DaedalusConfig())
    monkeypatch.setattr(injector, "get_daedalus_email", lambda config: "daedalus@example.com")


def manifest_skills():
    data = yaml.safe_load((PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    return [s["name"] for s in data["skills"]]


def test_manifest_lists_every_shipped_skill_and_nothing_else():
    on_disk = sorted(p.parent.name for p in get_skills_dir().glob("*/SKILL.md"))
    assert sorted(manifest_skills()) == on_disk
    assert {"ariadne", "mind-palace", "exhale", "inhale"} <= set(on_disk)
    assert list_skills() == manifest_skills()


def test_skill_frontmatter_names_match_their_folders():
    for name in manifest_skills():
        text = (get_skills_dir() / name / "SKILL.md").read_text(encoding="utf-8")
        front = yaml.safe_load(text.split("---")[1])
        assert front["name"] == name and front["description"].strip()


@pytest.mark.parametrize("name", ["exhale", "inhale"])
def test_rituals_are_generic(name):
    text = (get_skills_dir() / name / "SKILL.md").read_text(encoding="utf-8")
    found = [term for term in DENY if re.search(rf"\b{re.escape(term)}\b", text)]
    assert found == []
    assert text.isascii()


def run(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["hydrate", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_hydrate_installs_every_skill(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, "--no-agents", "--no-template")

    for name in manifest_skills():
        installed = tmp_path / ".claude" / "skills" / name / "SKILL.md"
        assert installed.read_bytes() == (get_skills_dir() / name / "SKILL.md").read_bytes()


def test_hydrate_overwrites_an_installed_skill(tmp_path, monkeypatch):
    target = tmp_path / ".claude" / "skills" / "exhale" / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")

    run(tmp_path, monkeypatch, "--no-agents", "--no-template")

    assert target.read_bytes() == (get_skills_dir() / "exhale" / "SKILL.md").read_bytes()


def test_no_skills_writes_none(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, "--no-agents", "--no-template", "--no-skills")
    assert not (tmp_path / ".claude" / "skills").exists()


def test_dry_run_lists_skills_and_writes_none(tmp_path, monkeypatch):
    output = run(tmp_path, monkeypatch, "--no-agents", "--no-template", "--dry-run")

    assert "Skills that would be written:" in output
    assert "exhale" in output and "inhale" in output
    assert not (tmp_path / ".claude").exists()


def test_dry_run_after_install_reports_nothing_to_write(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, "--no-agents", "--no-template")
    output = run(tmp_path, monkeypatch, "--no-agents", "--no-template", "--dry-run")
    assert "Skills that would be written: none" in output


def test_init_installs_skills(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("daedalus.cli.commands._ensure_global_identity", lambda: None)
    result = CliRunner().invoke(main, ["init"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "inhale" / "SKILL.md").exists()


def test_reconstruct_skill_and_mnemosyne_agent_ship(tmp_path, monkeypatch):
    from daedalus.plugin import get_agents_dir
    data = yaml.safe_load((PLUGIN_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert "mnemosyne" in [a["name"] for a in data["agents"]]
    assert (get_agents_dir() / "mnemosyne.md").exists()
    assert "reconstruct" in manifest_skills()
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(main, ["hydrate", "--no-template"])
    assert (tmp_path / ".claude/skills/reconstruct/SKILL.md").exists()
    assert (tmp_path / ".claude/agents/mnemosyne.md").exists()


def test_hit_em_up_ships_its_personas_and_frames_and_they_are_generic(tmp_path, monkeypatch):
    skill = get_skills_dir() / "hit-em-up"
    personas = sorted(p.stem for p in (skill / "personas").glob("*.md"))
    frames = sorted(p.stem for p in (skill / "frames").glob("*.md"))
    assert {"neutral", "battle"} <= set(frames)
    assert {"workplace", "full-bore"} <= set(personas)
    shipped = [("personas", n) for n in personas] + [("frames", n) for n in frames]
    for folder, name in shipped:
        text = (skill / folder / f"{name}.md").read_text(encoding="utf-8")
        assert [t for t in DENY if re.search(rf"\b{re.escape(t)}\b", text)] == []
        assert text.isascii()
    full = (skill / "personas" / "full-bore.md").read_text(encoding="utf-8")
    assert "No amendment may aim his fire at a person." in full

    run(tmp_path, monkeypatch, "--no-agents", "--no-template")
    for folder, name in shipped:
        installed = tmp_path / ".claude" / "skills" / "hit-em-up" / folder / f"{name}.md"
        assert installed.read_bytes() == (skill / folder / f"{name}.md").read_bytes()


def test_hit_em_up_ships_clash_and_its_cast_generic(tmp_path, monkeypatch):
    skill = get_skills_dir() / "hit-em-up"
    shipped = ["clash/protocol.md", "clash/crowd.md", "personas/edge-case.md"]
    for rel in shipped:
        text = (skill / rel).read_text(encoding="utf-8")
        assert [t for t in DENY if re.search(rf"\b{re.escape(t)}\b", text)] == []
        assert text.isascii()
    assert "clash/protocol.md" in (skill / "SKILL.md").read_text(encoding="utf-8")
    edge = (skill / "personas" / "edge-case.md").read_text(encoding="utf-8")
    assert "No amendment may aim her fire at a person." in edge
    crowd = (skill / "clash" / "crowd.md").read_text(encoding="utf-8")
    assert "No amendment may let a bar into the ledger on a receipt the crowd did not check." in crowd
    protocol = (skill / "clash" / "protocol.md").read_text(encoding="utf-8")
    assert "Answer the verse first." in protocol and "DODGED" in crowd
    assert '"maxBars"' in protocol and "Verses strictly alternate" in protocol
    assert "Never let an MC write to the ledger" in protocol

    run(tmp_path, monkeypatch, "--no-agents", "--no-template")
    for rel in shipped:
        installed = tmp_path / ".claude" / "skills" / "hit-em-up" / rel
        assert installed.read_bytes() == (skill / rel).read_bytes()
