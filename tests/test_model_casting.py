"""Model casting for workers and judge (edict 0002).

Adapted from the Ariadne session's acceptance oracle (exp/ariadne-local,
experiments/ariadne-local/mature/mature_tasks.py, TASKS["model_casting"]), which also passes
unchanged against this implementation.
"""

import asyncio
import json
import sys
import types

import pytest
from click.testing import CliRunner

from daedalus import config as cfg
from daedalus.ariadne import semantic_review
from daedalus.ariadne.diff_bus import AriadneBus, Diff
from daedalus.ariadne.orchestrator import AriadneOrchestrator
from daedalus.cli.main import main

from test_ariadne_worker_loop import buses, edit, fake_sdk, process, project, run_work  # noqa: F401


@pytest.fixture(autouse=True)
def config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_config_file", lambda: tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(cfg, "get_config_dir", lambda: tmp_path / "cfg")


def set_models(worker=None, judge=None):
    for key, value in (("ariadne.worker_model", worker), ("ariadne.judge_model", judge)):
        if value:
            out = CliRunner().invoke(main, ["config", key, value])
            assert out.exit_code == 0 and "Unknown" not in out.output, out.output


@pytest.fixture
def fake_judge_sdk(monkeypatch):
    calls = []

    async def fake_query(prompt, options):
        calls.append(options)
        yield types.SimpleNamespace(text="APPROVE\nLooks right.")

    monkeypatch.setattr(semantic_review, "HAS_AGENT_SDK", True)
    monkeypatch.setattr(semantic_review, "query", fake_query, raising=False)
    monkeypatch.setattr(semantic_review, "ClaudeAgentOptions", lambda **kw: types.SimpleNamespace(**kw))
    return calls


def a_diff():
    return Diff.from_git_diff("w", "i", "diff --git a/x b/x\n", "Change x")


def test_defaults_are_unset():
    c = cfg.AriadneConfig()
    assert c.worker_model is None and c.judge_model is None


def test_settable_through_the_config_cli_and_unsettable():
    set_models("claude-haiku-5-5", "claude-opus-5-5")
    loaded = cfg.load_config().ariadne
    assert (loaded.worker_model, loaded.judge_model) == ("claude-haiku-5-5", "claude-opus-5-5")
    CliRunner().invoke(main, ["config", "ariadne.worker_model", "default"])
    assert cfg.cast_model(cfg.load_config().ariadne.worker_model) is None


@pytest.mark.parametrize("model", [None, "m-worker"])
def test_worker_model_reaches_options_and_the_diff(project, buses, fake_sdk, model):
    if model:
        set_models(worker=model)
    fake_sdk.scripts.append(edit("calc.py", "def mul(a, b):", "def mul(a, b):  # note"))
    asyncio.run(run_work(project, buses, "Document mul"))
    # Unset passes no model at all, so the real SDK keeps its own default (as before 0002)
    assert getattr(fake_sdk.calls[0], "model", "absent") == (model or "absent")
    (diff,) = buses[1].list_pending_diffs()
    assert diff.metadata.get("worker_model") == model


@pytest.mark.parametrize("model", [None, "m-judge"])
def test_judge_model_reaches_options_and_the_result(tmp_path, fake_judge_sdk, model):
    if model:
        set_models(judge=model)
    orch = AriadneOrchestrator(tmp_path, bus=AriadneBus(root=tmp_path / "ab"))
    result = orch.semantic_reviewer.review(a_diff(), "Change x")
    assert getattr(fake_judge_sdk[0], "model", None) == model
    assert result.to_dict()["model"] == model


def test_review_show_displays_both_models(tmp_path, fake_judge_sdk, monkeypatch, capsys):
    from daedalus.ariadne import orchestrator as orch_mod
    # The orchestrator CLI makes a roadmap Tracker in the working directory; keep it out of the checkout
    monkeypatch.chdir(tmp_path)
    set_models(judge="m-judge")
    bus = AriadneBus(root=tmp_path / "ab")
    bus.initialize()
    diff = a_diff()
    diff.metadata["worker_model"] = "m-worker"
    diff.semantic_review = AriadneOrchestrator(tmp_path, bus=bus).semantic_reviewer.review(diff, "Change x").to_dict()
    bus.submit_diff(diff)
    monkeypatch.setattr(orch_mod, "AriadneBus", lambda *a, **k: bus)
    monkeypatch.setattr(sys, "argv", ["ariadne", "--repo", str(tmp_path), "review", "show", diff.id])
    orch_mod.main()
    out = capsys.readouterr().out
    assert "worker model: m-worker" in out and "model m-judge" in out
