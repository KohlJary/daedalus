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


def test_old_tombstones_still_match_and_forgetting_stays_loose(tmp_path):
    """Momus: tombstones hash a loose form; changing it would let a forgotten observation back in."""
    import hashlib
    import re as _re

    root = tmp_path / "models"
    m.apply_change("user", {"op": "add", "entry": {"observation": "Seed", "confidence": 0.5, "label": "shown",
                                                   "evidence": [{"session": "s", "event": "e"}]}},
                   by="proposal", root=root, today=date(2026, 10, 1))
    data = m.load("user", root)
    old = hashlib.sha256(_re.sub(r"\W+", " ", "prefers short, direct answers.").strip().encode()).hexdigest()
    data["tombstones"].append({"id": "u099", "date": "2026-01-01", "reason": "forgotten by user", "observation_hash": old})
    assert m.is_tombstoned(data, observation="Prefers short, direct answers.")
    assert m.is_tombstoned(data, observation="prefers short direct answers")


def test_figures_are_period_checked_too(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: cfg)
    project = make_project(tmp_path / "proj")
    install_fixtures(project)
    digest_project(project)
    import json

    path = project / ".daedalus/reflection/sessions" / f"{REAL_SESSION}.json"
    data = json.loads(path.read_text())
    days = sorted(set(data["event_days"].values()))
    data["event_days"][next(iter(data["event_days"]))] = "2020-01-01"
    path.write_text(json.dumps(data))
    ev = next(u for u, d in data["event_days"].items() if d == days[-1])
    rep = {"schema": REPORT_SCHEMA, "level": "daily", "period": days[-1], "proposals": [], "findings": [
        {"id": "F1", "type": "other", "text": f"{data['tool_calls']} calls [s:{REAL_SESSION} e:{ev}]",
         "figures": [{"value": data["tool_calls"], "cite": f"[s:{REAL_SESSION} d:tool_calls]"}]}]}
    errs = check_report(project, rep, tmp_path / "models").errors
    assert any("figure cites tool_calls, a whole-session total" in e for e in errs)


def test_version_ranges_are_not_numbers():
    assert bare_numbers("Python 3.10-3.12 is supported") == []
