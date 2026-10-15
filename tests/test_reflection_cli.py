"""Reflection end to end (edict 0010): CLI, runners, A/B arm, inhale, doctor, bundles, identity."""

import hashlib
import json
import os
import subprocess
import time
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus.cli.main import main
from daedalus.reflection import models as m

from reflection_helpers import INTERRUPT_SESSION, REAL_SESSION, claude_home, git_init, install_fixtures, make_project

pytestmark = pytest.mark.reflection


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "daedalus-config"
    cfg.mkdir()
    monkeypatch.setattr("daedalus.config.get_config_dir", lambda: cfg)
    monkeypatch.setattr("daedalus.reflection.paths.get_config_dir", lambda: cfg)
    return cfg


@pytest.fixture
def project(tmp_path, monkeypatch, config_dir):
    p = make_project(tmp_path / "proj")
    install_fixtures(p)
    monkeypatch.chdir(p)
    return p


def run(*args, env=None):
    result = CliRunner().invoke(main, list(args), env=env, catch_exceptions=False)
    return result


# ---------- the runner guardrail ----------


def test_local_and_headless_need_machine_employer_false(config_dir):
    for value in ("local", "headless"):
        r = run("config", "reflection.runner", value)
        assert r.exit_code == 1 and "machine.employer" in r.output
    run("config", "machine.employer", "true")
    assert run("config", "reflection.runner", "local").exit_code == 1
    run("config", "machine.employer", "false")
    assert run("config", "reflection.runner", "headless").exit_code == 0
    assert run("config", "reflection.runner", "local").exit_code == 0


def test_local_falls_back_to_inhale_until_t_e5(config_dir):
    from daedalus.reflection.runners import resolve_runner

    run("config", "machine.employer", "false")
    run("config", "reflection.runner", "local")
    r = resolve_runner()
    assert r.configured == "local" and r.effective == "inhale" and "T-e5" in r.reason


def test_tick_makes_no_model_calls(project, monkeypatch):
    def no_calls(*a, **k):
        raise AssertionError("a model call was made")

    monkeypatch.setattr("daedalus.reflection.runners.run_headless", no_calls)
    monkeypatch.setattr("daedalus.reflection.runners.find_claude", lambda: None)
    for runner in ("inhale", "local"):
        if runner == "local":
            run("config", "machine.employer", "false")
            run("config", "reflection.runner", "local")
        r = run("reflect", "tick")
        assert r.exit_code == 0, r.output
        assert "Runner: inhale" in r.output
    assert "unavailable" in run("reflect", "runner").output


# ---------- digest, notes, inhale, the arm ----------


def test_exhale_notes_go_into_the_sessions_digest(project):
    r = run("reflect", "digest", "--notes", "Slow: waited on a backgrounded sleep.",
            env={"CLAUDE_CODE_SESSION_ID": INTERRUPT_SESSION})
    assert r.exit_code == 0, r.output
    digest = json.loads((project / ".daedalus/reflection/sessions" / f"{INTERRUPT_SESSION}.json").read_text(encoding="utf-8"))
    assert digest["notes"] == "Slow: waited on a backgrounded sleep."


def test_inhale_says_nothing_when_nothing_is_due(project):
    run("config", "reflection.model_summary", "off")
    r = run("reflect", "inhale", env={"CLAUDE_CODE_SESSION_ID": "new-session"})
    assert r.output == ""


def test_inhale_reports_what_is_due(project):
    run("reflect", "digest")
    for f in (project / ".daedalus/reflection/sessions").glob("*.json"):  # into a completed month
        d = json.loads(f.read_text(encoding="utf-8"))
        d["start"], d["end"] = "2026-09-15T10:00:00Z", "2026-09-15T11:00:00Z"
        d["event_days"] = {u: "2026-09-15" for u in d.get("event_days", {})}  # events belong to their day
        f.write_text(json.dumps(d), encoding="utf-8")
    run("config", "reflection.model_summary", "off")
    r = run("reflect", "inhale")
    assert "Reflection due" in r.output and "run now, or defer" in r.output
    assert "monthly reflection due for 2026-09" in r.output


def test_the_arm_is_chosen_in_code_and_recorded(project):
    from daedalus.reflection.arms import assign_arm

    first = assign_arm(project, "sess-a", "ab", seed=7)
    assert first["seed"] == 7 and first["arm"] in ("on", "off")
    assert assign_arm(project, "sess-a", "ab", seed=8)["arm"] == first["arm"]  # one arm per session
    import random
    assert first["arm"] == random.Random(7).choice(["on", "off"])
    arms = {assign_arm(project, f"s{i}", "ab", seed=i)["arm"] for i in range(20)}
    assert arms == {"on", "off"}


def test_digests_record_the_arm_and_none_without_inhale(project):
    from daedalus.reflection.arms import assign_arm

    assign_arm(project, INTERRUPT_SESSION, "on")
    run("reflect", "digest")
    sessions = project / ".daedalus/reflection/sessions"
    assert json.loads((sessions / f"{INTERRUPT_SESSION}.json").read_text(encoding="utf-8"))["model_summary_arm"] == "on"
    assert json.loads((sessions / f"{REAL_SESSION}.json").read_text(encoding="utf-8"))["model_summary_arm"] == "none"


def test_the_summary_prints_only_in_the_on_arm(project, config_dir):
    m.apply_change("user", {"op": "add", "entry": {"observation": "Uses they/them", "confidence": 0.9, "label": "shown"}},
                   by="user")
    run("config", "reflection.model_summary", "on")
    assert "they/them" in run("reflect", "inhale", env={"CLAUDE_CODE_SESSION_ID": "s-on"}).output
    run("config", "reflection.model_summary", "off")
    assert "they/them" not in run("reflect", "inhale", env={"CLAUDE_CODE_SESSION_ID": "s-off"}).output


# ---------- model CLI ----------


def test_forget_on_the_self_model_is_refused(project):
    s = m.apply_change("self", {"op": "add", "entry": {"kind": "behavior", "observation": "x"}}, by="user")
    r = run("reflect", "model", "self", "forget", s["id"])
    assert r.exit_code == 1 and "Only the user model" in r.output


def test_aspiration_text_cannot_be_edited_from_the_cli(project):
    a = m.aspire("To be plain", "claude-test", "2026-10")
    r = run("reflect", "model", "self", "edit", a["id"], "--observation", "To be fancy")
    assert r.exit_code == 1
    assert run("reflect", "model", "self", "delete", a["id"]).exit_code == 0


def test_history_cli_shows_versions_in_order(project):
    e = m.apply_change("user", {"op": "add", "entry": {"observation": "A"}}, by="user")
    m.user_edit("user", e["id"], {"observation": "B"})
    out = run("reflect", "model", "user", "--history", e["id"]).output.splitlines()
    assert out[0].endswith(": A") and out[1].endswith(": B")


def test_a_self_entry_dissent_blocks_nothing(project):
    s = m.apply_change("self", {"op": "add", "entry": {"kind": "stance", "observation": "I ask first"}}, by="user")
    r = run("edict", "dissent", s["id"], "--objection", "Too absolute", "--why", "Pre-approved pushes exist",
            "--instead", "Ask unless approved")
    assert r.exit_code == 0 and "nothing is paused" in r.output
    assert not (project / "docs" / "edicts" / "dissents").exists()
    from daedalus.reflection.bundle import build_bundle

    bundle = build_bundle(project, "monthly", "2026-10", {"half_life_self": 60, "half_life_user": 180}, "work")
    assert bundle["model_dissents"] == ["d001"]


# ---------- bundles ----------


def test_the_aspiration_bundle_holds_no_aspirations(project):
    m.aspire("To finish what I start", "claude-test", "2026-09")
    m.apply_change("self", {"op": "add", "entry": {"kind": "behavior", "observation": "I left a branch dangling"}},
                   by="user")
    run("reflect", "digest")
    assert run("reflect", "bundle", "aspiration", "2026-10").exit_code == 0
    text = (project / ".daedalus/reflection/bundles/aspiration-2026-10.json").read_text(encoding="utf-8")
    bundle = json.loads(text)
    assert "To finish what I start" not in text and '"aspiration"' not in json.dumps(bundle["behavior"])
    assert bundle["question"] == "Who do you want to be?" and bundle["behavior"]


def test_the_first_monthly_bundle_offers_seed_sources(project, config_dir):
    (config_dir / "identity.md").write_text("# Daedalus Identity\n", encoding="utf-8")
    memory = claude_home() / "projects" / "-fixture-project" / "memory"
    memory.mkdir()
    (memory / "pronouns.md").write_text("Kohl uses they/them\n", encoding="utf-8")
    from daedalus.reflection.bundle import build_bundle

    bundle = build_bundle(project, "monthly", "2026-10", {"half_life_self": 60, "half_life_user": 180}, "work")
    kinds = sorted(s["kind"] for s in bundle["seed_sources"])
    assert kinds == ["identity", "memory-note"]


def test_a_monthly_report_renders_an_empty_evolution(project):
    from daedalus.reflection.render import render_report

    md = render_report({"level": "monthly", "period": "2026-10", "evolution": []})
    assert "## Evolution" in md and "No model changes this month." in md


def test_identity_files_are_untouched_by_reflection(project, config_dir):
    from daedalus.identity import seed  # noqa: F401  (package copies)
    from daedalus.reflection import pending as pq
    from daedalus.reflection.bundle import build_aspiration_bundle, build_bundle

    pkg = Path(__file__).parents[1] / "src" / "daedalus" / "identity" / "data"
    (config_dir / "identity.md").write_text("# Identity\n", encoding="utf-8")
    (config_dir / "identity.json").write_text("{}\n", encoding="utf-8")
    files = [pkg / "identity.md", pkg / "identity.json", config_dir / "identity.md", config_dir / "identity.json"]
    before = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    settings = {"half_life_self": 60, "half_life_user": 180}
    run("reflect", "digest")
    build_bundle(project, "monthly", "2026-10", settings, "work")
    build_aspiration_bundle(project, "2026-10", settings)
    m.aspire("To be useful", "claude-test", "2026-10")
    s = m.apply_change("self", {"op": "add", "entry": {"kind": "behavior", "observation": "x"}}, by="proposal")
    m.apply_change("self", {"op": "retire", "id": s["id"]}, by="proposal")
    assert {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files} == before


# ---------- doctor and git ----------


def test_doctor_warns_before_cleanup_deletes_undigested_sessions(project):
    from daedalus.doctor import check_undigested_sessions

    (claude_home() / "settings.json").write_text(json.dumps({"cleanupPeriodDays": 10}), encoding="utf-8")
    folder = claude_home() / "projects" / "-fixture-project"
    old = time.time() - 5 * 86400
    for f in folder.glob("*.jsonl"):
        os.utime(f, (old, old))
    findings = check_undigested_sessions(project)
    assert findings and findings[0].name == "undigested-sessions-near-cleanup"
    assert "cleanupPeriodDays 10" in findings[0].message
    run("reflect", "digest")
    assert check_undigested_sessions(project) == []


def test_init_and_hydrate_keep_reflection_out_of_git(project):
    from daedalus.cli.commands import _ensure_reflection_ignored

    git_init(project)
    (project / ".gitignore").write_text("venv/\n", encoding="utf-8")
    _ensure_reflection_ignored(project)
    _ensure_reflection_ignored(project)  # idempotent
    text = (project / ".gitignore").read_text(encoding="utf-8")
    assert text.count("/.daedalus/reflection/") == 1
    ok = subprocess.run(["git", "check-ignore", "-q", ".daedalus/reflection/sessions/a.json"], cwd=project)
    assert ok.returncode == 0


def test_no_reflection_module_needs_fcntl(monkeypatch):
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("no fcntl here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    for mod in ("fsutil", "paths", "digest", "due", "models", "check", "pending", "bundle", "runners",
                "tick", "arms", "render"):
        sys.modules.pop(f"daedalus.reflection.{mod}", None)
        importlib.import_module(f"daedalus.reflection.{mod}")


def test_the_plugin_ships_delphi_and_the_reflect_skill():
    from daedalus.plugin import get_agents_dir, get_skills_dir
    import yaml

    manifest = yaml.safe_load((get_skills_dir().parent / "plugin.yaml").read_text(encoding="utf-8"))
    assert "delphi" in [a["name"] for a in manifest["agents"]]
    assert "reflect" in [s["name"] for s in manifest["skills"]]
    assert (get_agents_dir() / "delphi.md").exists() and (get_skills_dir() / "reflect" / "SKILL.md").exists()
    assert "daedalus reflect digest" in (get_skills_dir() / "exhale" / "SKILL.md").read_text(encoding="utf-8")
    assert "daedalus reflect inhale" in (get_skills_dir() / "inhale" / "SKILL.md").read_text(encoding="utf-8")


def test_headless_runs_only_where_allowed_and_inhale_presents_its_report(project, monkeypatch):
    import types

    from daedalus.reflection import tick as tk

    calls = []

    def fake_headless(project_dir, prompt, timeout=1800):
        calls.append(prompt)
        out = Path(project_dir) / ".daedalus/reflection/reports/monthly-2026-09.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# Reflection\n", encoding="utf-8")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr("daedalus.reflection.runners.run_headless", fake_headless)
    monkeypatch.setattr("daedalus.reflection.runners.find_claude", lambda: "/usr/bin/claude")
    with pytest.raises(RuntimeError):
        tk.run_due_headless(project)  # machine.employer unset: refused
    assert calls == []
    run("config", "machine.employer", "false")
    run("config", "reflection.runner", "headless")
    assert tk.run_due_headless(project) is True
    assert "Do not import or apply" in calls[0]
    run("config", "reflection.model_summary", "off")
    out = run("reflect", "inhale").output
    assert "report ready" in out and "monthly-2026-09.md" in out
    assert "report ready" not in run("reflect", "inhale").output  # presented once


def test_digests_record_mode_and_seed_and_bundles_hide_the_arm(project):
    from daedalus.reflection.arms import assign_arm
    from daedalus.reflection.bundle import build_bundle

    assign_arm(project, INTERRUPT_SESSION, "ab", seed=3)
    run("reflect", "digest")
    d = json.loads((project / ".daedalus/reflection/sessions" / f"{INTERRUPT_SESSION}.json").read_text(encoding="utf-8"))
    assert d["model_summary_mode"] == "ab" and d["model_summary_seed"] == 3
    bundle = build_bundle(project, "monthly", "2026-10", {"half_life_self": 60, "half_life_user": 180}, "work")
    assert all("model_summary_arm" not in x and "model_summary_seed" not in x for x in bundle["digests"])


def test_a_failing_headless_run_is_not_retried_every_tick(project, monkeypatch):
    import subprocess as sp

    from daedalus.reflection import tick as tk

    calls = []

    def hang(project_dir, prompt, timeout=1800):
        calls.append(1)
        raise sp.TimeoutExpired("claude", timeout)

    monkeypatch.setattr("daedalus.reflection.runners.run_headless", hang)
    monkeypatch.setattr("daedalus.reflection.runners.find_claude", lambda: "/usr/bin/claude")
    run("config", "machine.employer", "false")
    run("config", "reflection.runner", "headless")
    for _ in range(4):
        assert tk.run_due_headless(project) is False
    assert len(calls) == 2


def test_headless_runs_with_a_bounded_tool_list(monkeypatch, tmp_path):
    from daedalus.reflection import runners

    seen = {}
    monkeypatch.setattr(runners, "find_claude", lambda: "claude")
    monkeypatch.setattr(runners.subprocess, "run", lambda args, **kw: seen.setdefault("args", args))
    runners.run_headless(tmp_path, "go")
    assert seen["args"][:3] == ["claude", "-p", "go"] and seen["args"][3] == "--allowedTools"
    assert "Bash(daedalus reflect:*)" in seen["args"][4] and "Bash " not in seen["args"][4] + " "
