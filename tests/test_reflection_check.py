"""Report checks and the pending queue (edict 0010)."""

import json
from pathlib import Path

import pytest

from daedalus.reflection import models as m
from daedalus.reflection import pending as pq
from daedalus.reflection.check import REPORT_SCHEMA, check_report
from daedalus.reflection.digest import digest_project, load_digests

from reflection_helpers import INTERRUPT_SESSION, REAL_SESSION, install_fixtures, make_project

pytestmark = pytest.mark.reflection


IDENTITY_QUOTE = [{"file": "identity.md", "quote": "the builder/craftsman"}]


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


def report(**kw):
    base = {"schema": REPORT_SCHEMA, "level": "weekly", "period": "2026-W42", "findings": [], "proposals": []}
    base.update(kw)
    return base


def failure(digests):
    return digests[REAL_SESSION]["events"]["failures"][0]


def errors(project, rep, root, **kw):
    return check_report(project, rep, root, **kw).errors


# ---------- findings ----------


def test_a_good_report_passes(env):
    project, digests, root = env
    uuid = failure(digests)
    n = digests[REAL_SESSION]["tools"]["Bash"]["failures"]
    rep = report(findings=[{"id": "F1", "type": "failed_tool_call",
                            "text": f"Bash kept failing [s:{REAL_SESSION} e:{uuid}]",
                            "figures": [{"value": n, "cite": f"[s:{REAL_SESSION} d:tools.Bash.failures]"}]}])
    assert errors(project, rep, root) == []


def test_finding_without_a_citation_fails(env):
    project, _, root = env
    rep = report(findings=[{"id": "F1", "type": "pattern", "text": "Things were slow"}])
    assert any("no citation" in e for e in errors(project, rep, root))


def test_malformed_citation_fails(env):
    project, _, root = env
    rep = report(findings=[{"id": "F1", "type": "pattern", "text": f"Slow [s:{REAL_SESSION}]"}])
    assert any("not in the form" in e for e in errors(project, rep, root))


def test_fabricated_uuid_session_and_field_fail(env):
    project, _, root = env
    for text, expect in [(f"x [s:{REAL_SESSION} e:00000000-fake]", "not in session"),
                         ("x [s:no-such-session e:abc]", "has no digest"),
                         (f"x [s:{REAL_SESSION} d:counts.nothing]", "doesn't have")]:
        rep = report(findings=[{"id": "F1", "type": "pattern", "text": text}])
        assert any(expect in e for e in errors(project, rep, root)), text


def test_a_finding_must_cite_events_of_its_own_type(env):
    project, digests, root = env
    # The interrupt session's rejection is a real event, but not a failure
    rejection = digests[INTERRUPT_SESSION]["events"]["rejected_by_user"][0]
    rep = report(findings=[{"id": "F1", "type": "failed_tool_call", "text": f"x [s:{INTERRUPT_SESSION} e:{rejection}]"}])
    assert any("not one of" in e for e in errors(project, rep, root))
    rep["findings"][0]["type"] = "rejected_by_user"
    assert errors(project, rep, root) == []


def test_a_figure_must_match_the_digest(env):
    project, digests, root = env
    rep = report(findings=[{"id": "F1", "type": "pattern", "text": f"x [s:{REAL_SESSION} d:counts.failures]",
                            "figures": [{"value": 99, "cite": f"[s:{REAL_SESSION} d:counts.failures]"}]}])
    assert any("the digest says 8" in e for e in errors(project, rep, root))


# ---------- proposals against the models ----------


def model_proposal(op="add", label="inferred", **change):
    return {"id": "R1", "target": "model", "label": label, "text": "", "model": {"op": op, **change}}


def cite(digests, sessions=1):
    ids = list(digests)[:sessions]
    return " ".join(f"[s:{s} d:counts]" for s in ids)


def test_inferred_user_entries_need_three_sessions_and_a_working_preference(env):
    project, digests, root = env
    p = model_proposal(model="user", entry={"category": "working-preference", "scope": "any", "observation": "x",
                                            "evidence": [{"session": REAL_SESSION}, {"session": INTERRUPT_SESSION}]})
    p["text"] = cite(digests)
    assert any("three sessions" in e for e in errors(project, report(proposals=[p]), root))
    p["model"]["entry"]["category"] = "character"
    errs = errors(project, report(proposals=[p]), root)
    assert any("character" in e for e in errs)


def memory_note(text="Kohl uses they/them\n"):
    from reflection_helpers import claude_home

    note = claude_home() / "projects" / "-fixture-project" / "memory" / "pronouns.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(text, encoding="utf-8")
    return note


def test_a_seed_quoting_the_user_is_shown_without_three_sessions(env):
    project, _, root = env
    note = memory_note()
    p = model_proposal(model="user", label="shown",
                       entry={"category": "identity", "scope": "any", "observation": "Uses they/them",
                              "evidence": [{"source": str(note), "quote": "Kohl uses they/them"}]})
    assert errors(project, report(proposals=[p]), root) == []


def test_a_seed_must_really_quote_a_real_source(env):
    project, _, root = env
    note = memory_note()
    made_up = model_proposal(model="user", label="inferred",
                             entry={"category": "working-preference", "scope": "any", "observation": "x",
                                    "evidence": [{"source": "nowhere", "quote": "made up"}]})
    assert any("not an identity file or a Claude Code memory note" in e
               for e in errors(project, report(proposals=[made_up]), root))
    wrong_quote = model_proposal(model="user", label="shown",
                                 entry={"category": "x", "scope": "any", "observation": "x",
                                        "evidence": [{"source": str(note), "quote": "Kohl loves YAML"}]})
    assert any("quote is not in" in e for e in errors(project, report(proposals=[wrong_quote]), root))
    identity = model_proposal(model="user", label="shown",
                              entry={"category": "x", "scope": "any", "observation": "x", "evidence": [
                                  {"source": str(Path(__file__).parents[1] / "src/daedalus/identity/data/identity.md"),
                                   "quote": "the builder/craftsman"}]})
    assert any("own words" in e for e in errors(project, report(proposals=[identity]), root))
    empty = model_proposal(model="user", label="shown", entry={"category": "x", "scope": "any", "observation": "x"})
    empty["text"] = f"[s:{REAL_SESSION} d:counts]"
    assert any("cites its evidence" in e for e in errors(project, report(proposals=[empty]), root))


def test_a_personal_entry_is_rejected_in_a_work_project(env):
    project, digests, root = env
    p = model_proposal(model="user", label="shown", entry={"scope": "personal", "observation": "x", "evidence": []})
    p["text"] = cite(digests)
    assert any("work project" in e for e in errors(project, report(proposals=[p]), root, scope="work"))
    assert not any("work project" in e for e in errors(project, report(proposals=[p]), root, scope="personal"))


def test_self_interpretations_need_a_behavior_and_stances_state_no_conflict(env):
    project, digests, root = env
    p = model_proposal(model="self", entry={"kind": "interpretation", "observation": "I rush", "evidence": [],
                                            "model_ids": ["claude-test"]})
    p["text"] = cite(digests)
    assert any("behavior entry" in e for e in errors(project, report(proposals=[p]), root))
    b = m.apply_change("self", {"op": "add", "entry": {"kind": "behavior", "observation": "I retried a lot",
                                                       "evidence": [{"session": REAL_SESSION}]}}, by="proposal", root=root)
    p["model"]["entry"]["evidence"] = [{"entry": b["id"]}]
    assert errors(project, report(proposals=[p]), root) == []
    stance = model_proposal(model="self", label="inferred", entry={"kind": "stance", "observation": "I ask first",
                                                                   "evidence": [{"entry": b["id"]}],
                                                                   "model_ids": ["claude-test"]})
    stance["text"] = cite(digests)
    assert any("identity_conflict" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_conflict"] = True
    assert any("identity_conflict" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_conflict"] = False
    assert any("identity_checked" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_checked"] = [{"file": "identity.md", "quote": "a sentence that isn't there"}]
    assert any("quote is not in" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_checked"] = IDENTITY_QUOTE
    assert errors(project, report(proposals=[stance]), root) == []


def test_aspirations_are_not_proposals(env):
    project, digests, root = env
    p = model_proposal(model="self", entry={"kind": "aspiration", "observation": "To be kind"})
    p["text"] = cite(digests)
    assert any("not proposed" in e for e in errors(project, report(proposals=[p]), root))


def test_monthly_reports_carry_the_bundle_sections(env):
    project, _, root = env
    rep = report(level="monthly", period="2026-10")
    errs = errors(project, rep, root)
    assert any("'evolution' must be a list" in e for e in errs)
    bundle = {"lineage": ["s004"], "unmoved_aspirations": [], "model_dissents": []}
    rep.update(evolution=[], lineage=[], unmoved_aspirations=[], model_dissents=[])
    assert any("'lineage' must list ['s004']" in e for e in errors(project, rep, root, bundle=bundle))
    rep["lineage"] = ["s004"]
    assert errors(project, rep, root, bundle=bundle) == []


# ---------- the pending queue ----------


def write_report(project: Path, rep: dict, verdicts: dict | None) -> Path:
    path = project / ".daedalus" / "reflection" / "reports" / f"{rep['level']}-{rep['period']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep), encoding="utf-8")
    if verdicts is not None:
        pq.verdicts_path(path).write_text(json.dumps(verdicts), encoding="utf-8")
    return path


def file_proposal(project, digests, pid="R1"):
    return {"id": pid, "target": "file", "label": "shown", "text": f"Note it [s:{REAL_SESSION} e:{failure(digests)}]",
            "file": {"path": "CLAUDE.md", "op": "append", "text": "Run doctor after the gameplan exists."}}


def test_import_needs_momus_verdicts_and_drops_contradicted(env):
    project, digests, root = env
    rep = report(proposals=[file_proposal(project, digests, "R1"), file_proposal(project, digests, "R2")])
    path = write_report(project, rep, None)
    with pytest.raises(pq.PendingError, match="Momus verdict"):
        pq.import_report(project, path, root)
    write_report(project, rep, {"R1": {"verdict": "consistent"}, "R2": {"verdict": "contradicted", "note": "no"}})
    added, notes = pq.import_report(project, path, root)
    assert [p["report_proposal"] for p in added] == ["R1"]
    assert added[0]["verdict"] == "consistent"
    assert "contradicted" in notes[0]


def test_nothing_changes_before_apply_and_drop_discards(env):
    project, digests, root = env
    path = write_report(project, report(proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path, root)
    assert not (project / "CLAUDE.md").exists()
    applied, _ = pq.apply(project, "Q1", root)
    assert (project / "CLAUDE.md").read_text(encoding="utf-8").strip() == "Run doctor after the gameplan exists."
    assert pq.load_pending(project) == []
    path2 = write_report(project, report(period="2026-W43", proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path2, root)
    pq.drop(project, "Q2")
    assert pq.load_pending(project) == []


def test_gameplan_proposals_go_to_gameplan_pending(env):
    from daedalus.cli import gameplan as gp

    project, digests, root = env
    p = {"id": "R1", "target": "gameplan", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
         "gameplan": {"kind": "new-task", "task": "T-r1", "title": "Allowlist doctor", "details": "It prompts"}}
    pq.import_report(project, write_report(project, report(proposals=[p]), {"R1": "shown"}), root)
    _, notes = pq.apply(project, "Q1", root)
    assert "gameplan pending" in notes[0]
    handed = gp.load_pending(project)
    assert handed[0]["kind"] == "new-task" and handed[0]["task"] == "T-r1" and handed[0]["source"] == "reflection"


def test_permission_proposals_add_an_allow_rule(env):
    project, digests, root = env
    p = {"id": "R1", "target": "permission", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
         "permission": {"allow": "Bash(daedalus doctor:*)"}}
    pq.import_report(project, write_report(project, report(proposals=[p]), {"R1": "shown"}), root)
    pq.apply(project, "Q1", root)
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(daedalus doctor:*)"]


def test_stances_are_not_applied_in_a_batch(env):
    project, digests, root = env
    stance = {"id": "R1", "target": "model", "label": "inferred", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
              "model": {"model": "self", "op": "add", "identity_conflict": False, "identity_checked": IDENTITY_QUOTE,
                        "entry": {"kind": "stance", "observation": "I ask before pushing", "scope": "any",
                                  "evidence": [{"session": REAL_SESSION, "event": failure(digests)}],
                                  "model_ids": ["claude-test"]}}}
    pq.import_report(project, write_report(project, report(proposals=[stance]), {"R1": "consistent"}), root)
    applied, notes = pq.apply(project, "all", root)
    assert applied == [] and "on its own" in notes[0]
    assert m.load("self", root)["entries"] == []
    pq.apply(project, "Q1", root)
    assert m.load("self", root)["entries"][0]["observation"] == "I ask before pushing"
    assert m.load_history(root, "self")[-1]["proposal_id"] == "Q1"


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX permissions")
def test_applying_a_file_proposal_keeps_the_files_permissions(env):
    import os
    import stat

    project, digests, root = env
    target = project / "CLAUDE.md"
    target.write_text("x\n", encoding="utf-8")
    os.chmod(target, 0o644)
    path = write_report(project, report(proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path, root)
    pq.apply(project, "Q1", root)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o644


def test_applying_a_file_proposal_keeps_crlf_line_endings(env):
    project, digests, root = env
    (project / "CLAUDE.md").write_bytes(b"first\r\nsecond\r\n")
    path = write_report(project, report(proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path, root)
    pq.apply(project, "Q1", root)
    assert (project / "CLAUDE.md").read_bytes() == b"first\r\nsecond\r\nRun doctor after the gameplan exists.\r\n"


def test_evidence_must_take_a_known_shape(env):
    project, digests, root = env
    p = model_proposal(model="self", label="shown",
                       entry={"kind": "behavior", "observation": "I retried", "scope": "any",
                              "evidence": [{"session": REAL_SESSION, "digest": "counts.retries"}],
                              "model_ids": ["claude-test"]})
    p["text"] = cite(digests)
    assert any("is not one of" in e for e in errors(project, report(proposals=[p]), root))
    p["model"]["entry"]["evidence"] = [{"session": REAL_SESSION, "field": "counts.retries"}]
    assert errors(project, report(proposals=[p]), root) == []


def test_the_running_session_is_left_out_of_bundles(env, monkeypatch):
    from daedalus.reflection.bundle import build_bundle

    project, digests, root = env
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", REAL_SESSION)
    for d in (project / ".daedalus/reflection/sessions").glob("*.json"):
        data = json.loads(d.read_text(encoding="utf-8"))
        data["start"] = data["end"] = "2026-10-14T10:00:00Z"
        d.write_text(json.dumps(data), encoding="utf-8")
    bundle = build_bundle(project, "daily", "2026-10-14", {"half_life_self": 60, "half_life_user": 180}, "work", root)
    assert [d["session_id"] for d in bundle["digests"]] == [INTERRUPT_SESSION]


def test_file_proposals_reach_only_skills_agents_claude_md_and_memory(env):
    project, digests, root = env
    pkg_identity = Path(__file__).parents[1] / "src/daedalus/identity/data/identity.md"
    for path, ok in [("CLAUDE.md", True), (".claude/skills/inhale/SKILL.md", True), (".claude/agents/delphi.md", True),
                     (".claude/settings.json", False), ("src/app.py", False), ("../elsewhere/CLAUDE.md", False),
                     (str(pkg_identity), False), (str(memory_note()), True)]:
        p = file_proposal(project, digests)
        p["file"]["path"] = path
        errs = errors(project, report(proposals=[p]), root)
        assert (errs == []) == ok, (path, errs)


def test_permission_proposals_name_a_command_and_stay_in_the_project(env):
    project, digests, root = env
    for allow, path, ok in [("Bash(daedalus doctor:*)", None, True), ("Bash(*)", None, False), ("Bash", None, False),
                            ("*", None, False), ("Bash(daedalus doctor:*)", "/etc/settings.json", False)]:
        p = {"id": "R1", "target": "permission", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
             "permission": {"allow": allow, **({"path": path} if path else {})}}
        assert (errors(project, report(proposals=[p]), root) == []) == ok, allow


def test_aspirations_cant_be_proposed_against_or_filed_as_behavior(env):
    project, digests, root = env
    a = m.aspire("To finish what I start", "claude-test", "2026-10", root=root)
    p = model_proposal(op="retire", model="self", id=a["id"])
    p["text"] = cite(digests)
    assert any("is an aspiration" in e for e in errors(project, report(proposals=[p]), root))
    b = model_proposal(model="self", label="shown", entry={"kind": "behavior", "observation": "I finish things",
                                                           "evidence": [{"aspiration": a["id"]}],
                                                           "model_ids": ["claude-test"]})
    b["text"] = cite(digests)
    assert any("filed as a behavior" in e for e in errors(project, report(proposals=[b]), root))


def test_self_entries_record_model_ids(env):
    project, digests, root = env
    p = model_proposal(model="self", label="shown", entry={"kind": "behavior", "observation": "I retried",
                                                           "evidence": [{"session": REAL_SESSION, "field": "counts"}]})
    p["text"] = cite(digests)
    assert any("model_ids" in e for e in errors(project, report(proposals=[p]), root))


# ---------- Momus's review of the build (D3-D6) ----------


def test_render_needs_every_verdict_and_leaves_out_contradicted(env, monkeypatch):
    from click.testing import CliRunner

    from daedalus.cli.main import main

    project, digests, root = env
    monkeypatch.chdir(project)
    monkeypatch.setattr("daedalus.reflection.models.models_dir", lambda: root)
    rep = report(proposals=[file_proposal(project, digests, "R1"), file_proposal(project, digests, "R2")])
    path = write_report(project, rep, None)
    r = CliRunner().invoke(main, ["reflect", "render", str(path)])
    assert r.exit_code == 1 and "No Momus verdict" in r.output
    write_report(project, rep, {"R1": {"verdict": "consistent"}})
    assert CliRunner().invoke(main, ["reflect", "render", str(path)]).exit_code == 1
    write_report(project, rep, {"R1": {"verdict": "consistent"}, "R2": {"verdict": "contradicted"}})
    r = CliRunner().invoke(main, ["reflect", "render", str(path)])
    assert r.exit_code == 0, r.output
    md = path.with_suffix(".md").read_text(encoding="utf-8")
    assert "**R1**" in md and "Momus: consistent" in md and "**R2**" not in md and "contradicted by Momus: R2" in md
    assert CliRunner().invoke(main, ["reflect", "check", str(path)]).exit_code == 0
    assert not path.with_suffix(".md").read_text(encoding="utf-8") == ""  # check no longer writes it


def test_apply_all_saves_as_it_goes_and_a_report_cant_requeue(env):
    project, digests, root = env
    good = file_proposal(project, digests, "R1")
    bad = file_proposal(project, digests, "R2")
    bad["file"] = {"path": "CLAUDE.md", "op": "replace", "old": "not in the file", "new": "x"}
    path = write_report(project, report(proposals=[good, bad]), {"R1": "shown", "R2": "shown"})
    pq.import_report(project, path, root)
    with pytest.raises(pq.PendingError):
        pq.apply(project, "all", root)
    assert [p["report_proposal"] for p in pq.load_pending(project)] == ["R2"]  # R1 applied and gone
    pq.drop(project, "Q2")
    added, _ = pq.import_report(project, path, root)
    assert added == []  # applied and dropped proposals don't come back
    assert (project / "CLAUDE.md").read_text(encoding="utf-8").count("Run doctor") == 1


def test_revising_a_stance_is_not_batched(env):
    project, digests, root = env
    s = m.apply_change("self", {"op": "add", "entry": {"kind": "stance", "observation": "I ask first"}},
                       by="user", root=root)
    p = {"id": "R1", "target": "model", "label": "inferred", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
         "model": {"model": "self", "op": "revise", "id": s["id"], "changes": {"observation": "I never ask"},
                   "identity_conflict": False, "identity_checked": IDENTITY_QUOTE}}
    pq.import_report(project, write_report(project, report(proposals=[p]), {"R1": "consistent"}), root)
    applied, notes = pq.apply(project, "all", root)
    assert applied == [] and "on its own" in notes[0]
    assert m.find(m.load("self", root), s["id"])["observation"] == "I ask first"


def test_forget_keeps_no_text_and_drops_queued_proposals(env):
    project, digests, root = env
    e = m.apply_change("user", {"op": "add", "entry": {"observation": "Takes medication at 9am"}}, by="user", root=root)
    p = {"id": "R1", "target": "model", "label": "shown", "text": f"x [s:{REAL_SESSION} e:{failure(digests)}]",
         "model": {"model": "user", "op": "revise", "id": e["id"], "changes": {"confidence": 0.9}}}
    pq.import_report(project, write_report(project, report(proposals=[p]), {"R1": "shown"}), root)
    entry = m.forget(e["id"], "purge", root)
    assert pq.forget_queued(project, entry) == 1 and pq.load_pending(project) == []
    stored = m.model_path("user", root).read_text(encoding="utf-8") + (root / ".state.json").read_text(encoding="utf-8")
    assert "medication" not in stored.lower()
    assert m.is_tombstoned(m.load("user", root), observation="takes medication at 9am!")


def test_monthly_reports_say_whether_each_aspiration_moved(env):
    project, digests, root = env
    rep = report(level="monthly", period="2026-10", evolution=[], lineage=[], unmoved_aspirations=[],
                 model_dissents=[])
    bundle = {"lineage": [], "unmoved_aspirations": [], "model_dissents": [], "aspirations_active": ["s001"]}
    assert any("says nothing about s001" in e for e in errors(project, rep, root, bundle=bundle))
    rep["aspiration_movement"] = [{"id": "s001", "moved": True, "text": "I finished the branch"}]
    assert any("no citation" in e for e in errors(project, rep, root, bundle=bundle))
    rep["aspiration_movement"] = [{"id": "s001", "moved": False, "text": "Nothing this month."}]
    assert errors(project, rep, root, bundle=bundle) == []
