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


@pytest.mark.parametrize("command, texts", [
    ('git commit -m "T-h1: the kit"', ["T-h1: the kit"]),
    ("git commit -q -F - <<'EOF'\nT-c2: views\n\nbody\nEOF", ["T-c2: views\n\nbody"]),
    ('git commit -am "T-a3 fix"', ["T-a3 fix"]),
    ('git commit -m "first" -m "T-b4 second"', ["first", "T-b4 second"]),
    ('git commit -m "say \\"T-x9\\" there"', ['say "T-x9" there']),
    ("daedalus gameplan -w hooks task status T-c2 done", ["T-c2"]),
    ("daedalus gameplan --workstream hooks task status T-c3 done", ["T-c3"]),
    ("daedalus gameplan --workstream=hooks task status T-c4 done", ["T-c4"]),
    ('git commit --message="T-c5 x"', ["T-c5 x"]),
    ("git commit -m \"$(cat <<'EOF'\nT-e22: fix\nEOF\n)\"", ["T-e22: fix"]),
    ("cd x && git commit -m \"$(cat <<'EOF'\nT-e22: say \"hi\"\nEOF\n)\"", ['T-e22: say "hi"']),
    ("cat <<'A'\nT-e99\nA\ngit commit -F - <<'B'\nT-e22\nB", ["T-e22"]),
    ('git -C sub commit -m "T-g1"', ["T-g1"]),
    ("git commit -mT-g2", ["T-g2"]),
    ("if true; then git commit -qm 'T-g3'; fi", ["T-g3"]),
    ("git commit -aF - <<'E'\nT-g4 all\nE", ["T-g4 all"]),
    ('n=$((1+1)); git commit -m "T-g5"', ["T-g5"]),
    ("git status # it's fine\ngit commit -m 'T-g6'", ["T-g6"]),
    ('git log -m "T-g7"', []),
    ("cat > f <<'EOF'\nT-q7\nEOF", []),
    ("echo 'git commit -m T-z1'", []),
])
def test_marker_texts(command, texts):
    assert ix.marker_texts(command) == texts


def test_the_latest_id_in_a_message_wins_and_a_task_survives_a_compaction(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    t.prompt("from T-a1 to T-b2 " + "x" * 600).request(1000).request(2000)
    t.boundary().prompt("summary", isCompactSummary=True).request(3000).prompt("go on " + "y" * 600).request(4000)
    m = measure(t.write())
    assert row(m, "task:T-b2", "by_task")["tokens"] > 0
    assert "task:T-a1" not in {r["key"] for r in m["by_task"]}


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


# ---------- Momus's review of the first version (trial 2026-10-15-context-measure.md) ----------


def test_d1_an_api_error_entry_is_not_a_request(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(10_000).prompt("b" * 900).request(11_000)
    err = t._base("assistant", requestId=None, isApiErrorMessage=True, message={
        "id": "e1", "role": "assistant", "model": "<synthetic>", "content": [{"type": "text", "text": "API Error"}],
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
    t.raw(err).prompt("c" * 900).request(12_000)
    m = measure(t.write())
    assert m["exact"] is True and m["model"] == "claude-test"
    assert "other:cleared by Claude Code" not in {r["key"] for r in m["by_subject"]}
    assert sum(r["tokens"] for r in m["by_subject"]) == 12_000


def test_d3_a_compaction_bigger_than_the_default_window_raises_the_guess(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(150_000)
    t.events.append(t._base("system", subtype="compact_boundary", compactMetadata={"trigger": "auto", "preTokens": 582_761}))
    t.prompt("summary", isCompactSummary=True).request(145_000)
    m = measure(t.write())
    assert m["window_tokens"] == cmap.LARGE_WINDOW and m["window_known"] is False


def test_a_background_command_notice_belongs_to_its_command(tmp_path):
    t = Transcript(tmp_path / "s.jsonl")
    t.prompt("a").request(1000, blocks=[t.tool_use("toolu_b1", "Bash", command="pytest -q", run_in_background=True)])
    t.result("toolu_b1", "Command running in background with ID: b77")
    t.request(1100)
    t.prompt("<task-notification>\n<task-id>b77</task-id>\n<tool-use-id>toolu_b1</tool-use-id>\n<status>completed</status>"
             + "z" * 3000, isMeta=True)
    t.request(3000)
    m = measure(t.write())
    keys = {r["key"] for r in m["by_subject"]}
    assert "agent:Agent: agent" not in keys and row(m, "command:pytest")["tokens"] > 900


def test_sidechain_entries_count_for_nothing(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    side = t._base("assistant", requestId="side", isSidechain=True, message={
        "id": "sm", "role": "assistant", "model": "claude-test", "content": [],
        "usage": {"input_tokens": 90_000, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}})
    t.raw(side).prompt("b").request(1200)
    m = measure(t.write())
    assert m["used_tokens"] == 1200 and "other:cleared by Claude Code" not in {r["key"] for r in m["by_subject"]}


def test_meta_reminders_are_not_your_messages(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    t.prompt("<system-reminder>" + "r" * 900, isMeta=True).request(1500)
    m = measure(t.write())
    assert row(m, "other:reminders and attachments")["tokens"] > 400
    assert "conversation:your messages" not in {r["key"] for r in m["by_subject"]}


def test_a_new_first_line_resets_even_when_the_file_grew(tmp_path):
    path = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000).write()
    cmap.refresh(path)
    Transcript(path).prompt("different start " + "q" * 2000).request(5000).request(7000).write()
    data = cmap.refresh(path)[0]
    assert data["segment"]["last_ctx"] == 7000 and data["segment"]["base"] == 5000  # rebuilt from the top


def test_a_shrunk_transcript_with_the_same_first_line_resets(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    for i in range(5):
        t.prompt("p").request(2000 + i)
    path = t.write()
    cmap.refresh(path)
    lines = path.read_text().splitlines(keepends=True)
    path.write_text("".join(lines[:2]))
    assert cmap.refresh(path)[0]["segment"]["last_ctx"] == 1000


def test_a_complete_line_without_its_newline_waits_and_is_read_once(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000)
    path = t.write()
    t2 = Transcript(tmp_path / "x")
    t2.n, t2.req = 40, 40
    t2.request(2500)
    line = json.dumps(t2.events[0])
    with open(path, "a") as f:
        f.write(line)  # valid JSON, no newline yet
    data, _ = cmap.refresh(path)
    assert data["segment"]["last_ctx"] == 1000
    with open(path, "a") as f:
        f.write("\n")
    data, _ = cmap.refresh(path)
    assert data["segment"]["last_ctx"] == 2500 and data["offset"] == path.stat().st_size


@pytest.mark.parametrize("command, name", [
    ("T=$(mktemp -d) && cd $T && make", "make"), ("(cd x && pytest)", "pytest"), ("D() { ls; }; D", "ls"),
])
def test_more_command_names(command, name):
    assert command_name(command) == name


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


def test_a_synthetic_model_alone_marks_an_entry_as_no_request(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(10_000).prompt("b" * 900).request(11_000)
    t.raw(t._base("assistant", message={"id": "e2", "role": "assistant", "model": "<synthetic>", "content": [],
                                         "usage": {"input_tokens": 0, "output_tokens": 0}}))
    t.prompt("c" * 900).request(12_000)
    m = measure(t.write())
    assert m["exact"] is True and "other:cleared by Claude Code" not in {r["key"] for r in m["by_subject"]}


def test_an_earlier_request_bigger_than_the_default_window_raises_the_guess(tmp_path):
    t = Transcript(tmp_path / "s.jsonl").prompt("a").request(300_000)
    t.events.append(t._base("system", subtype="compact_boundary", compactMetadata={"trigger": "manual"}))
    t.prompt("summary", isCompactSummary=True).request(50_000)
    assert measure(t.write())["window_tokens"] == cmap.LARGE_WINDOW


def test_an_index_from_an_older_version_is_rebuilt(tmp_path):
    path = Transcript(tmp_path / "s.jsonl").prompt("a").request(1000).prompt("b").request(1500).write()
    stale, _ = cmap.refresh(path)
    stale["version"] = ix.INDEX_VERSION - 1
    stale["segment"]["last_ctx"] = 99
    cmap.save_index("s", stale)
    assert cmap.refresh(path)[0]["segment"]["last_ctx"] == 1500
