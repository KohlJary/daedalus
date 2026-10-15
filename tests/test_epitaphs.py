"""Why things died (dream pick 14): dropped intake keeps an epitaph; repeats become a doctor hint."""

from click.testing import CliRunner

from daedalus import epitaphs
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.doctor import run_checks


def _new_item(n, title, source="github"):
    return {"id": f"P{n}", "kind": "roadmap-new", "item": {"id": f"{source}-{n}", "title": title},
            "origin": {"source": source, "external_id": str(n), "url": ""}}


def test_dropping_intake_leaves_an_epitaph_with_the_reason(tmp_path, monkeypatch):
    gp.ensure_gameplan(tmp_path)
    gp.save_pending(tmp_path, [_new_item(1, "Dark mode"), {"id": "P2", "task": "T-1", "status": "done"}])
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(main, ["gameplan", "pending", "drop", "P1", "--why", "not this quarter"])
    CliRunner().invoke(main, ["gameplan", "pending", "drop", "P2"])
    rows = epitaphs.load(tmp_path)
    assert [(r["key"], r["title"], r["why"]) for r in rows] == [("github:1", "Dark mode", "not this quarter")]
    out = CliRunner().invoke(main, ["roadmap", "epitaphs"]).output
    assert "Dark mode (not this quarter)" in out


def test_three_drops_of_the_same_request_become_a_hint(tmp_path, monkeypatch):
    gp.ensure_gameplan(tmp_path)
    for n, title in enumerate(("Dark mode!", "dark mode", "A dark mode"), 1):
        gp.save_pending(tmp_path, [_new_item(n, title, "github" if n < 3 else "ado")])
        gp.drop_pending(tmp_path, f"P{n}", why="later" if n == 3 else None)
    [r] = epitaphs.recurring(tmp_path)
    assert r["count"] == 3 and r["sources"] == ["ado", "github"] and r["last_why"] == "later"
    _, hints = run_checks(tmp_path)
    assert any(h.startswith("intake-dropped-repeatedly") for h in hints)
    monkeypatch.chdir(tmp_path)
    assert "3x A dark mode" in CliRunner().invoke(main, ["roadmap", "epitaphs", "--recurring"]).output
