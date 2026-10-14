"""What reflection is due (edict 0010), with fixture digests and a fixed clock."""

from datetime import date, timezone

import pytest

from daedalus.reflection.due import compute_due, load_state, mark_done

from reflection_helpers import make_project

pytestmark = pytest.mark.reflection
UTC = timezone.utc


def digest(sid: str, day: str, calls: int) -> dict:
    return {"session_id": sid, "start": f"{day}T10:00:00Z", "end": f"{day}T11:00:00Z", "tool_calls": calls}


def due(digests, today, state=None, threshold=20):
    return compute_due(digests, state or {"covered_through": {}}, today, threshold, tz=UTC)


def test_no_digests_means_nothing_is_due():
    assert due([], date(2026, 10, 20)) == []


def test_today_is_never_due_yet():
    assert due([digest("a", "2026-10-20", 50)], date(2026, 10, 20)) == []


def test_a_busy_completed_day_is_due_as_a_daily():
    # Wednesday, in a week not yet over
    result = due([digest("a", "2026-10-14", 50)], date(2026, 10, 15))
    assert [(d.level, d.period) for d in result] == [("daily", "2026-10-14")]
    assert result[0].sessions == ["a"] and result[0].tool_calls == 50


def test_a_small_day_rolls_into_the_next_weekly():
    small = [digest("a", "2026-10-13", 5)]
    assert due(small, date(2026, 10, 15)) == []  # not due as a daily
    weekly = due(small, date(2026, 10, 19))      # Monday after the week of the 12th
    assert [(d.level, d.period) for d in weekly] == [("weekly", "2026-W42")]
    assert weekly[0].sessions == ["a"]


def test_a_completed_week_absorbs_its_days():
    ds = [digest("a", "2026-10-12", 30), digest("b", "2026-10-14", 40), digest("c", "2026-10-15", 3)]
    result = due(ds, date(2026, 10, 19))
    assert [(d.level, d.period) for d in result] == [("weekly", "2026-W42")]
    assert result[0].absorbs == ["2026-10-12", "2026-10-14"]  # the small day was never due alone
    assert result[0].sessions == ["a", "b", "c"]


def test_a_month_away_runs_the_monthly_once():
    ds = [digest(f"s{i}", f"2026-09-{d:02d}", 30) for i, d in enumerate((2, 9, 16, 23, 29))]
    result = due(ds, date(2026, 10, 25))
    assert [(d.level, d.period) for d in result] == [("monthly", "2026-09")]
    assert "2026-09-02" in result[0].absorbs and "2026-W36" in result[0].absorbs


def test_mark_done_covers_lower_levels(tmp_path):
    project = make_project(tmp_path / "p")
    ds = [digest("a", "2026-10-12", 30), digest("b", "2026-10-13", 30)]
    mark_done(project, "weekly", date(2026, 10, 18), "2026-W42")
    state = load_state(project)
    assert state["covered_through"]["daily"] == "2026-10-18"
    assert due(ds, date(2026, 10, 20), state) == []
    # A new session after the covered week is due again, on its own terms
    ds.append(digest("c", "2026-10-19", 30))
    assert [(d.level, d.period) for d in due(ds, date(2026, 10, 20), state)] == [("daily", "2026-10-19")]


def test_a_week_straddling_a_due_month_counts_only_its_own_days():
    # Week of 2026-09-28 to 2026-10-04 straddles September and October
    ds = [digest("sep", "2026-09-29", 30), digest("oct", "2026-10-02", 30)]
    result = due(ds, date(2026, 10, 6))
    levels = {(d.level, d.period): d for d in result}
    assert ("monthly", "2026-09") in levels
    week = levels[("weekly", "2026-W40")]
    assert week.sessions == ["oct"]
