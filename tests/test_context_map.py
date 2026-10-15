"""The context map (edict 0015, T-c1 and T-c2): exact measuring, attribution, subjects, tasks, the index."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus import context as cmap
from daedalus.context import index as ix
from daedalus.context.index import _size, command_name, path_subject

ROOT = "/work/proj"
T0 = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)


class Transcript:
    """Builds a transcript in the shape Claude Code writes (main thread, usage per request)."""

    def __init__(self, path: Path):
        self.path = path
        self.events = []
        self.n = 0
        self.req = 0
        self.branch = "main"

    def _base(self, kind, minutes=None, **kw):
        self.n += 1
        at = (T0 + timedelta(minutes=self.n if minutes is None else minutes)).isoformat().replace("+00:00", "Z")
        return {"type": kind, "uuid": f"u{self.n}", "timestamp": at, "cwd": ROOT, "sessionId": "s",
                "isSidechain": False, "gitBranch": self._branch(kw.pop("branch", None)), **kw}

    def _branch(self, branch):
        self.branch = branch or self.branch
        return self.branch

    def request(self, context, output=10, blocks=None, events=1, minutes=None):
        """One API request: `events` assistant entries sharing a requestId and usage, with content blocks."""
        self.req += 1
        usage = {"input_tokens": 5, "cache_read_input_tokens": context - 5, "cache_creation_input_tokens": 0,
                 "output_tokens": output}
        blocks = blocks or [{"type": "text", "text": "ok"}]
        for i in range(events):
            part = blocks[i::events] or [{"type": "text", "text": ""}]
            self.events.append(self._base("assistant", minutes, requestId=f"r{self.req}", message={
                "id": f"m{self.req}", "role": "assistant", "model": "claude-test", "usage": usage, "content": part}))
        return self

    def tool_use(self, tid, name, **inp):
        return {"type": "tool_use", "id": tid, "name": name, "input": inp}

    def result(self, tid, content, minutes=None):
        self.events.append(self._base("user", minutes, message={"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": content}]}))
        return self

    def prompt(self, text, minutes=None, **kw):
        self.events.append(self._base("user", minutes, message={"role": "user", "content": text}, **kw))
        return self

    def raw(self, event):
        self.events.append(event)
        return self

    def boundary(self):
        self.events.append(self._base("system", subtype="compact_boundary", compactMetadata={"trigger": "auto"}))
        return self

    def write(self):
        self.path.write_text("".join(json.dumps(e) + "\n" for e in self.events))
        return self.path


def padded(make, target):
    """A block whose serialized size is exactly `target` characters."""
    text = ""
    block = make(text)
    text = "x" * (target - _size(block))
    block = make(text)
    assert _size(block) == target
    return block


def measure(path, **kw):
    return cmap.measure(Path(ROOT), transcript=path, now=kw.pop("now", T0 + timedelta(hours=10)), **kw)


def row(m, key, view="by_subject"):
    return next(r for r in m[view] if r["key"] == key)


# ---------- exact size and attribution ----------


def test_exact_size_with_entries_sharing_a_request(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("hi").request(1000).request(1500, events=3).request(1700)
    m = measure(t.write())
    assert m["used_tokens"] == 1700 and m["exact"] is True
    assert abs(sum(r["tokens"] for r in m["by_subject"]) - 1700) <= len(m["by_subject"])


def test_output_tokens_are_exact_and_the_rest_is_split_by_size(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    t.prompt("start").request(10_000, output=1200,
                              blocks=[t.tool_use("t1", "Bash", command="pytest -q")])
    t.raw(t._base("user", message={"role": "user", "content": [
        padded(lambda s: {"type": "tool_result", "tool_use_id": "t1", "content": s}, 9000)]}))
    msg = t._base("user", message={"role": "user", "content": ""})
    msg["message"]["content"] = "y" * (1000 - _size(""))  # the message's content serializes to 1,000 chars
    t.raw(msg).request(13_200)
    m = measure(t.write())
    assert row(m, "output:output")["tokens"] == 1200
    assert row(m, "command:pytest")["tokens"] == 1800
    assert row(m, "conversation:your messages")["tokens"] == 200


def test_growth_below_output_is_split_by_size_and_marked_estimated(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000, output=500).prompt("b" * 300).request(1100)
    m = measure(t.write())
    assert m["exact"] is False
    assert row(m, "conversation:your messages")["how"] == "estimated"
    assert m["used_tokens"] == 1100


def test_a_shrinking_context_keeps_the_sum_exact(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(5000).request(4000)
    m = measure(t.write())
    assert row(m, "other:cleared by Claude Code")["tokens"] == -1000
    assert sum(r["tokens"] for r in m["by_subject"]) == 4000


def test_the_ratio_is_measured_not_four(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000, output=0)
    for i in range(10):  # 3,000 characters per 1,000 tokens: a ratio of 3
        t.prompt("z" * (3000 - 2)).request(1000 + (i + 1) * 1000, output=0)
    t.prompt("q" * 598)  # after the last request: pending, estimated at the measured ratio
    m = measure(t.write())
    assert m["ratio_chars_per_token"] == pytest.approx(3.0, abs=0.01)
    assert m["pending_tokens"] == 200


# ---------- boundaries and the base ----------


def test_totals_reset_at_a_compaction_and_the_summary_is_found_when_not_adjacent(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("old work").request(1000).request(90_000)
    t.boundary().raw(t._base("attachment", attachment={"type": "hook_success", "content": "x"}))
    t.prompt("This session is being continued...", isCompactSummary=True)
    t.request(20_000).prompt("new").request(21_000)
    m = measure(t.write())
    assert m["used_tokens"] == 21_000 and m["compactions_seen"] == 1
    assert row(m, "base")["tokens"] == 20_000
    assert "compaction summary" in row(m, "base")["breakdown"]
    assert sum(r["tokens"] for r in m["by_subject"]) == 21_000


# ---------- subjects ----------


@pytest.mark.parametrize("command, name", [
    ("cd x && FOO=1 pytest -q", "pytest"), ("a; b | c", "a"), ("for f in *; do echo $f; done", "echo"),
    ("[ -x a ] && make", "make"), ("/usr/bin/git status", "git"), ("cd x", "?"),
])
def test_command_names(command, name):
    assert command_name(command) == name


def test_paths_inside_and_outside_the_project():
    assert path_subject("/work/proj/src/daedalus/context/index.py", ROOT) == ("file", "src/daedalus/")
    assert path_subject("/work/proj/README.md", ROOT) == ("file", "README.md")
    assert path_subject("/tmp/scratch/x.py", ROOT) == ("file", "outside: tmp/scratch")


def test_subagent_reports_count_under_their_type(tmp_path):
    sid = "sess-1"
    t = Transcript(tmp_path / f"{sid}.jsonl")
    t.prompt("review it").request(1000, blocks=[t.tool_use("t1", "Agent", subagent_type="momus", prompt="go")])
    t.result("t1", [{"type": "text", "text": "Async agent launched successfully.\nagentId: abc123 (internal ID)"}])
    t.request(1100)
    t.prompt('<task-notification>\n<task-id>abc123</task-id>\n<status>completed</status>' + "r" * 2000, isMeta=True)
    t.prompt('Another Claude session sent a message:\n<agent-message from="abc123">\n[Subagent hand-back] ' + "s" * 2000,
             isMeta=True)
    t.request(3000)
    meta = tmp_path / sid / "subagents"
    meta.mkdir(parents=True)
    (meta / "agent-abc123.meta.json").write_text(json.dumps({"agentType": "momus"}))
    m = measure(t.write())
    assert row(m, "agent:Agent: momus (launch)")["tokens"] > 0
    assert row(m, "agent:Agent: momus")["tokens"] > row(m, "agent:Agent: momus (launch)")["tokens"]


# ---------- tasks ----------


def test_task_markers_and_branch_changes(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    t.prompt("work on T-a1 please").request(1000)
    t.prompt("more T-a1 work" + "a" * 900).request(2000)
    t.prompt("switching" + "b" * 900, branch="feat/x").request(3000)
    t.request(3100, blocks=[t.tool_use("t9", "Read", file_path="/work/proj/a.py")])
    t.result("t9", "mentions T-z9 in a file" + "c" * 900, minutes=None)
    t.request(4000)
    t.prompt("now T-b2 " + "d" * 900, branch="feat/x").request(5000)
    m = measure(t.write())
    tasks = {r["key"]: r["tokens"] for r in m["by_task"]}
    assert set(tasks) >= {"task:T-a1", "branch:feat/x", "task:T-b2"}
    assert "task:T-z9" not in tasks  # an ID inside a tool result is not a marker


def test_commit_messages_and_gameplan_commands_are_markers_but_heredocs_are_not():
    seg = ix.empty_segment()
    indexer = ix.Indexer(ix.empty_index("x", "h"), {})
    for cmd, task in [("git commit -m \"T-h1: the kit\"", "T-h1"),
                      ("daedalus gameplan -w hooks task status T-c2 done", "T-c2"),
                      ("cat > f <<'EOF'\nT-q7\nEOF", "T-c2")]:
        for mt in ix.MARKER_COMMANDS.finditer(cmd):
            indexer._markers(seg, mt.group(1) or mt.group(2) or "")
        assert seg["task"] == task


# ---------- quiet, incremental, cold ----------


def test_quiet_share(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    t.prompt("a", minutes=0).request(1000, minutes=0)
    t.request(1500, blocks=[t.tool_use("t1", "Bash", command="pytest")], minutes=1).result("t1", "p" * 900, minutes=1)
    t.request(3000, minutes=100).prompt("recent", minutes=100).request(3100, minutes=100)
    m = cmap.measure(Path(ROOT), transcript=t.write(), now=T0 + timedelta(minutes=120), quiet_minutes=60)
    assert row(m, "command:pytest")["quiet"] is True
    assert row(m, "conversation:your messages")["quiet"] is False
    assert m["quiet_tokens"] == sum(r["tokens"] for r in m["by_subject"] if r["quiet"])


def test_the_index_reads_only_new_bytes_and_resets_on_a_rewrite(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    path = t.write()
    data, _ = cmap.refresh(path)
    first = data["offset"]
    assert first == path.stat().st_size
    with open(path, "a") as f:
        t2 = Transcript(tmp_path / "unused")
        t2.n, t2.req = 50, 50
        t2.request(2000)
        f.write("".join(json.dumps(e) + "\n" for e in t2.events))
    data, _ = cmap.refresh(path)
    assert data["offset"] == path.stat().st_size and data["segment"]["last_ctx"] == 2000
    Transcript(path).prompt("rewritten").request(700).write()
    data, _ = cmap.refresh(path)
    assert data["segment"]["last_ctx"] == 700  # a changed first line resets the index


def test_a_half_written_last_line_waits(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    path = t.write()
    with open(path, "a") as f:
        f.write('{"type": "user", "uuid": "partial"')
    data, _ = cmap.refresh(path)
    assert data["offset"] < path.stat().st_size


def test_a_cold_start_catches_up_in_slices(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    for i in range(30):
        t.prompt("p" * 1000).request(1000 * (i + 1))
    path = t.write()
    slices, caught_up = 0, False
    while not caught_up:
        _, caught_up = cmap.refresh(path, max_bytes=path.stat().st_size // 3 + 1)
        slices += 1
    assert slices == 3
    assert cmap.load_index("s")["segment"]["last_ctx"] == 30_000


# ---------- the library and the CLI ----------


def test_keys_are_stable_as_the_transcript_grows(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000, blocks=[t_use := {
        "type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest"}}]).result("t1", "x" * 500)
    t.request(2000)
    keys1 = {r["key"] for r in measure(t.write())["by_subject"]}
    t.prompt("more").request(2500)
    keys2 = {r["key"] for r in measure(t.write())["by_subject"]}
    assert keys1 <= keys2 and "command:pytest" in keys1 and t_use["id"] == "t1"


def test_measure_has_the_shape_the_tui_reads(tmp_path):
    m = measure(Transcript(tmp_path / "s.jsonl").prompt("a").request(1000).prompt("b").request(1200).write())
    assert {"session_id", "measured_at", "window_tokens", "used_tokens", "measured", "by_subject", "by_task",
            "plan", "pins"} <= set(m)
    for r in m["by_subject"]:
        assert {"key", "subject", "kind", "tokens", "share", "quiet", "last_touched"} <= set(r)
        assert 0 <= r["share"] <= 1 or r["tokens"] < 0


def test_cli_prints_the_map_and_json(tmp_path, monkeypatch):
    from daedalus.cli.main import main

    path = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000).prompt("b").request(1200).write()
    monkeypatch.setattr(cmap, "find_transcript", lambda project_dir, session_id=None: path)
    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(main, ["context"]).output
    assert "Context: 1,200 tokens (exact)" in out
    data = json.loads(CliRunner().invoke(main, ["context", "--json"]).output)
    assert data["used_tokens"] == 1200
    assert "base (before any task" in CliRunner().invoke(main, ["context", "--by", "task"]).output
