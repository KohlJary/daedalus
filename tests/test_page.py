"""The state-of-the-project page (dream pick 33)."""

import json
from datetime import datetime, timezone

from click.testing import CliRunner

from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.page import build


def test_page_shows_plan_edicts_intake_and_note_and_nothing_private(tmp_path, monkeypatch):
    gp.ensure_gameplan(tmp_path)
    data = gp.load_gameplan(tmp_path)
    gp.add_phase(data, "p1", "Make <widgets>", edict="0042")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Write the parser")
    gp.save_gameplan(tmp_path, data)
    (tmp_path / "docs/edicts").mkdir(parents=True)
    (tmp_path / "docs/edicts/0042-widgets.md").write_text("# Edict 0042: Widgets\nStatus: accepted\n")
    (tmp_path / ".daedalus/roadmap/index.json").write_text(json.dumps({"items": [
        {"id": "a", "title": "x", "status": "backlog", "origin": {"source": "github", "external_id": "1"}},
        {"id": "b", "title": "y", "status": "done"}]}))
    (tmp_path / "docs/status.md").write_text("# Status\n\n## Tonight\n- Built things.\n")
    (tmp_path / ".daedalus/reflection").mkdir()
    (tmp_path / ".daedalus/reflection/secret.json").write_text('{"x": "PRIVATE-REFLECTION"}')
    page = build(tmp_path, now=datetime(2026, 10, 15, tzinfo=timezone.utc))
    assert "Make &lt;widgets&gt;" in page and "T-1" in page and "Widgets" in page and "(accepted)" in page
    assert "<td>github</td>" in page and "<td>local</td>" in page and "Built things." in page
    assert "PRIVATE-REFLECTION" not in page and "<script" not in page
    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(main, ["page"])
    assert out.exit_code == 0 and (tmp_path / ".daedalus/page/index.html").exists()


def test_an_empty_project_still_renders(tmp_path):
    assert "No phase is active" in build(tmp_path)
