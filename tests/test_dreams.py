"""Dreaming (edict 0013, as amended): seeds, modes, files, the dream source, the review, guardrails, due, log."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from daedalus.cli import gameplan as gp
from daedalus.dreams import prompts, review, seeds, store

from sources_helpers import index, offline, pending, project, run  # noqa: F401

SETTINGS = {"enabled": True, "mode": "ab", "seeds": 5, "turns": 4, "max_tokens": 60000, "review_min": 4,
            "recur_min": 3}


@pytest.fixture
def dreaming(project):
    assert run("config", "--project", "dream.enabled", "true").exit_code == 0
    data = gp.load_gameplan(project)
    gp.add_phase(data, "p1", "Phase one")
    gp.activate_phase(data, "p1")
    gp.add_task(data, "T-1", "Build the thing", details="see src/app/core.py")
    data["activePhase"]["tasks"][0].update(status="in_progress", updated="2026-09-01")
    gp.save_gameplan(project, data)
    idx = {"items": [{"id": "abc12345", "title": "Export to CSV", "status": "backlog", "created_at": "2026-08-01",
                      "origin": {"source": "local"}}], "version": 1}
    (project / ".daedalus/roadmap/index.json").write_text(json.dumps(idx))
    (project / "docs").mkdir(exist_ok=True)
    (project / "docs/status.md").write_text("# Status\n\n## Open questions\n- Should the TUI show dreams?\n")
    return project


def list_dream(n=31):
    return "## Ideas\n\n" + "\n".join(f"{i}. Idea number {i} about the labyrinth" for i in range(1, n + 1))


WAKING = """## Picks

1. **Glass labyrinth**: from i3. It grew from the stalled task; make it real with a map view.
2. **Wings for the CLI**: from i7. It grew from the open question; ship a release command.
3. **Thread of Ariadne**: from i12. It grew from the backlog; a resumable trail.
"""


def make_dream(project, mode="list", theme=None, today=None, seed=None):
    # The mode comes from settings (a configured mode), not forced, so these dreams count in the A/B report
    meta = store.start(project, {**SETTINGS, "mode": mode}, theme=theme, today=today, seed=seed)
    if mode == "narrative":
        for k in range(SETTINGS["turns"]):
            store.append_turn(project, meta["id"], "narrator", f"You walk a corridor {k}.", SETTINGS)
            store.append_turn(project, meta["id"], "dreamer", f"I build a door {k}.", SETTINGS)
        store.write_part(project, meta["id"], "waking", "## Ideas\n\n1. A door\n2. A map\n\n" + WAKING, SETTINGS)
    else:
        store.write_part(project, meta["id"], "dream", list_dream(), SETTINGS)
        store.write_part(project, meta["id"], "waking", WAKING, SETTINGS)
    store.done(project, meta["id"], {"dreamer": "claude-opus-5-5"}, 1234)
    return meta["id"]


# ---------- seeds ----------

def test_seeds_are_deterministic_cover_the_kinds_and_put_a_theme_first(dreaming):
    today = date(2026, 10, 15)
    a = seeds.select_seeds(dreaming, SETTINGS, today=today)
    b = seeds.select_seeds(dreaming, SETTINGS, today=today)
    assert a == b
    kinds = {s["kind"] for s in seeds.candidates(dreaming, SETTINGS, today)}
    assert {"stale_task", "backlog", "open_question"} <= kinds
    themed = seeds.select_seeds(dreaming, SETTINGS, theme="the TUI", today=today)
    assert themed[0]["kind"] == "theme" and themed[0]["text"] == "the TUI"
    assert len({s["kind"] for s in a}) >= 2


def test_readiness_is_the_weighted_formula(dreaming):
    ranked = seeds.score(dreaming, seeds.candidates(dreaming, SETTINGS, date(2026, 10, 15)))
    assert all(0 <= s["readiness"] <= 1 for s in ranked)
    assert ranked == sorted(ranked, key=lambda s: (-s["readiness"], s["id"]))


# ---------- modes ----------

def test_ab_draws_the_mode_in_code_and_logs_it(dreaming):
    meta = store.start(dreaming, SETTINGS, seed=7)
    assert meta["mode"] in store.MODES and meta["seed"] == 7
    assert store.draw_mode("ab", 7) == (meta["mode"], 7)
    starts = [r for r in store.load_log(dreaming) if r["record"] == "start"]
    assert starts[-1]["mode"] == meta["mode"] and starts[-1]["seed"] == 7
    skill = Path(__file__).parents[1] / "src/daedalus/plugin/skills/dream/SKILL.md"
    assert "--mode" not in skill.read_text()


def test_narrative_runs_its_turns_and_a_wake_word_does_not_end_it(dreaming):
    meta = store.start(dreaming, SETTINGS, mode="narrative")
    for k in range(SETTINGS["turns"]):
        store.append_turn(dreaming, meta["id"], "narrator", "A hall.", SETTINGS)
        store.append_turn(dreaming, meta["id"], "dreamer", "I wake, I leave, I return, I exit." if k == 0 else "I stay.",
                          SETTINGS)
        if k < SETTINGS["turns"] - 1:
            assert prompts.next_step(dreaming, meta["id"], SETTINGS) == "narrator"
    with pytest.raises(store.DreamError, match="its 4 turns"):
        store.append_turn(dreaming, meta["id"], "narrator", "More.", SETTINGS)
    assert prompts.next_step(dreaming, meta["id"], SETTINGS) == "waking"


def test_the_plain_arm_has_no_dream_frame(dreaming):
    meta = store.start(dreaming, SETTINGS, mode="plain")
    agent, text = prompts.build(dreaming, meta["id"], "dreamer", SETTINGS)
    frame = prompts.PLAIN.replace("{seeds}", "")
    assert agent == "general-purpose" and "dream" not in frame.lower() and "speculative" not in frame.lower()
    assert text.startswith(frame.split("\n")[0])
    store.write_part(dreaming, meta["id"], "dream", list_dream(), SETTINGS)
    _, waking = prompts.build(dreaming, meta["id"], "waking", SETTINGS)
    assert "plain" not in waking and "dream" not in prompts.WAKING.lower()
    other = store.start(dreaming, SETTINGS, mode="list")
    assert prompts.build(dreaming, other["id"], "dreamer", SETTINGS)[0] == agent  # the agent can't tell them apart
    store.write_part(dreaming, other["id"], "dream", list_dream(), SETTINGS)
    _, list_waking = prompts.build(dreaming, other["id"], "waking", SETTINGS)
    frame = lambda w: (w.split("The notes:")[0], w.split("The text:")[1])  # noqa: E731
    assert frame(list_waking) == frame(waking)  # the arms differ only at generation (seed order aside)


def test_a_dream_over_the_token_cap_is_truncated(dreaming):
    meta = store.start(dreaming, {**SETTINGS, "max_tokens": 10}, mode="list")
    store.write_part(dreaming, meta["id"], "dream", list_dream(), {**SETTINGS, "max_tokens": 10})
    assert store.load_meta(dreaming, meta["id"])["truncated"] is True


# ---------- files ----------

def test_files_carry_the_label_are_ignored_and_keep_writes_docs(dreaming):
    dream_id = make_dream(dreaming)
    folder = store.dream_dir(dreaming, dream_id)
    for part in ("dream.md", "waking.md"):
        assert (folder / part).read_text().startswith(store.LABEL)
    assert [i["id"] for i in store.ideas(dreaming, dream_id)][:2] == [f"{dream_id}.i1", f"{dream_id}.i2"]
    assert [p["id"] for p in store.picks(dreaming, dream_id)] == [f"{dream_id}.p{n}" for n in (1, 2, 3)]
    run("init", "--no-hooks")
    assert subprocess.run(["git", "check-ignore", "-q", f".daedalus/dreams/{dream_id}/dream.md"],
                          cwd=dreaming).returncode == 0
    out = run("dream", "keep", dream_id)
    assert out.exit_code == 0 and (dreaming / f"docs/dreams/{dream_id}.md").read_text().startswith(store.LABEL.rstrip())
    shown = run("dream", "show", dream_id).output
    assert "list" not in shown.split("# Dream")[1].split("\n")[0] and "mode" not in shown


def test_narrative_ideas_come_from_the_waking_pass(dreaming):
    dream_id = make_dream(dreaming, mode="narrative")
    assert [i["text"] for i in store.ideas(dreaming, dream_id)] == ["A door", "A map"]


# ---------- the dream source ----------

def test_picks_sync_as_ideas_once_and_dropped_ones_stay_dropped(dreaming):
    dream_id = make_dream(dreaming)
    out = run("source", "sync", "dream")
    assert out.exit_code == 0, out.output
    props = pending(dreaming)
    assert [p["item"]["id"] for p in props] == [f"dream-{dream_id}.p{n}" for n in (1, 2, 3)]
    assert all(p["item"]["item_type"] == "idea" and p["item"]["priority"] == "P2" for p in props)
    assert "proposed 0" in run("source", "sync", "dream").output
    run("gameplan", "pending", "drop", props[0]["id"])
    run("gameplan", "pending", "apply", "all")
    assert "proposed 0" in run("source", "sync", "dream").output
    log = store.load_log(dreaming)
    outcomes = {r["item"]: r["outcome"] for r in log if r["record"] == "resolution"}
    assert outcomes[f"{dream_id}.p1"] == "dropped" and outcomes[f"{dream_id}.p2"] == "applied"
    from daedalus.sources.dream import DreamSource

    assert DreamSource.supports_write_back is False


def test_the_dream_source_is_off_unless_dreaming_is(project):
    assert "dream" not in run("source", "list").output.split("Sources here")[1]


# ---------- the review ----------

def _review(project, themes, recur_min=3):
    bundle = review.build_bundle(project)
    return review.record(project, bundle, {"themes": themes}, {**SETTINGS, "recur_min": recur_min})


def test_a_theme_in_three_dreams_with_different_seeds_is_elevated_as_p1(dreaming):
    ids = []
    for k, theme in enumerate(("doors", "maps", "wings")):
        ids.append(make_dream(dreaming, theme=theme, today=date(2026, 10, 10 + k)))
    themes = [{"title": "A map of the labyrinth", "summary": "Show the codebase as a place.",
               "ideas": [f"{d}.i3" for d in ids], "integrated_by": None},
              {"title": "Bogus", "summary": "x", "ideas": ["2020-01-01.i1"], "integrated_by": None}]
    out = _review(dreaming, themes)
    [t] = out["themes"]
    assert t["elevated"] and t["dreams"] == 3 and t["distinct_top_seeds"] == 3 and len(out["dropped"]) == 1
    run("source", "sync", "dream")
    theme_prop = next(p for p in pending(dreaming) if p["origin"]["external_id"].startswith("theme:"))
    assert theme_prop["item"]["priority"] == "P1"
    assert theme_prop["item"]["description"].startswith("recurring (3 dreams)")


def test_a_covered_theme_is_listed_not_proposed(dreaming):
    ids = [make_dream(dreaming, theme=t, today=date(2026, 10, 10 + k)) for k, t in enumerate("abc")]
    out = _review(dreaming, [{"title": "CSV", "summary": "x", "ideas": [f"{d}.i1" for d in ids],
                              "integrated_by": "abc12345"}])
    assert not out["themes"][0]["elevated"] and out["themes"][0]["integrated_by"] == "abc12345"


def test_recurrence_needs_different_top_seeds(dreaming):
    ids = [make_dream(dreaming, theme="same", today=date(2026, 10, 10 + k)) for k in range(3)]
    out = _review(dreaming, [{"title": "Same", "summary": "x", "ideas": [f"{d}.i2" for d in ids],
                              "integrated_by": None}])
    t = out["themes"][0]
    assert t["dreams"] == 3 and t["distinct_top_seeds"] == 1 and not t["elevated"] and not t["independent"]


def test_a_dropped_theme_returns_once_after_more_recurrences_then_retires(dreaming):
    ids = [make_dream(dreaming, theme=t, today=date(2026, 10, 1 + k)) for k, t in enumerate("abc")]
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in ids], "integrated_by": None}])
    run("source", "sync", "dream")
    theme = next(p for p in pending(dreaming) if p["origin"]["external_id"].startswith("theme:"))
    run("gameplan", "pending", "drop", theme["id"])
    run("source", "sync", "dream")
    assert not any(p["origin"]["external_id"].startswith("theme:") for p in pending(dreaming))
    more = [make_dream(dreaming, theme=t, today=date(2026, 10, 5 + k)) for k, t in enumerate("def")]
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{ids[0]}.i3"] + [f"{d}.i3" for d in more],
                        "integrated_by": None}])
    run("source", "sync", "dream")
    back = next(p for p in pending(dreaming) if p["origin"]["external_id"].startswith("theme:"))
    assert "You dropped it" in back["item"]["description"]
    run("gameplan", "pending", "drop", back["id"])
    final = [make_dream(dreaming, theme=t, today=date(2026, 10, 12 + k)) for k, t in enumerate("ghi")]
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{ids[0]}.i3"] + [f"{d}.i3" for d in final],
                        "integrated_by": None}])
    run("source", "sync", "dream")
    assert not any(p["origin"]["external_id"].startswith("theme:") for p in pending(dreaming))


# ---------- guardrails ----------

def test_reflect_check_rejects_a_report_leaning_on_a_dream(dreaming):
    from daedalus.reflection.check import REPORT_SCHEMA, check_report

    dream_id = make_dream(dreaming)
    rep = {"schema": REPORT_SCHEMA, "level": "weekly", "period": "2026-W42", "proposals": [],
           "findings": [], "summary": f"As the dream {dream_id}.p2 suggested, see .daedalus/dreams/{dream_id}/"}
    errs = check_report(dreaming, rep, dreaming / "models").errors
    assert any("never evidence" in e for e in errs)


def test_models_refuse_dream_evidence(tmp_path):
    from daedalus.reflection import models as m

    with pytest.raises(m.ModelError, match="never evidence"):
        m.apply_change("self", {"op": "add", "entry": {"observation": "x", "evidence": [
            {"source": "docs/dreams/2026-10-15.md", "quote": "wings"}]}}, by="proposal", root=tmp_path)


def test_reflection_models_and_pending_import_nothing_from_dreams():
    src = Path(__file__).parents[1] / "src/daedalus/reflection"
    for name in ("models.py", "pending.py"):
        text = (src / name).read_text()
        assert "dreams" not in [w for line in text.splitlines() if line.lstrip().startswith(("import", "from"))
                                for w in line.replace(".", " ").split()], name


def test_delphi_bundles_hold_no_dream_content(dreaming):
    from daedalus.reflection.bundle import build_bundle

    make_dream(dreaming)
    bundle = build_bundle(dreaming, "weekly", "2026-W42", {"half_life_self": 60, "half_life_user": 180}, "work",
                          root=dreaming / "models")
    assert "labyrinth" not in json.dumps(bundle).lower() and "dreams/" not in json.dumps(bundle)


def test_the_brief_has_one_dream_line_and_no_dream_text(dreaming):
    import sys

    from daedalus.hooks import session_start_brief

    make_dream(dreaming)
    for mod in [m for m in sys.modules if m.startswith("daedalus.dreams")]:
        del sys.modules[mod]
    brief = session_start_brief(dreaming)
    lines = [l for l in brief.splitlines() if "dream" in l.lower()]
    assert len(lines) == 1 and "waiting" in lines[0] and "labyrinth" not in brief.lower()
    assert not any(m.startswith("daedalus.dreams") for m in sys.modules)


# ---------- due ----------

def test_a_dream_is_due_after_a_reflection_run_and_not_twice_a_day(dreaming):
    from daedalus.reflection import explog

    assert store.compute_due(dreaming)["due"] is False
    explog.append(dreaming, {"record": "run", "level": "daily", "period": "2026-10-14", "runner": "inhale",
                             "models": {}, "sessions": 1, "session_ids": [], "tokens": 1, "findings": {},
                             "proposals": [], "check_iterations": 1, "report": "daily-2026-10-14.json"})
    assert store.compute_due(dreaming)["due"] is True
    make_dream(dreaming)
    assert store.compute_due(dreaming)["due"] is False


# ---------- the log ----------

def test_the_log_holds_no_text_and_summarises_per_mode(dreaming):
    make_dream(dreaming, mode="list")
    make_dream(dreaming, mode="plain")
    raw = store.log_path(dreaming).read_text()
    assert "labyrinth" not in raw.lower() and "Glass" not in raw
    with pytest.raises(store.DreamError):
        store.log(dreaming, {"record": "resolution", "item": "a pick with words in it", "outcome": "applied"})
    out = run("dream", "log").output
    assert "list: 1 dream(s)" in out and "plain: 1 dream(s)" in out and "untested" in out


def test_cli_walks_a_list_dream_end_to_end(dreaming, tmp_path):
    assert run("dream", "start", "--mode", "list").exit_code == 0
    dream_id = store.list_dreams(dreaming)[-1]
    out = run("dream", "prompt", dream_id, "next").output
    assert out.startswith("AGENT: general-purpose (dreamer)") and "You are Morpheus" in out
    f = tmp_path / "d.md"
    f.write_text(list_dream())
    assert run("dream", "write", dream_id, "dream", "--file", str(f)).exit_code == 0
    assert run("dream", "prompt", dream_id, "next").output.startswith("AGENT: general-purpose (waking)")
    f.write_text(WAKING)
    run("dream", "write", dream_id, "waking", "--file", str(f))
    done = run("dream", "done", dream_id, "--tokens", "10", "--dreamer-model", "claude-opus-5-5")
    assert done.exit_code == 0 and "31 ideas, 3 picks" in done.output


# ---------- fixes from Momus's trial (2026-10-15-edict-0013-build) ----------

REAL_COVERAGE = Path(__file__).parents[1] / "docs/design/tui/coverage.md"


def test_coverage_gaps_are_only_the_detail_tables_marked_rows(dreaming):
    """B1: the real coverage.md. Summary, totals and legend rows aren't gaps; no seed has an empty key."""
    dest = dreaming / "docs/design/tui/coverage.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(REAL_COVERAGE.read_text(encoding="utf-8"), encoding="utf-8")
    gaps = [s for s in seeds.candidates(dreaming, SETTINGS, date(2026, 10, 15)) if s["kind"] == "coverage_gap"]
    assert sorted(s["key"] for s in gaps) == sorted([
        "ariadne-bus-pending-verified-rejected-diffs-conflicts", "ariadne-plans-daedalus-plans",
        "theseus-reports", "mind-palace-labyrinth-map"])
    assert all(s["key"] and s["id"] != "coverage_gap:" for s in gaps)
    assert all("Direct coverage" not in s["text"] and "Group" not in s["text"] for s in gaps)


def test_recurrence_matches_whole_tokens_and_never_an_empty_key(dreaming):
    """B1: `T-e1` doesn't recur in a report naming only `T-e12`; an empty key recurs nowhere."""
    reports = dreaming / ".daedalus/reflection/reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "weekly-2026-W41.json").write_text(json.dumps({"period": "2026-W41", "findings": [
        {"id": "f1", "text": "T-e12 stalled again."}]}))
    assert seeds._recurrence(dreaming, {"key": "T-e1"}) == 0
    assert seeds._recurrence(dreaming, {"key": "T-e12"}) == 1
    assert seeds._recurrence(dreaming, {"key": ""}) == 0


@pytest.mark.parametrize("period,age", [("2026-W40", 11), ("2026-09", 15), ("2026-10-03", 12)])
def test_finding_seeds_age_from_weekly_and_monthly_periods(dreaming, period, age):
    """B1: a finding is aged from the end of its report's period, whatever the period's shape."""
    reports = dreaming / ".daedalus/reflection/reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"r-{period}.json").write_text(json.dumps({"period": period, "findings": [
        {"id": "f1", "text": "Something recurs."}]}))
    [f] = [s for s in seeds.candidates(dreaming, SETTINGS, date(2026, 10, 15)) if s["kind"] == "finding"]
    assert f["age_days"] == age


def test_a_recent_top_seed_ranks_after_the_others(dreaming):
    """B1 (F-d1): with the project unchanged, three nights give three different top seeds."""
    ids = [make_dream(dreaming, today=date(2026, 10, 10 + k)) for k in range(3)]
    tops = [review._top_seed(dreaming, d) for d in ids]
    assert len(set(tops)) == 3, tops
    ranked = seeds.score(dreaming, seeds.candidates(dreaming, SETTINGS, date(2026, 10, 13)))
    assert ranked[-1]["recent_top"] and ranked[-1]["id"] in tops[1:]
    assert ranked[0]["id"] == tops[0]  # out of the last two, it's back on top


def _three(project, start=1, themes="abc"):
    return [make_dream(project, theme=t, today=date(2026, 10, start + k)) for k, t in enumerate(themes)]


def test_review_split_gives_the_old_id_to_one_theme(dreaming):
    """B2: two themes overlapping one old theme: the larger overlap keeps the ID, the other is new and
    holds only its own ideas."""
    old = _three(dreaming)
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in old], "integrated_by": None}])
    new = _three(dreaming, 5, "de")
    out = _review(dreaming, [
        {"title": "Map A", "summary": "x", "ideas": [f"{old[0]}.i3", f"{old[1]}.i3", f"{new[0]}.i1"], "integrated_by": None},
        {"title": "Map B", "summary": "x", "ideas": [f"{old[2]}.i3", f"{new[1]}.i1"], "integrated_by": None}])
    a, b = out["themes"]
    assert a["id"] == "t1" and b["id"] == "t2"
    assert b["ideas"] == sorted([f"{old[2]}.i3", f"{new[1]}.i1"]) and b["dreams"] == 2
    assert a["ideas"] == sorted([f"{old[0]}.i3", f"{old[1]}.i3", f"{new[0]}.i1"])
    registry = review.load_themes(dreaming)["themes"]
    assert not set(registry["t1"]["ideas"]) & set(registry["t2"]["ideas"])
    text = (review.reviews_dir(dreaming) / f"{out['review']}.md").read_text()
    assert text.count("## t1:") == 1


def test_review_merge_into_a_covered_theme_supersedes_the_other(dreaming):
    """B2: two elevated themes merged into one that's covered: neither stays elevated."""
    ids = _three(dreaming)
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in ids], "integrated_by": None},
                       {"title": "Wings", "summary": "y", "ideas": [f"{d}.i5" for d in ids], "integrated_by": None}])
    assert [t["id"] for t in review.elevated(dreaming)] == ["t1", "t2"]
    out = _review(dreaming, [{"title": "Both", "summary": "z", "integrated_by": "abc12345",
                              "ideas": [f"{d}.i{n}" for d in ids for n in (3, 5)]}])
    assert [t["id"] for t in out["themes"]] == ["t1"] and review.elevated(dreaming) == []
    t2 = review.load_themes(dreaming)["themes"]["t2"]
    assert t2["superseded"] and t2["superseded_by"] == "t1" and not t2["elevated"]


def test_review_rename_with_no_shared_ideas_stops_the_old_theme(dreaming):
    """B2: a theme regrouped under only new ideas is a new theme, and the old one isn't proposed twice."""
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in _three(dreaming)],
                        "integrated_by": None}])
    new = _three(dreaming, 5, "def")
    _review(dreaming, [{"title": "Atlas", "summary": "x", "ideas": [f"{d}.i4" for d in new], "integrated_by": None}])
    assert [t["id"] for t in review.elevated(dreaming)] == ["t2"]
    t1 = review.load_themes(dreaming)["themes"]["t1"]
    assert t1["superseded"] and t1["superseded_by"] is None


def test_review_an_idea_claimed_twice_stays_with_the_first_and_empty_themes_go(dreaming):
    """B2: duplicate claims: the second theme keeps only its own ideas, or is dropped if none are left."""
    ids = _three(dreaming)
    out = _review(dreaming, [
        {"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in ids], "integrated_by": None},
        {"title": "Echo", "summary": "x", "ideas": [f"{ids[0]}.i3"], "integrated_by": None},
        {"title": "Part", "summary": "x", "ideas": [f"{ids[1]}.i3", f"{ids[1]}.i4"], "integrated_by": None}])
    assert [(t["id"], t["ideas"]) for t in out["themes"]] == [
        ("t1", sorted(f"{d}.i3" for d in ids)), ("t2", [f"{ids[1]}.i4"])]
    assert [d["title"] for d in out["dropped"]] == ["Echo"]
    assert set(review.load_themes(dreaming)["themes"]) == {"t1", "t2"}


def test_done_refuses_a_dream_already_done(dreaming):
    """B3: a second `done` doesn't log a second run."""
    dream_id = make_dream(dreaming)
    with pytest.raises(store.DreamError, match="already done"):
        store.done(dreaming, dream_id, {}, 1)
    assert run("dream", "done", dream_id).exit_code != 0
    assert [r["record"] for r in store.load_log(dreaming)] == ["start", "run"]


def test_a_forced_mode_is_logged_and_kept_out_of_the_ab(dreaming, tmp_path):
    """B3: `dream start --mode` is recorded as forced and reported apart from the drawn dreams."""
    assert run("dream", "start", "--mode", "plain").exit_code == 0
    dream_id = store.list_dreams(dreaming)[-1]
    store.write_part(dreaming, dream_id, "dream", list_dream(), SETTINGS)
    store.write_part(dreaming, dream_id, "waking", WAKING, SETTINGS)
    assert run("dream", "done", dream_id).exit_code == 0
    assert all(r["forced"] is True for r in store.load_log(dreaming) if r["record"] in ("start", "run"))
    make_dream(dreaming, mode="list")
    out = run("dream", "log").output
    drawn, forced = out.split("Forced dreams")
    assert "list: 1 dream(s)" in drawn and "plain" not in drawn and "plain: 1 dream(s)" in forced


def test_the_cli_holds_the_narrative_to_its_order(dreaming, tmp_path):
    """B3: narrator first, then alternating; no waking pass until the turns are taken."""
    meta = store.start(dreaming, {**SETTINGS, "mode": "narrative"})
    f = tmp_path / "t.md"
    f.write_text("A hall.")
    turn = lambda who: run("dream", "turn", meta["id"], who, "--file", str(f)).exit_code  # noqa: E731
    assert turn("dreamer") != 0
    assert turn("narrator") == 0 and turn("narrator") != 0 and turn("dreamer") == 0
    f.write_text(WAKING)
    assert run("dream", "write", meta["id"], "waking", "--file", str(f)).exit_code != 0
    assert run("dream", "prompt", meta["id"], "waking").exit_code != 0
    f.write_text("A hall.")
    for _ in range(SETTINGS["turns"] - 1):
        assert turn("narrator") == 0 and turn("dreamer") == 0
    f.write_text("## Ideas\n\n1. A hall\n\n" + WAKING)
    assert run("dream", "write", meta["id"], "waking", "--file", str(f)).exit_code == 0
    assert run("dream", "done", meta["id"]).exit_code == 0


def test_a_truncated_first_turn_still_wakes(dreaming):
    """B3 (F-n1): a first turn over the cap ends the dream; the waking pass runs on the empty transcript."""
    small = {**SETTINGS, "mode": "narrative", "max_tokens": 5}
    meta = store.start(dreaming, small)
    with pytest.raises(store.DreamError, match="truncated"):
        store.append_turn(dreaming, meta["id"], "narrator", "x" * 100, small)
    assert prompts.next_step(dreaming, meta["id"], small) == "waking"
    agent, text = prompts.build(dreaming, meta["id"], "waking", small)
    assert "cut off" in text and "empty" in text
    store.write_part(dreaming, meta["id"], "waking", "## Ideas\n\n1. A hall\n\n" + WAKING, small)
    assert store.done(dreaming, meta["id"], {}, None, settings=small)["status"] == "done"


def test_dreaming_off_means_no_due_file_and_no_brief_line(project):
    """B4: with dream.enabled unset, a reflection run makes nothing due and the brief says nothing."""
    from daedalus.hooks import session_start_brief
    from daedalus.reflection import explog

    explog.append(project, {"record": "run", "level": "daily", "period": "2026-10-14", "runner": "inhale",
                            "models": {}, "sessions": 1, "session_ids": [], "tokens": 1, "findings": {},
                            "proposals": [], "check_iterations": 1, "report": "daily-2026-10-14.json"})
    assert run("reflect", "done", "daily", "2026-10-14").exit_code == 0
    assert store.refresh_due(project)["due"] is False
    assert not store.due_path(project).exists()
    assert "Dream" not in session_start_brief(project)
    # A due.json without "enabled": true (an older one, or hand-made) is ignored by the hook
    store.due_path(project).parent.mkdir(parents=True, exist_ok=True)
    store.due_path(project).write_text(json.dumps({"due": True, "waiting": "2026-10-14"}))
    assert "Dream" not in session_start_brief(project)


def test_dreaming_on_writes_an_enabled_due_file(dreaming):
    """B4, the other side: with dreaming on, due.json says so and the brief shows the line."""
    make_dream(dreaming)
    assert json.loads(store.due_path(dreaming).read_text())["enabled"] is True


def test_keep_never_overwrites_without_force(dreaming):
    """B5: a kept or hand-made docs/dreams/<id>.md survives `dream keep` of a dream with the same ID."""
    dream_id = make_dream(dreaming)
    dest = dreaming / f"docs/dreams/{dream_id}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("FIRST DREAM")
    out = run("dream", "keep", dream_id)
    assert out.exit_code != 0 and dest.read_text() == "FIRST DREAM"
    assert run("dream", "keep", dream_id, "--force").exit_code == 0 and dest.read_text().startswith(store.LABEL.rstrip())


def test_review_show_prints_the_newest_by_time(dreaming):
    import os

    folder = review.reviews_dir(dreaming)
    folder.mkdir(parents=True)
    (folder / "2026-10-15.md").write_text("FIRST")
    (folder / "2026-10-15-2.md").write_text("SECOND")
    os.utime(folder / "2026-10-15.md", (1, 1))
    assert run("dream", "review", "show").output.strip() == "SECOND"


def test_the_log_reports_elevated_theme_outcomes(dreaming):
    ids = _three(dreaming)
    _review(dreaming, [{"title": "Map", "summary": "x", "ideas": [f"{d}.i3" for d in ids], "integrated_by": None}])
    run("source", "sync", "dream")
    theme = next(p for p in pending(dreaming) if p["origin"]["external_id"].startswith("theme:"))
    run("gameplan", "pending", "drop", theme["id"])
    assert "Elevated themes (synced / applied / dropped / built): 0 / 0 / 1 / 0." in run("dream", "log").output


def test_reordered_seeds_are_not_independent_recurrence(dreaming, monkeypatch):
    """Momus N1: the recency penalty rotates the top seed on unchanged state; the same seed set in another
    order is the same material and counts once."""
    ids = [make_dream(dreaming, today=date(2026, 10, 1 + k)) for k in range(3)]
    sets = {"|".join(sorted(s["id"] for s in json.loads((store.dream_dir(dreaming, d) / "seeds.json").read_text())["seeds"]))
            for d in ids}
    out = _review(dreaming, [{"title": "Same stuff", "summary": "x", "ideas": [f"{d}.i4" for d in ids],
                              "integrated_by": None}])
    assert out["themes"][0]["distinct_top_seeds"] == len(sets)
    if len(sets) == 1:
        assert not out["themes"][0]["elevated"]
