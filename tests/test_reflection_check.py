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


@pytest.fixture
def env(tmp_path):
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


def test_a_seed_quoting_the_user_is_shown_without_three_sessions(env):
    project, _, root = env
    p = model_proposal(model="user", label="shown",
                       entry={"category": "identity", "scope": "any", "observation": "Uses they/them",
                              "evidence": [{"source": "/memory/kohl-pronouns.md", "quote": "Kohl uses they/them"}]})
    assert errors(project, report(proposals=[p]), root) == []


def test_a_personal_entry_is_rejected_in_a_work_project(env):
    project, digests, root = env
    p = model_proposal(model="user", label="shown", entry={"scope": "personal", "observation": "x", "evidence": []})
    p["text"] = cite(digests)
    assert any("work project" in e for e in errors(project, report(proposals=[p]), root, scope="work"))
    assert not any("work project" in e for e in errors(project, report(proposals=[p]), root, scope="personal"))


def test_self_interpretations_need_a_behavior_and_stances_state_no_conflict(env):
    project, digests, root = env
    p = model_proposal(model="self", entry={"kind": "interpretation", "observation": "I rush", "evidence": []})
    p["text"] = cite(digests)
    assert any("behavior entry" in e for e in errors(project, report(proposals=[p]), root))
    b = m.apply_change("self", {"op": "add", "entry": {"kind": "behavior", "observation": "I retried a lot",
                                                       "evidence": [{"session": REAL_SESSION}]}}, by="proposal", root=root)
    p["model"]["entry"]["evidence"] = [{"entry": b["id"]}]
    assert errors(project, report(proposals=[p]), root) == []
    stance = model_proposal(model="self", label="inferred", entry={"kind": "stance", "observation": "I ask first"})
    stance["text"] = cite(digests)
    assert any("identity_conflict" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_conflict"] = True
    assert any("identity_conflict" in e for e in errors(project, report(proposals=[stance]), root))
    stance["model"]["identity_conflict"] = False
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
            "file": {"path": "NOTES.md", "op": "append", "text": "Run doctor after the gameplan exists."}}


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
    assert not (project / "NOTES.md").exists()
    applied, _ = pq.apply(project, "Q1", root)
    assert (project / "NOTES.md").read_text(encoding="utf-8").strip() == "Run doctor after the gameplan exists."
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
              "model": {"model": "self", "op": "add", "identity_conflict": False,
                        "entry": {"kind": "stance", "observation": "I ask before pushing", "scope": "any"}}}
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
    target = project / "NOTES.md"
    target.write_text("x\n", encoding="utf-8")
    os.chmod(target, 0o644)
    path = write_report(project, report(proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path, root)
    pq.apply(project, "Q1", root)
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o644


def test_applying_a_file_proposal_keeps_crlf_line_endings(env):
    project, digests, root = env
    (project / "NOTES.md").write_bytes(b"first\r\nsecond\r\n")
    path = write_report(project, report(proposals=[file_proposal(project, digests)]), {"R1": "shown"})
    pq.import_report(project, path, root)
    pq.apply(project, "Q1", root)
    assert (project / "NOTES.md").read_bytes() == b"first\r\nsecond\r\nRun doctor after the gameplan exists.\r\n"


def test_evidence_must_take_a_known_shape(env):
    project, digests, root = env
    p = model_proposal(model="self", label="shown",
                       entry={"kind": "behavior", "observation": "I retried", "scope": "any",
                              "evidence": [{"session": REAL_SESSION, "digest": "counts.retries"}]})
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
