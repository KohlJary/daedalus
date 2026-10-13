"""Gameplan phases and tasks can name the edict they implement (edict 0007)."""

from click.testing import CliRunner

from daedalus.cli import gameplan as gp
from daedalus.cli.main import main


def run(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["gameplan", *args])
    assert result.exit_code == 0, result.output
    return result.output


def test_phase_and_task_carry_edict(tmp_path, monkeypatch):
    gp.ensure_gameplan(tmp_path)
    run(tmp_path, monkeypatch, "phase", "add", "p1", "Backbone", "--edict", "0007")
    run(tmp_path, monkeypatch, "phase", "activate", "p1")
    run(tmp_path, monkeypatch, "task", "add", "T1", "Doctor", "--edict", "0007")
    run(tmp_path, monkeypatch, "task", "add", "T2", "Untagged")

    data = gp.load_gameplan(tmp_path)
    assert data["phases"][0]["edict"] == "0007"
    assert data["activePhase"]["edict"] == "0007"
    tasks = {t["id"]: t for t in data["activePhase"]["tasks"]}
    assert tasks["T1"]["edict"] == "0007"
    assert "edict" not in tasks["T2"]

    shown = run(tmp_path, monkeypatch, "show")
    assert "Backbone (0 items) [edict 0007]" in shown
    assert "T1: Doctor [edict 0007]" in shown
    assert "T2: Untagged\n" in shown


def test_edict_is_optional(tmp_path):
    data = gp.empty_gameplan()
    phase = gp.add_phase(data, "p1", "Plain")
    assert "edict" not in phase
