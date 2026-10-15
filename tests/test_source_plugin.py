"""A source from a separate package registers through the entry point and syncs with no change to
Daedalus (edict 0011): the proof that a Jira source could be written outside Daedalus."""

import sys
import textwrap

import pytest

from daedalus import sources

from sources_helpers import offline, pending, project, run  # noqa: F401

PLUGIN = '''
from daedalus.sources import RemoteItem, Source


class FakeJira(Source):
    title = "Fake Jira"
    supports_write_back = True
    config_schema = [{"key": "board", "type": "str", "default": None, "description": "The Jira board."}]
    default_mapping = {
        "owned": ["title", "status"],
        "kinds": {"Epic": "phase", "Story": "item", "Sub-task": "task"},
        "states": {"To Do": "backlog", "In Progress": "in_progress", "Done": "done"},
    }
    closed = []

    def is_configured(self):
        return bool(self.settings.get("board"))

    def fetch(self, known_ids, since):
        return [
            RemoteItem("J-1", "Epic", "Checkout revamp", "In Progress"),
            RemoteItem("J-2", "Story", "Pay with a saved card", "To Do", parent="J-1"),
            RemoteItem("J-3", "Sub-task", "Card vault API", "To Do", parent="J-2"),
        ]

    def write_back(self, external_id, comment):
        FakeJira.closed.append((external_id, comment))
'''


@pytest.fixture
def plugin(tmp_path, monkeypatch, offline):
    site = tmp_path / "site"
    (site / "fakejira").mkdir(parents=True)
    (site / "fakejira" / "__init__.py").write_text(textwrap.dedent(PLUGIN))
    dist = site / "fakejira-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: fakejira\nVersion: 0.1\n")
    (dist / "entry_points.txt").write_text("[daedalus.sources]\njira = fakejira:FakeJira\n")
    monkeypatch.syspath_prepend(str(site))
    sources.reset()
    yield
    sys.modules.pop("fakejira", None)
    sources.reset()


def test_third_party_source_registers_configures_and_syncs(plugin, project):
    assert "jira" in sources.installed()
    assert run("config", "--project", "sources.jira.board", "CHK").exit_code == 0
    assert run("config", "--project", "sources.jira.on_conflict", "source").exit_code == 0
    assert run("config", "--project", "sources.jira.nope", "x").exit_code == 1
    listed = run("source", "list").output
    assert "Fake Jira" in listed and "jira" in listed.split("Sources here")[1]

    run("source", "sync", "jira")
    kinds = sorted(p["kind"] for p in pending(project))
    assert kinds == ["new-phase", "roadmap-new"]
    assert run("gameplan", "pending", "apply", "all").exit_code == 0
    assert "proposed 0" in run("source", "sync", "jira").output
    run("gameplan", "phase", "activate", "jira-j-1")
    run("gameplan", "task", "status", "jira-j-3", "done", "-r", "Vault live")
    run("gameplan", "pending", "apply", "all")
    import fakejira

    assert fakejira.FakeJira.closed == [("J-3", None)]
