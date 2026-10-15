"""Momus's open leaks from the reflection-tooling review (trial 2026-10-15-reflection-tooling-fixes.md)."""

from datetime import date

import pytest

from daedalus.reflection import models as m
from daedalus.reflection.check import REPORT_SCHEMA, bare_numbers, check_report
from daedalus.reflection.digest import digest_project, load_digests

from reflection_helpers import REAL_SESSION, install_fixtures, make_project

pytestmark = pytest.mark.reflection


def test_ratios_ranges_units_and_more_words_are_numbers():
    found = [w for _, _, w in bare_numbers("4/109 calls, 10-20 retries, 3x slower, 12KB, twice, thirteen, sixty")]
    assert found[:4] == ["4", "109", "10", "20"] and "3x" in found and "12KB" in found
    assert {"twice", "thirteen", "sixty"} <= set(found)
    assert bare_numbers("see src/a/b2.py and edict 0010 on 2026-10-14") == []


def test_symbols_matter_to_the_duplicate_guard_and_revise_is_guarded(tmp_path):
    root = tmp_path / "models"

    def add(obs):
        return m.apply_change("self", {"op": "add", "entry": {"observation": obs, "kind": "behavior", "confidence": 0.5,
                                                             "label": "shown", "evidence": [{"session": "s", "event": "e"}]}},
                              by="proposal", root=root, today=date(2026, 10, 1))
    add("I use x != y checks")
    add("I use x == y checks")  # not the same observation
    with pytest.raises(m.ModelError):
        add("I use x == y checks.")  # trailing punctuation doesn't make it different
    with pytest.raises(m.ModelError, match="already says this"):
        m.apply_change("self", {"op": "revise", "id": "s001", "changes": {"observation": "I use x == y checks"}},
                       by="proposal", root=root, today=date(2026, 10, 1))


def test_a_daily_cannot_cite_a_multi_day_sessions_totals(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: cfg)
    project = make_project(tmp_path / "proj")
    install_fixtures(project)
    digest_project(project)
    d = {x["session_id"]: x for x in load_digests(project)}[REAL_SESSION]
    days = sorted(set(d["event_days"].values()))
    import json

    path = project / ".daedalus/reflection/sessions" / f"{REAL_SESSION}.json"
    data = json.loads(path.read_text())
    first = next(iter(data["event_days"]))
    data["event_days"][first] = "2020-01-01"  # make the session span another day
    path.write_text(json.dumps(data))
    rep = {"schema": REPORT_SCHEMA, "level": "daily", "period": days[-1], "proposals": [], "findings": [
        {"id": "F1", "type": "other", "text": f"Calls [s:{REAL_SESSION} d:tool_calls]"},
        {"id": "F2", "type": "other", "text": f"Models [s:{REAL_SESSION} d:models]"}]}
    errs = check_report(project, rep, tmp_path / "models").errors
    assert any("F1" in e and "whole-session total" in e for e in errs)
    assert not any("F2" in e and "whole-session total" in e for e in errs)
