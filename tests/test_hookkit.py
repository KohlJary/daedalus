"""The hook kit (edict 0016, T-h1): a light dispatcher per event, registration, state, the budget, failing soft."""

import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from daedalus import hooks
from daedalus.config import HooksConfig
from daedalus_hookkit import cli, core, paths, settings as kit_settings, state as kit_state
from daedalus_hookkit.core import Feature, Line, dispatch

SRC = Path(__file__).resolve().parents[1] / "src"


def project(tmp_path):
    (tmp_path / ".daedalus").mkdir(parents=True, exist_ok=True)
    return tmp_path


def feat(name, events, run, key="session_start", gate=False):
    return Feature(name, frozenset(events), key, run, gate=gate)


def payload(p, **kw):
    return {"session_id": "s1", "cwd": str(p), **kw}


# ---------- the kit is light ----------


def test_importing_the_kit_imports_no_daedalus_click_or_cli():
    code = ("import sys, daedalus_hookkit, daedalus_hookkit.core, daedalus_hookkit.cli, daedalus_hookkit.features;"
            "bad=[m for m in sys.modules if m=='daedalus' or m.startswith('daedalus.') or m=='click' or m=='platformdirs'];"
            "print(bad)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(SRC)}, check=True).stdout.strip()
    assert out == "[]"


def _median_ms(cmd, stdin, env, runs=20):
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env, check=True)
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def test_no_feature_event_runs_in_40ms(tmp_path):
    p = project(tmp_path)
    env = {**os.environ, "PYTHONPATH": str(SRC), "XDG_CACHE_HOME": str(tmp_path / "c"), "XDG_CONFIG_HOME": str(tmp_path / "g")}
    base = _median_ms([sys.executable, "-c", "pass"], "", env, runs=10)
    if base > 30:
        pytest.skip(f"slow runner: a bare interpreter takes {base:.0f} ms here")
    stdin = json.dumps(payload(p, hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "x"}))
    cmd = [sys.executable, "-m", "daedalus_hookkit", "PostToolUse"]
    _median_ms(cmd, stdin, env, runs=2)  # warm
    ms = _median_ms(cmd, stdin, env)
    assert ms <= 40, f"median {ms:.1f} ms (bare interpreter {base:.1f} ms)"


# ---------- settings and paths agree with daedalus.config ----------


def test_kit_defaults_match_the_config_dataclass():
    assert kit_settings.DEFAULTS["hooks"] == asdict(HooksConfig())


def test_kit_paths_match_platformdirs(monkeypatch):
    import importlib
    import platformdirs

    importlib.reload(paths)  # the conftest replaced the functions; check the real ones
    try:
        assert paths.config_dir() == Path(platformdirs.user_config_dir("daedalus"))
        assert paths.cache_dir() == Path(platformdirs.user_cache_dir("daedalus"))
    finally:
        importlib.reload(paths)


def test_project_overrides_global_and_mistyped_values_fall_back(tmp_path):
    p = project(tmp_path)
    paths.config_dir().mkdir(parents=True, exist_ok=True)
    (paths.config_dir() / "config.json").write_text(json.dumps({"hooks": {"budget_per_hour": 3, "board": False}}))
    (p / ".daedalus/config.json").write_text(json.dumps({"hooks": {"budget_per_hour": 9, "capture": "yes"}}))
    s = kit_settings.Settings(p)
    assert s.get("hooks", "budget_per_hour") == 9
    assert s.enabled("board") is False
    assert s.enabled("capture") is False  # "yes" isn't a bool: the default stands


# ---------- output channels ----------


def test_silent_events_print_nothing_but_update_state(tmp_path):
    p = project(tmp_path)

    def run(ctx):
        ctx.touch()["seen"] = ctx.event
        return [Line("would continue the turn", nudge="x:y")]

    for event in ("Stop", "PreCompact", "SessionEnd", "SubagentStop"):
        f = feat("x", [event], run)
        assert dispatch(event, payload(p), [f]) == ""
        assert kit_state.load("s1")["seen"] == event


def test_post_tool_use_uses_additional_context_and_prompt_events_plain_stdout(tmp_path):
    p = project(tmp_path)
    f = feat("x", ["PostToolUse", "UserPromptSubmit", "SessionStart"], lambda ctx: [Line("hello", kind="notice")])
    out = json.loads(dispatch("PostToolUse", payload(p), [f]))
    assert out == {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "hello"}}
    assert dispatch("UserPromptSubmit", payload(p), [f]) == "hello"
    assert dispatch("SessionStart", payload(p), [f]) == "hello"


def test_pre_tool_use_gate_denies_with_reason(tmp_path):
    p = project(tmp_path)
    f = feat("gate", ["PreToolUse"], lambda ctx: [Line("no trial", kind="gate", decision="deny")], gate=True)
    out = json.loads(dispatch("PreToolUse", payload(p), [f]))["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and out["permissionDecisionReason"] == "no trial"


def test_long_lines_are_cut(tmp_path):
    p = project(tmp_path)
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line("a" * 500, kind="notice")])
    assert len(dispatch("UserPromptSubmit", payload(p), [f])) == core.MAX_LINE


# ---------- fail soft, no-op ----------


def test_a_failing_feature_is_dropped_and_the_others_still_print(tmp_path):
    p = project(tmp_path)

    def boom(ctx):
        raise RuntimeError("x")

    fs = [feat("a", ["UserPromptSubmit"], boom), feat("b", ["UserPromptSubmit"], lambda ctx: [Line("ok", kind="notice")])]
    assert dispatch("UserPromptSubmit", payload(p), fs) == "ok"


def test_a_failing_gate_allows_the_call_visibly_and_counts(tmp_path):
    p = project(tmp_path)

    def boom(ctx):
        raise TimeoutError("gh hung")

    out = json.loads(dispatch("PreToolUse", payload(p), [feat("momus gate", ["PreToolUse"], boom, gate=True)]))
    out = out["hookSpecificOutput"]
    assert "permissionDecision" not in out
    assert "didn't run" in out["additionalContext"] and "gh hung" in out["additionalContext"]
    assert kit_state.load("s1")["gate"]["allowed_by_error"] == 1


def test_no_daedalus_dir_means_nothing_happens(tmp_path):
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line("hi", kind="notice")])
    assert dispatch("UserPromptSubmit", payload(tmp_path), [f]) == ""
    assert not kit_state.state_path("s1").exists()


def test_main_survives_garbage_and_exceptions(tmp_path, monkeypatch, capsys):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
    assert cli.main(["UserPromptSubmit"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload(project(tmp_path)))))
    monkeypatch.setattr(core, "dispatch", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
    assert cli.main(["UserPromptSubmit"]) == 0
    assert capsys.readouterr().out == ""


def test_console_entry_exits_zero(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(SRC), "XDG_CACHE_HOME": str(tmp_path / "c")}
    r = subprocess.run([sys.executable, "-m", "daedalus_hookkit", "UserPromptSubmit"], input="garbage",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout == ""


def test_project_dir_comes_from_claude_project_dir(tmp_path, monkeypatch):
    p = project(tmp_path / "proj")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(p))
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line(str(ctx.project_dir), kind="notice")])
    assert dispatch("UserPromptSubmit", payload(elsewhere), [f]) == str(p)


# ---------- the noise budget ----------


def test_budget_drops_the_seventh_nudge_in_an_hour_and_logs_it(tmp_path):
    p = project(tmp_path)
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line("nudge", nudge="x:n", tool="agent:momus")])
    t0 = 1_000_000.0
    outs = [dispatch("UserPromptSubmit", payload(p), [f], now=t0 + i * 60) for i in range(7)]
    assert outs[:6] == ["nudge"] * 6 and outs[6] == ""
    st = kit_state.load("s1")
    assert [e.get("dropped", False) for e in st["events"]] == [False] * 6 + [True]
    assert st["events"][0] | {} == {"at": t0, "hook": "x", "event": "UserPromptSubmit", "nudge": "x:n",
                                    "followed": None, "tool": "agent:momus", "counted": True, "seq": 0}
    assert st["budget"] == {"per_hour": 6, "used": 6}
    assert dispatch("UserPromptSubmit", payload(p), [f], now=t0 + 3700) == "nudge"  # the hour has passed


def test_one_nudge_per_call_and_gates_and_briefs_are_not_counted(tmp_path):
    p = project(tmp_path)
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line("one", nudge="x:a"), Line("two", nudge="x:b"),
                                                      Line("brief", kind="brief")])
    assert dispatch("UserPromptSubmit", payload(p), [f]) == "one\nbrief"
    st = kit_state.load("s1")
    assert st["budget"]["used"] == 1 and st["events"][1]["dropped"] is True


def test_feature_switch_comes_from_its_hooks_key(tmp_path):
    p = project(tmp_path)
    (p / ".daedalus/config.json").write_text(json.dumps({"hooks": {"board": False}}))
    f = feat("x", ["UserPromptSubmit"], lambda ctx: [Line("hi", kind="notice")], key="board")
    assert dispatch("UserPromptSubmit", payload(p), [f]) == ""


# ---------- state ----------


def test_state_is_written_atomically_and_pruned(tmp_path):
    st = kit_state.empty("abc", 1.0)
    kit_state.save(st)
    path = kit_state.state_path("abc")
    assert json.loads(path.read_text())["session_id"] == "abc"
    assert not [x for x in path.parent.iterdir() if x.name.startswith(".tmp-")]
    old = time.time() - 8 * 86400
    os.utime(path, (old, old))
    kit_state.prune()
    assert not path.exists()


def test_state_survives_a_corrupt_file(tmp_path):
    kit_state.state_dir().mkdir(parents=True)
    kit_state.state_path("s1").write_text("[1, 2")
    assert kit_state.load("s1")["events"] == []


def test_session_ids_cannot_escape_the_state_dir():
    assert kit_state.state_path("../../etc/passwd").parent == kit_state.state_dir()


# ---------- the real features ----------


def test_session_start_dispatcher_prints_the_brief(tmp_path):
    p = project(tmp_path)
    (p / ".daedalus/session-summaries.md").write_text("## 2026-10-15: a note\nDid things.\n")
    hooks.session_start_brief(p)  # the first brief's board check creates .daedalus/board, which doctor then sees
    out = dispatch("SessionStart", payload(p, source="startup"))
    assert out and out == hooks.session_start_brief(p)


def test_capture_runs_on_session_end_silently(tmp_path, monkeypatch):
    p = project(tmp_path)
    (p / ".daedalus/config.json").write_text(json.dumps({"hooks": {"capture": True}}))
    called = []
    monkeypatch.setattr(hooks, "capture", lambda d: called.append(Path(d)) or "Daedalus: proposed ...")
    assert dispatch("SessionEnd", payload(p)) == ""
    assert called == [p]


# ---------- registration ----------


def kit_commands(p):
    s = json.loads((p / ".claude/settings.json").read_text())
    return {e: [h["command"] for g in groups for h in g["hooks"]] for e, groups in s.get("hooks", {}).items()}


def test_kit_registration_is_idempotent_and_follows_config(tmp_path):
    added, removed, err = hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": True}, kit=True)
    assert err is None and removed == []
    assert kit_commands(tmp_path) == {"SessionStart": ["daedalus-hook SessionStart"],
                                      "UserPromptSubmit": ["daedalus-hook UserPromptSubmit"]}
    assert hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": True}, kit=True) == ([], [], None)
    hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": True, "capture": True}, kit=True)
    assert kit_commands(tmp_path)["PreCompact"] == ["daedalus-hook PreCompact"]
    _, removed, _ = hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": False}, kit=True)
    assert sorted(removed) == ["PreCompact", "SessionEnd", "UserPromptSubmit"]


def test_kit_replaces_the_older_commands_and_keeps_others(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude/settings.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
    hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": True}, kit=False)
    assert "daedalus hook board" in kit_commands(tmp_path)["UserPromptSubmit"]
    added, removed, _ = hooks.register_hooks(tmp_path, enabled={"session_start": True, "board": True}, kit=True)
    assert "UserPromptSubmit: daedalus hook board" in removed or "UserPromptSubmit" in removed
    assert kit_commands(tmp_path) == {"SessionStart": ["daedalus-hook SessionStart"],
                                      "UserPromptSubmit": ["echo mine", "daedalus-hook UserPromptSubmit"]}


def test_without_the_kit_installed_the_older_commands_are_kept(tmp_path):
    hooks.register_hooks(tmp_path, enabled={"session_start": True}, kit=True)
    hooks.register_hooks(tmp_path, enabled={"session_start": True})  # conftest: kit not installed
    assert kit_commands(tmp_path) == {"SessionStart": ["daedalus hook session-start"]}


# ---------- efficacy (T-h2) ----------


from daedalus import hookstate  # noqa: E402
from daedalus_hookkit.features import efficacy  # noqa: E402


def nudger(spec):
    return feat("x", ["UserPromptSubmit"], lambda ctx: [Line("try it", nudge="x:try", tool=spec)])


def tool_call(p, name, now, **inp):
    eff = Feature("efficacy", frozenset({"PostToolUse", "UserPromptSubmit"}), "", efficacy.run)
    return dispatch("PostToolUse", payload(p, tool_name=name, tool_input=inp), [eff], now=now)


def test_a_nudge_followed_within_the_window_and_one_ignored(tmp_path):
    p = project(tmp_path)
    dispatch("UserPromptSubmit", payload(p), [nudger("agent:momus")], now=1000)
    tool_call(p, "Read", 1001, file_path="x")
    tool_call(p, "Agent", 1002, subagent_type="momus", prompt="review")
    e = kit_state.load("s1")["events"][0]
    assert e["followed"] is True and e["followed_after"] == 2

    dispatch("UserPromptSubmit", payload(p), [nudger("skill:exhale")], now=5000)
    for i in range(20):
        tool_call(p, "Read", 5001 + i, file_path=str(i))
    st = kit_state.load("s1")
    assert st["events"][1]["followed"] is False
    summary = hookstate.summarize(st)["nudges"]["x:try"]
    assert summary == {"shown": 2, "followed": 1, "ignored": 1, "pending": 0, "dropped": 0, "tool": "agent:momus"}


@pytest.mark.parametrize("spec, name, inp, prompt, hit", [
    ("skill:exhale", "Skill", {"skill": "daedalus:exhale"}, "", True),
    ("skill:exhale", "", {}, "/exhale now", True),
    ("skill:exhale", "", {}, "please exhale", False),
    ("bash:daedalus gameplan pending", "Bash", {"command": "cd x && daedalus gameplan pending"}, "", True),
    ("agent:general-purpose", "Agent", {}, "", True),
    ("tool:Read", "Read", {}, "", True),
    ("agent:momus", "Agent", {"subagent_type": "theseus"}, "", False),
])
def test_what_counts_as_following_a_nudge(spec, name, inp, prompt, hit):
    assert efficacy._matches(spec, name, inp, prompt) is hit


def test_efficacy_writes_nothing_while_no_nudge_is_pending(tmp_path):
    p = project(tmp_path)
    tool_call(p, "Read", 1, file_path="x")
    assert not kit_state.state_path("s1").exists()


def test_the_call_that_prompted_a_nudge_does_not_follow_it(tmp_path):
    p = project(tmp_path)
    eff = Feature("efficacy", frozenset({"PostToolUse"}), "", efficacy.run)
    gate_nudge = feat("x", ["PostToolUse"], lambda ctx: [Line("run momus", nudge="x:m", tool="tool:Bash")])
    dispatch("PostToolUse", payload(p, tool_name="Bash", tool_input={"command": "gh pr create"}), [eff, gate_nudge])
    assert kit_state.load("s1")["events"][0]["followed"] is None


def test_hookstate_load_returns_the_shared_shape(tmp_path):
    st = hookstate.load(tmp_path, "nothing-yet")
    assert set(st) >= {"session_id", "events", "gate", "budget"}
    assert hookstate.state_path("abc") == kit_state.state_path("abc")


def test_digest_counts_agents_skills_and_hook_efficacy(tmp_path):
    from daedalus.reflection.digest import build_digest

    sid = "11111111-2222-3333-4444-555555555555"
    lines = []
    for i, (tool, inp) in enumerate([("Agent", {"subagent_type": "momus"}), ("Agent", {}),
                                     ("Skill", {"skill": "daedalus:exhale"}), ("Read", {"file_path": "a"})]):
        lines.append({"type": "assistant", "uuid": f"a{i}", "timestamp": f"2026-10-15T10:0{i}:00Z", "sessionId": sid,
                      "message": {"id": f"m{i}", "role": "assistant", "model": "claude-opus-5-5",
                                  "usage": {"input_tokens": 1, "output_tokens": 1},
                                  "content": [{"type": "tool_use", "id": f"t{i}", "name": tool, "input": inp}]}})
    f = tmp_path / f"{sid}.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    st = kit_state.empty(sid, 1.0)
    st["events"] = [{"at": 1, "hook": "x", "event": "PostToolUse", "nudge": "x:try", "followed": True,
                     "tool": "agent:momus", "counted": True}]
    kit_state.save(st)
    d = build_digest(f)
    assert d["agent_calls"] == {"general-purpose": 1, "momus": 1}
    assert d["skill_calls"] == {"exhale": 1}
    assert d["hooks"]["nudges"]["x:try"]["followed"] == 1
