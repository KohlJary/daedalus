"""Digests (edict 0010): counts from real transcripts, citations, idempotency, project mapping."""

import json
import os
from pathlib import Path

import pytest

from daedalus.reflection import digest as dg
from daedalus.reflection.paths import norm_path, owner_project

from reflection_helpers import (
    FIXTURES, INTERRUPT_SESSION, REAL_SESSION, Builder, claude_home, install_fixtures, make_project,
    write_session,
)

pytestmark = pytest.mark.reflection


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- the real fixtures, against counts made by hand ----------


def test_real_session_counts_match_the_hand_count():
    d = dg.build_digest(FIXTURES / f"{REAL_SESSION}.jsonl")
    # By hand (jq over the fixture): 10 tool results with is_error, 2 of them classifier denials
    assert d["counts"]["failures"] == 8
    assert d["counts"]["denied_by_classifier"] == 2
    assert d["counts"]["rejected_by_user"] == 0
    assert d["counts"]["interruptions"] == 0
    assert d["tool_calls"] == 14
    assert d["tools"]["Bash"] == {"calls": 11, "failures": 7}
    assert d["tools"]["Write"] == {"calls": 1, "failures": 1}  # "File has not been read yet"
    assert d["tokens"] == {"input": 38, "output": 21928, "cache_read": 4515881, "cache_creation": 35763,
                           "messages": 17}
    assert d["models"] == ["claude-opus-5-5"]
    assert d["claude_code_versions"] == ["2.1.296"]


def test_interrupt_session_counts_match_the_hand_count():
    d = dg.build_digest(FIXTURES / f"{INTERRUPT_SESSION}.jsonl")
    assert d["counts"]["rejected_by_user"] == 1       # the Write the user declined
    assert d["counts"]["interruptions"] == 1          # Esc while numbers were streaming
    assert d["counts"]["interruptions_before_reply"] == 2  # Esc before the reply began: no marker
    assert d["counts"]["failures"] == 0               # a rejection is not a tool failure
    assert d["labels"]["interruptions_before_reply"] == "inferred"
    assert d["labels"]["interruptions"] == "shown"


def test_citations_are_the_fixtures_event_uuids():
    path = FIXTURES / f"{REAL_SESSION}.jsonl"
    d = dg.build_digest(path)
    expected_failures, expected_denials = [], []
    for ev in _events(path):
        if ev.get("type") != "user" or not isinstance((ev.get("message") or {}).get("content"), list):
            continue
        for block in ev["message"]["content"]:
            if block.get("type") == "tool_result" and block.get("is_error") is True:
                text = block.get("content") if isinstance(block.get("content"), str) else json.dumps(block.get("content"))
                (expected_denials if "auto mode classifier" in text else expected_failures).append(ev["uuid"])
    assert d["events"]["failures"] == expected_failures
    assert d["events"]["denied_by_classifier"] == expected_denials

    interrupts = _events(FIXTURES / f"{INTERRUPT_SESSION}.jsonl")
    d2 = dg.build_digest(FIXTURES / f"{INTERRUPT_SESSION}.jsonl")
    marker = [e["uuid"] for e in interrupts if e.get("type") == "user"
              and (e.get("message") or {}).get("content") == [{"type": "text", "text": "[Request interrupted by user]"}]]
    assert d2["events"]["interruptions"] == marker


def test_a_message_split_across_events_is_counted_once():
    path = FIXTURES / f"{REAL_SESSION}.jsonl"
    events = [e for e in _events(path) if e.get("type") == "assistant" and (e.get("message") or {}).get("usage")]
    per_event = sum(e["message"]["usage"]["output_tokens"] for e in events)
    ids = [e["message"]["id"] for e in events]
    assert len(ids) > len(set(ids)), "the fixture has a message written as several events"
    d = dg.build_digest(path)
    assert d["tokens"]["messages"] == len(set(ids))
    assert d["tokens"]["output"] < per_event  # summing per event would overcount


def test_unknown_event_types_and_missing_usage_are_counted_not_fatal():
    d = dg.build_digest(FIXTURES / f"{REAL_SESSION}.jsonl")
    assert d["skipped"]["unknown_types"] == {"synthetic-unknown-type": 1}
    assert d["skipped"]["missing_usage"] == 1


def test_subagent_transcripts_are_included():
    d = dg.build_digest(FIXTURES / f"{REAL_SESSION}.jsonl")
    assert d["subagents"]["count"] == 1
    sub = d["subagents"]["list"][0]
    assert sub["agent_type"] == "momus"
    assert sub["tool_calls"] == 5
    assert sub["tokens"]["messages"] == 4


def test_background_agent_totals_come_from_their_completion_notices(tmp_path):
    b = Builder(str(tmp_path))
    b.prompt()
    b.raw({"type": "attachment", "uuid": "att-1", "sessionId": b.session_id, "timestamp": b.start,
           "attachment": {"type": "queued_command", "prompt": "<task-notification>\n<task-id>a1</task-id>",
                          "usage": {"totalTokens": 45000, "toolUses": 9}}})
    b.raw({"type": "attachment", "uuid": "att-2", "sessionId": b.session_id, "timestamp": b.start,
           "attachment": {"type": "queued_command", "prompt": "<task-notification>\n<task-id>a1</task-id>",
                          "usage": {"totalTokens": 45000, "toolUses": 9}}})
    b.prompt("<task-notification>\n<task-id>a2</task-id>\n<usage><subagent_tokens>51000</subagent_tokens></usage>")
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    assert d["subagents"]["reported_by_agent"] == {"a1": 45000, "a2": 51000}
    assert d["subagents"]["reported_tokens"] == 96000
    assert d["prompts"] == 1  # notifications are not prompts


# ---------- heuristics, on synthetic events ----------


def test_retry_rereads_and_marker_text_inside_a_prompt(tmp_path):
    b = Builder(str(tmp_path))
    b.prompt("please quote [Request interrupted by user] in a sentence")  # not a marker
    b.call("Bash", "t1", command="pytest -q")
    b.result("t1", "Exit code 1\nfailed", is_error=True)
    retry = b.call("Bash", "t2", command="pytest -q")
    b.result("t2", "ok")
    b.call("Read", "t3", file_path="/x/a.py")
    b.result("t3", "...")
    reread = b.call("Read", "t4", file_path="/x/a.py")
    b.result("t4", "...")
    b.call("Edit", "t5", file_path="/x/a.py")
    b.result("t5", "ok")
    b.call("Read", "t6", file_path="/x/a.py")  # after an edit: not a re-read
    b.result("t6", "...")
    b.call("Bash", "t7", command="ls")
    b.result("t7", "Exit code 2", is_error=True)
    b.call("Bash", "t8", command="ls -la")  # a different command: not a retry
    b.result("t8", "ok")
    b.reply()
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    assert d["events"]["retries"] == [retry]
    assert d["events"]["re_reads"] == [reread]
    assert d["counts"]["failures"] == 2
    assert d["counts"]["interruptions"] == 0


# ---------- writing digests: idempotency, mapping ----------


def test_digest_twice_writes_nothing_and_growth_redigests(tmp_path):
    project = make_project(tmp_path / "proj")
    folder = install_fixtures(project)
    first = dg.digest_project(project)
    assert sorted(first["written"]) == sorted([REAL_SESSION, INTERRUPT_SESSION])
    second = dg.digest_project(project)
    assert second["written"] == []
    # Appending to only a subagent transcript re-digests its session
    sub = next((folder / REAL_SESSION / "subagents").glob("*.jsonl"))
    with open(sub, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "late-sub-event", "isSidechain": True,
                            "message": {"role": "user", "content": "x"}}) + "\n")
    assert dg.digest_project(project)["written"] == [REAL_SESSION]
    # Appending to the session transcript does too
    with open(folder / f"{INTERRUPT_SESSION}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "late-event", "cwd": str(project),
                            "message": {"role": "user", "content": "more"}}) + "\n")
    assert dg.digest_project(project)["written"] == [INTERRUPT_SESSION]


def test_notes_survive_a_redigest(tmp_path):
    project = make_project(tmp_path / "proj")
    folder = install_fixtures(project)
    dg.digest_project(project)
    dg.set_notes(project, INTERRUPT_SESSION, "Waited on a backgrounded sleep.")
    with open(folder / f"{INTERRUPT_SESSION}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "late", "message": {"role": "user", "content": "x"}}) + "\n")
    dg.digest_project(project)
    saved = json.loads(dg.digest_path(project, INTERRUPT_SESSION).read_text(encoding="utf-8"))
    assert saved["notes"] == "Waited on a backgrounded sleep."


def test_mapping_by_cwd_with_a_hyphen_and_a_dot(tmp_path):
    project = make_project(tmp_path / "my-proj.v2")
    sibling = make_project(tmp_path / "my-proj")
    nested = make_project(project / "sub-repo")
    # Claude Code would encode both project and sibling's paths into look-alike folder names
    folder = claude_home() / "projects" / "-tmp-my-proj-v2"
    a = Builder(str(project), "s-project")
    a.prompt()
    write_session(folder, "s-project", a.events)
    b = Builder(str(sibling), "s-sibling")
    b.prompt()
    write_session(folder, "s-sibling", b.events)
    c = Builder(str(nested / "src"), "s-nested")  # started in a subdirectory of the nested repo
    (nested / "src").mkdir()
    c.prompt()
    write_session(claude_home() / "projects" / "other", "s-nested", c.events)
    assert [f.stem for f in dg.sessions_for_project(project)] == ["s-project"]
    assert [f.stem for f in dg.sessions_for_project(sibling)] == ["s-sibling"]
    assert [f.stem for f in dg.sessions_for_project(nested)] == ["s-nested"]


def test_windows_paths_normalise_by_case_and_separator():
    assert norm_path(r"C:\Users\Kohl\Repo", windows=True) == norm_path("c:/users/kohl/repo", windows=True)
    assert norm_path(r"C:\Users\Kohl\Repo\.", windows=True) == norm_path(r"c:\USERS\kohl\repo", windows=True)
    assert norm_path("/home/a/../b", windows=False) == "/home/b"


@pytest.mark.skipif(os.name != "nt", reason="drive letters exist only on Windows")
def test_windows_drive_letter_case_maps_to_the_project(tmp_path):
    project = make_project(tmp_path / "Proj")
    drive, rest = os.path.splitdrive(str(project))
    other_case = (drive.lower() if drive.isupper() else drive.upper()) + rest.upper()
    a = Builder(other_case, "s-win")
    a.prompt()
    write_session(claude_home() / "projects" / "C--proj", "s-win", a.events)
    assert [f.stem for f in dg.sessions_for_project(project)] == ["s-win"]
    assert owner_project(other_case) == norm_path(str(project.resolve()))


def test_claude_config_dir_is_where_transcripts_are_read(tmp_path, monkeypatch):
    project = make_project(tmp_path / "proj")
    elsewhere = tmp_path / "custom-claude"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    a = Builder(str(project), "s-custom")
    a.prompt()
    write_session(elsewhere / "projects" / "x", "s-custom", a.events)
    assert [f.stem for f in dg.sessions_for_project(project)] == ["s-custom"]
