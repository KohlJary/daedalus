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
    meta = store.start(project, SETTINGS, theme=theme, mode=mode, today=today, seed=seed)
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
    assert "plain" not in waking and "list" not in waking.split("Seeds:")[0]


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
    assert out.startswith("AGENT: morpheus (dreamer)")
    f = tmp_path / "d.md"
    f.write_text(list_dream())
    assert run("dream", "write", dream_id, "dream", "--file", str(f)).exit_code == 0
    assert run("dream", "prompt", dream_id, "next").output.startswith("AGENT: general-purpose (waking)")
    f.write_text(WAKING)
    run("dream", "write", dream_id, "waking", "--file", str(f))
    done = run("dream", "done", dream_id, "--tokens", "10", "--dreamer-model", "claude-opus-5-5")
    assert done.exit_code == 0 and "31 ideas, 3 picks" in done.output
