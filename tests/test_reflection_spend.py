"""Spend (edict 0010, reflection): per-model and per-turn tokens in digests, and their estimate."""

from datetime import date

import pytest

from daedalus.reflection import digest as dg
from daedalus.reflection import spend as sp

from reflection_helpers import FIXTURES, REAL_SESSION, Builder, write_session

pytestmark = pytest.mark.reflection


def test_units_weigh_class_and_model():
    t = {"input": 100, "output": 10, "cache_read": 1000, "cache_creation": 40, "cache_creation_1h": 40}
    # 100*1 + 10*5 + 1000*0.1 + 40*2 = 330 Haiku-input units; Opus is 5x, Sonnet 3x
    assert sp.units(t, "claude-haiku-5-5") == 330
    assert sp.units(t, "claude-sonnet-5-5") == 990
    assert sp.units(t, "claude-opus-5-5") == 1650
    # Writes not split by lifetime count as 5-minute writes (1.25x)
    assert sp.units({"cache_creation": 40}, "claude-haiku-5-5") == 50
    # Unknown models weigh as the dearest; synthetic messages weigh nothing
    assert sp.units(t, "mystery-model") == 1650
    assert sp.units(t, "<synthetic>") == 0


def _usage(out, read=1000, write_1h=0, model="claude-opus-5-5"):
    return {"model": model, "usage": {"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": read,
                                      "cache_creation_input_tokens": write_1h,
                                      "cache_creation": {"ephemeral_1h_input_tokens": write_1h,
                                                         "ephemeral_5m_input_tokens": 0}}}


def _session(tmp_path):
    b = Builder(str(tmp_path))
    first = b.prompt("short question")
    b.call("Read", "t1", file_path="/x")
    b.result("t1")
    b.reply("answer")
    second = b.prompt("a much longer request " * 20)
    for i in range(3):
        b.call("Bash", f"c{i}", command=f"echo {i}")
        b.result(f"c{i}")
    b.reply("done")
    b.raw({"type": "system", "subtype": "compact_boundary", "uuid": "cb-1", "timestamp": b.start,
           "compactMetadata": {"trigger": "auto", "preTokens": 150000}})
    # The Builder writes model "claude-test"; give the replies real usage on named models
    for ev in b.events:
        if ev["type"] == "assistant":
            ev["message"].update(_usage(out=50, write_1h=10))
    return b, first, second


def test_turns_split_tokens_by_prompt(tmp_path):
    b, first, second = _session(tmp_path)
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    assert [t["uuid"] for t in d["turns"]] == [first, second]
    one, two = d["turns"]
    assert one["tool_calls"] == 1 and two["tool_calls"] == 3
    assert one["tokens_by_model"]["claude-opus-5-5"]["messages"] == 2
    assert two["tokens_by_model"]["claude-opus-5-5"]["messages"] == 4
    assert one["chars"] == len("short question") and one["model"] == "claude-opus-5-5"
    assert d["tokens"]["cache_creation_1h"] == 60
    assert d["compactions"] == [{"uuid": "cb-1", "at": b.start, "trigger": "auto", "pre_tokens": 150000}]
    # The session's units are its turns' units (no subagents here)
    assert d["units"] == pytest.approx(sum(t["units"] for t in d["turns"]))
    # Turns and compactions are citable events with a day
    assert first in d["event_days"] and "cb-1" in d["event_days"]


def test_summary_finds_light_turns_and_the_dearest(tmp_path):
    b, first, second = _session(tmp_path)
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    s = sp.summarize([d], date(2026, 10, 5), date(2026, 10, 5))
    assert s["turns"] == 2 and s["sessions"] == 1
    assert s["top_turns"][0]["uuid"] == second
    light = s["light_turns_on_top_model"]
    assert light["model"] == "claude-opus-5-5" and light["count"] == 1  # the short, one-call turn
    assert s["compactions"] == {"count": 1, "auto": 1, "pre_tokens": 150000}
    assert sum(v["units"] for v in s["by_class"].values()) == pytest.approx(s["units"], abs=0.5)
    # Outside the period, nothing
    assert sp.summarize([d], date(2026, 10, 6), date(2026, 10, 7))["turns"] == 0
    assert "Most expensive turns" in sp.render(s)


def test_subagents_count_by_type_and_model():
    d = dg.build_digest(FIXTURES / f"{REAL_SESSION}.jsonl")
    sub = d["subagents"]["list"][0]
    assert sub["tokens_by_model"] and sub["start"]
    s = sp.summarize([d])
    assert s["by_agent_type"]["momus"]["count"] == 1
    assert s["subagent_units"] == pytest.approx(d["subagents"]["units"], abs=0.5)


def test_check_accepts_a_turn_citation(tmp_path):
    from daedalus.reflection.check import _event_uuids

    b, first, _ = _session(tmp_path)
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    assert first in _event_uuids(d) and "cb-1" in _event_uuids(d)


def test_messages_before_the_first_prompt_count_in_a_period(tmp_path):
    b = Builder(str(tmp_path))
    b.reply("a hook-driven reply before anything was typed")
    b.prompt("now a prompt")
    b.reply("answer")
    d = dg.build_digest(write_session(tmp_path / "t", b.session_id, b.events))
    assert d["turns"][0]["uuid"] is None
    day = date(2026, 10, 5)
    assert sp.summarize([d], day, day)["units"] == sp.summarize([d])["units"] > 0


def test_old_digests_without_spend_are_reported():
    old = {"session_id": "old", "start": "2026-10-05T12:00:00Z", "tokens": {"output": 5}}
    s = sp.summarize([old])
    assert s["digests_without_spend"] == 1 and any("predate" in n for n in s["notes"])
