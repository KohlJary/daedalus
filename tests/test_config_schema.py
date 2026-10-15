"""The config schema registry and the sources config group (edict 0011)."""

import json

from daedalus import config as cfg
from daedalus import config_schema

from sources_helpers import offline, project, run  # noqa: F401


def test_every_core_key_has_a_description():
    settings = config_schema.core_settings()
    assert len(settings) > 40
    missing = [k for k, s in settings.items() if not s.description]
    assert missing == []


def test_core_keys_match_the_dataclasses_and_choices():
    settings = config_schema.core_settings()
    assert settings["git.authorship"].choices == ("daedalus", "user")
    assert settings["machine.employer"].type == "tristate"
    assert settings["doctor.stale_commits"].type == "int" and settings["doctor.stale_commits"].project
    assert settings["tui.escape"].default == "ctrl+]"
    assert settings["tui.prs"].choices == ("local", "gh")


def test_source_on_conflict_is_validated_with_its_choices(offline):
    ok = run("config", "sources.github.on_conflict", "local")
    assert ok.exit_code == 0, ok.output
    assert cfg.load_config().sources == {"github": {"on_conflict": "local"}}
    bad = run("config", "sources.github.on_conflict", "sometimes")
    assert bad.exit_code == 1
    assert "Allowed: propose, source, local" in bad.output
    assert cfg.load_config().sources["github"]["on_conflict"] == "local"


def test_invalid_core_values_are_refused(offline):
    assert run("config", "hooks.capture", "maybe").exit_code == 1
    assert "takes true or false" in run("config", "hooks.capture", "maybe").output
    assert "Allowed: daedalus, user" in run("config", "git.authorship", "nobody").output
    assert run("config", "no.such", "x").exit_code == 1


def test_unknown_source_names_list_the_installed_plugins(offline):
    out = run("config", "sources.jira.url", "https://jira.example")
    assert out.exit_code == 1 and "installed: ado, dream, github" in out.output


def test_a_named_instance_takes_its_type(offline):
    assert run("config", "sources.work.type", "ado").exit_code == 0
    assert run("config", "sources.work.organization", "contoso").exit_code == 0
    assert run("config", "sources.work.type", "trello").exit_code == 1
    assert cfg.load_config().sources["work"] == {"type": "ado", "organization": "contoso"}


def test_project_layer_overrides_global(project):
    run("config", "sources.github.on_conflict", "source")
    run("config", "--project", "sources.github.on_conflict", "local")
    settings = cfg.get_source_settings(project, "github")
    assert settings["on_conflict"] == "local" and settings["write_back_comment"] is False
    saved = json.loads((project / ".daedalus" / "config.json").read_text())
    assert saved["sources"]["github"] == {"on_conflict": "local"}
    assert run("config", "--project", "sources.github.on_conflict").output.strip() == "local"
    bad = run("config", "--project", "sources.github.on_conflict", "bogus")
    assert bad.exit_code == 1 and "Allowed" in bad.output


def test_schema_listing(offline):
    out = run("config", "--schema", "sources.ado").output
    assert "sources.ado.organization" in out and "sources.ado.on_conflict" in out
    assert "one of: propose, source, local" in out
    assert "reflection.runner" in run("config", "--schema", "reflection").output


def test_unsetting_a_source_key(offline):
    run("config", "sources.github.token_env", "MY_TOKEN")
    run("config", "sources.github.token_env", "unset")
    assert cfg.load_config().sources["github"] == {}
