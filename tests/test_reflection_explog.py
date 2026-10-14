"""The experiment log (edict 0010, amended): runs and outcomes, counts and IDs only."""

import json

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.reflection import explog
from daedalus.reflection import pending as pq
from daedalus.reflection.arms import assign_arm
from daedalus.reflection.check import REPORT_SCHEMA
from daedalus.reflection.digest import digest_project, load_digests

from reflection_helpers import REAL_SESSION, install_fixtures, make_project

pytestmark = pytest.mark.reflection
SECRET_TEXT = "Kohl mentioned the zebra-colored umbrella"


@pytest.fixture
def project(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: cfg)
    monkeypatch.setattr("daedalus.reflection.paths.get_config_dir", lambda: cfg)
    p = make_project(tmp_path / "proj")
    install_fixtures(p)
    digest_project(p)
    monkeypatch.chdir(p)
    return p


def write_report(project, digests):
    uuid = digests[REAL_SESSION]["events"]["failures"][0]
    rep = {"schema": REPORT_SCHEMA, "level": "weekly", "period": "2026-W42",
           "findings": [{"id": "F1", "type": "failed_tool_call", "text": f"{SECRET_TEXT} [s:{REAL_SESSION} e:{uuid}]"}],
           "proposals": [{"id": "R1", "target": "file", "label": "shown",
                          "text": f"{SECRET_TEXT} [s:{REAL_SESSION} e:{uuid}]",
                          "file": {"path": "CLAUDE.md", "op": "append", "text": SECRET_TEXT}},
                         {"id": "R2", "target": "file", "label": "inferred",
                          "text": f"Another [s:{REAL_SESSION} e:{uuid}]",
                          "file": {"path": "CLAUDE.md", "op": "append", "text": "x"}}]}
    path = project / ".daedalus/reflection/reports/weekly-2026-W42.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rep), encoding="utf-8")
    pq.verdicts_path(path).write_text(json.dumps({"R1": {"verdict": "consistent", "note": SECRET_TEXT},
                                                  "R2": {"verdict": "untested"}}), encoding="utf-8")
    return path


def log_bytes(project):
    path = explog.log_path(project)
    return path.read_bytes() if path.exists() else b""


def test_done_apply_drop_and_arm_each_append_one_record_and_no_text(project, tmp_path):
    digests = {d["session_id"]: d for d in load_digests(project)}
    report = write_report(project, digests)
    steps = [
        lambda: CliRunner().invoke(main, ["reflect", "done", "weekly", "2026-W42", "--report", str(report),
                                          "--tokens", "98000", "--delphi-model", "claude-sonnet-5-5",
                                          "--momus-model", "claude-opus-5-5", "--check-iterations", "2"],
                                   catch_exceptions=False),
        lambda: pq.import_report(project, report, tmp_path / "models"),
        lambda: pq.apply(project, "Q1", tmp_path / "models"),
        lambda: pq.drop(project, "Q2"),
        lambda: assign_arm(project, "sess-x", "ab", seed=1),
    ]
    writes = [True, False, True, True, True]  # import itself logs nothing
    for step, writes_one in zip(steps, writes):
        before = log_bytes(project)
        step()
        after = log_bytes(project)
        assert after.startswith(before)
        assert after.count(b"\n") - before.count(b"\n") == (1 if writes_one else 0)
    raw = explog.log_path(project).read_text(encoding="utf-8")
    assert "zebra" not in raw and "umbrella" not in raw
    records = explog.load(project)
    assert [r["record"] for r in records] == ["run", "resolution", "resolution", "arm"]
    run = records[0]
    assert run["tokens"] == 98000 and run["check_iterations"] == 2 and run["findings"] == {"failed_tool_call": 1}
    assert [p["verdict"] for p in run["proposals"]] == ["consistent", "untested"]
    assert [r["outcome"] for r in records[1:3]] == ["applied", "dropped"]
    lines = explog.summary(records)
    assert any("Applied by target: file 1/2" in line for line in lines)


def test_records_with_free_text_are_refused(project):
    with pytest.raises(explog.LogError):
        explog.append(project, {"record": "run", "level": "weekly", "period": "free text here"})
    with pytest.raises(explog.LogError):
        explog.append(project, {"record": "run", "summary": "x"})
    assert explog.load(project) == []


def test_export_writes_a_copy_and_nothing_else(project, tmp_path):
    assign_arm(project, "s1", "on")
    dest = tmp_path / "out" / "runs.jsonl"
    r = CliRunner().invoke(main, ["reflect", "log", "export", str(dest)], catch_exceptions=False)
    assert r.exit_code == 0
    assert dest.read_bytes() == explog.log_path(project).read_bytes()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["runs.jsonl"]


def test_monthly_done_logs_model_change_counts(project, tmp_path):
    from daedalus.reflection import models as m

    m.aspire("To be plain", "claude-test", "2026-10")
    CliRunner().invoke(main, ["reflect", "done", "monthly", "2026-10"], catch_exceptions=False)
    changes = [r for r in explog.load(project) if r["record"] == "model_changes"]
    assert changes and changes[0]["counts"].get("aspire") == 1
