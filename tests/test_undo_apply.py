"""Undo an applied proposal (dream pick 25)."""

from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from daedalus import undo
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main


def setup(tmp_path):
    gp.ensure_gameplan(tmp_path)
    data = gp.load_gameplan(tmp_path)
    gp.add_phase(data, "p1", "One")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Do it")
    gp.save_gameplan(tmp_path, data)
    gp.save_pending(tmp_path, [{"id": "P1", "task": "T-1", "status": "done", "resolution": "did it"}])
    return tmp_path


def run(*a):
    return CliRunner().invoke(main, list(a))


def test_apply_then_undo_restores_the_plan_and_the_proposal(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    before = (tmp_path / ".daedalus/roadmap/gameplan.json").read_text()
    assert run("gameplan", "pending", "apply", "P1").exit_code == 0
    assert gp.find_task(gp.load_gameplan(tmp_path), "T-1")["status"] == "done"
    out = run("gameplan", "pending", "undo")
    assert out.exit_code == 0, out.output
    assert (tmp_path / ".daedalus/roadmap/gameplan.json").read_text() == before
    assert [p["id"] for p in gp.load_pending(tmp_path)] == ["P1"]
    assert run("gameplan", "pending", "undo").exit_code == 1  # once


def test_undo_refuses_after_a_later_change(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    run("gameplan", "pending", "apply", "P1")
    run("gameplan", "task", "add", "T-2", "Later work")
    out = run("gameplan", "pending", "undo")
    assert out.exit_code == 1 and "lose later work" in out.output
    assert gp.find_task(gp.load_gameplan(tmp_path), "T-2")


def test_undo_refuses_after_a_day_and_after_a_write_back(tmp_path, monkeypatch):
    setup(tmp_path)
    monkeypatch.chdir(tmp_path)
    run("gameplan", "pending", "apply", "P1")
    try:
        undo.undo(tmp_path, now=datetime.now(timezone.utc) + timedelta(days=2))
        assert False
    except ValueError as e:
        assert "over a day old" in str(e)
    path, entry = undo.latest(tmp_path)
    entry["outside_call"] = True
    import json

    path.write_text(json.dumps(entry))
    out = run("gameplan", "pending", "undo")
    assert out.exit_code == 1 and "outside tracker" in out.output
