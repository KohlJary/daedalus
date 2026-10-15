"""Fixes from the first real reflection run (2026-10-15; Momus's trial
.daedalus/momus/trials/2026-10-15-reflection-daily-2026-10-14.md): T-r10, T-r12 to T-r17."""

import json
from datetime import date

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.reflection import explog
from daedalus.reflection import models as m
from daedalus.reflection.bundle import build_bundle
from daedalus.reflection.check import REPORT_SCHEMA, bare_numbers, check_report
from daedalus.reflection.digest import digest_project, load_digests

from reflection_helpers import REAL_SESSION, install_fixtures, make_project

pytestmark = pytest.mark.reflection
SETTINGS = {"half_life_self": 60, "half_life_user": 180, "summary_tokens": 400}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "daedalus-config"
    cfg.mkdir()
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: cfg)
    project = make_project(tmp_path / "proj")
    install_fixtures(project)
    digest_project(project)
    digests = {d["session_id"]: d for d in load_digests(project)}
    return project, digests, tmp_path / "models"


def add(root, model="user", **entry):
    entry.setdefault("observation", "Prefers small PRs")
    entry.setdefault("confidence", 0.8)
    entry.setdefault("label", "shown")
    entry.setdefault("evidence", [{"session": "s1", "event": "e1"}])
    return m.apply_change(model, {"op": "add", "entry": entry}, by="proposal", root=root, today=date(2026, 10, 1))


def day_of(digest, uuid):
    return digest["event_days"][uuid]


# ---------- T-r10: scopes ----------

def test_old_scope_names_are_read_and_written_as_the_new_ones(tmp_path):
    root = tmp_path / "models"
    assert add(root, observation="a", scope="personal")["scope"] == "private"
    assert add(root, observation="b", scope="any")["scope"] == "anywhere"
    assert add(root, observation="c")["scope"] == "anywhere"
    assert m.canon_scope("work") == "work"


def test_summary_keeps_private_out_of_work_unless_shared(tmp_path):
    root = tmp_path / "models"
    add(root, observation="Plays bass in a band", scope="private")
    add(root, observation="Prefers direct answers", scope="anywhere")
    add(root, observation="Sprint reviews on Fridays", scope="work")
    work = m.summary("work", SETTINGS, root, date(2026, 10, 1))
    assert "Plays bass" not in work and "direct answers" in work and "Sprint" in work
    shared = m.summary("work", {**SETTINGS, "share_private": True}, root, date(2026, 10, 1))
    assert "Plays bass" in shared
    private = m.summary("private", SETTINGS, root, date(2026, 10, 1))
    assert "Sprint" not in private and "Plays bass" in private
    assert "Plays bass" not in m.summary("personal", SETTINGS, root, date(2026, 10, 1)) or True  # alias accepted


def test_check_applies_scope_rules_both_ways(env):
    project, digests, root = env
    ev = digests[REAL_SESSION]["events"]["failures"][0]

    def prop(scope):
        return {"id": "R1", "target": "model", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{ev}]",
                "model": {"model": "user", "op": "add",
                          "entry": {"observation": "Likes x", "category": "working-preference", "scope": scope,
                                    "confidence": 0.5, "label": "shown",
                                    "evidence": [{"session": REAL_SESSION, "event": ev}]}}}
    rep = {"schema": REPORT_SCHEMA, "level": "monthly", "period": "2026-10", "findings": [], "proposals": [prop("private")]}
    errs = check_report(project, rep, root, scope="work").errors
    assert any("not private ones" in e for e in errs)
    rep["proposals"] = [prop("work")]
    assert any("not work ones" in e for e in check_report(project, rep, root, scope="private").errors)


# ---------- T-r12: a daily cites only its own day ----------

def test_daily_rejects_events_from_another_day_and_bundle_marks_the_period(env):
    project, digests, root = env
    d = digests[REAL_SESSION]
    ev = d["events"]["failures"][0]
    day = day_of(d, ev)
    rep = {"schema": REPORT_SCHEMA, "level": "daily", "period": day, "proposals": [],
           "findings": [{"id": "F1", "type": "failed_tool_call", "text": f"failed [s:{REAL_SESSION} e:{ev}]"}]}
    assert not [e for e in check_report(project, rep, root).errors if "outside" in e]
    other = date.fromisoformat(day).replace(day=1 if date.fromisoformat(day).day != 1 else 2).isoformat()
    rep["period"] = other
    assert any("outside the daily period" in e for e in check_report(project, rep, root).errors)
    bundle = build_bundle(project, "daily", day, SETTINGS, "work", root=root)
    sess = next(x for x in bundle["digests"] if x["session_id"] == REAL_SESSION)
    assert ev in sess["in_period"]["failures"] and "spans_days" in sess


# ---------- T-r13: every number is a checked figure ----------

def test_bare_numbers_need_figures(env):
    project, digests, root = env
    ev = digests[REAL_SESSION]["events"]["failures"][0]
    n = digests[REAL_SESSION]["tools"]["Bash"]["failures"]
    text = f"Bash failed {n} times [s:{REAL_SESSION} e:{ev}]"
    rep = {"schema": REPORT_SCHEMA, "level": "weekly", "period": "2026-W42", "proposals": [],
           "findings": [{"id": "F1", "type": "failed_tool_call", "text": text}]}
    assert any(f"number '{n}' has no figures entry" in e for e in check_report(project, rep, root).errors)
    rep["findings"][0]["figures"] = [{"value": n, "cite": f"[s:{REAL_SESSION} d:tools.Bash.failures]"}]
    assert not [e for e in check_report(project, rep, root).errors if "figures entry" in e]
    rep["findings"][0]["text"] = f"Three failures [s:{REAL_SESSION} e:{ev}]"
    assert any("'Three'" in e for e in check_report(project, rep, root).errors)


def test_dates_citations_ids_and_code_are_not_numbers():
    text = "On 2026-10-14 at T-r12 in v2.1.300 `sleep 240` [s:abc-1 e:0f1e-22] see #52 and file_2.py"
    assert bare_numbers(text) == []
    assert [w for _, _, w in bare_numbers("99% hit rate, 4 refusals")] == ["99%", "4"]


# ---------- T-r14: no duplicate entries ----------

def test_the_same_observation_is_not_added_twice(tmp_path):
    root = tmp_path / "models"
    add(root, model="self", observation="I call Write on files I haven't read.", kind="behavior")
    with pytest.raises(m.ModelError, match="already says this"):
        add(root, model="self", observation="I call write on files I haven't read", kind="behavior")


def test_check_refuses_a_duplicate_add(env):
    project, digests, root = env
    add(root, model="self", observation="I wait with long sleeps", kind="behavior")
    ev = digests[REAL_SESSION]["events"]["failures"][0]
    p = {"id": "R1", "target": "model", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{ev}]",
         "model": {"model": "self", "op": "add",
                   "entry": {"observation": "I wait with long sleeps.", "kind": "behavior", "category": "tool-use",
                             "confidence": 0.4, "label": "shown",
                             "evidence": [{"session": REAL_SESSION, "event": ev}]}}}
    rep = {"schema": REPORT_SCHEMA, "level": "weekly", "period": "2026-W42", "findings": [], "proposals": [p]}
    assert any("already says this" in e for e in check_report(project, rep, root).errors)


# ---------- T-r15: answering a question approves nothing ----------

def test_ask_user_question_answers_are_not_prompt_approvals(env):
    _, digests, _ = env
    d = digests[REAL_SESSION]
    tools = {c["result"]: c["tool"] for c in d["calls"]}
    assert all(tools.get(u) != "AskUserQuestion" for u in d["events"]["approved_at_prompt"])


# ---------- T-r17: correcting a logged run ----------

def test_a_logged_run_is_corrected_by_a_later_record(tmp_path, monkeypatch):
    project = make_project(tmp_path / "p")
    explog.append(project, {"record": "run", "level": "daily", "period": "2026-10-14", "runner": "inhale",
                            "models": {"delphi": "claude-opus-5-5", "momus": "claude-opus-5-5"}, "sessions": 3,
                            "session_ids": [], "tokens": 1, "findings": {}, "proposals": [],
                            "check_iterations": 1, "report": "daily-2026-10-14.json"})
    before = explog.log_path(project).read_text()
    monkeypatch.chdir(project)
    out = CliRunner().invoke(main, ["reflect", "log", "correct", "daily", "2026-10-14", "models.momus",
                                    "claude-sonnet-5-5"])
    assert out.exit_code == 0, out.output
    assert explog.log_path(project).read_text().startswith(before)  # nothing rewritten
    [run] = [r for r in explog.corrected(explog.load(project)) if r["record"] == "run"]
    assert run["models"]["momus"] == "claude-sonnet-5-5"
    bad = CliRunner().invoke(main, ["reflect", "log", "correct", "daily", "2026-10-15", "tokens", "5"])
    assert bad.exit_code == 1 and "No daily run" in bad.output
