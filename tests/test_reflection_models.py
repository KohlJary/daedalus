"""The user and self models (edict 0010): history, decay, hand edits, forget, aspirations."""

import json
from datetime import date

import pytest

from daedalus.reflection import models as m

pytestmark = pytest.mark.reflection
SETTINGS = {"half_life_self": 60, "half_life_user": 180, "summary_tokens": 400}


@pytest.fixture
def root(tmp_path):
    return tmp_path / "models"


def add(root, model="user", **entry):
    entry.setdefault("observation", "Prefers small PRs")
    entry.setdefault("confidence", 0.8)
    entry.setdefault("label", "shown")
    entry.setdefault("evidence", [{"session": "s1", "event": "e1"}])
    return m.apply_change(model, {"op": "add", "entry": entry}, by="proposal", proposal_id="Q1", root=root,
                          today=date(2026, 10, 1))


def history_bytes(root) -> bytes:
    path = m.history_path(root)
    return path.read_bytes() if path.exists() else b""


def test_decay_halves_per_half_life_and_is_never_written_back(root):
    entry = add(root, observation="Uses they/them")
    stored = m.model_path("user", root).read_bytes()
    assert m.effective_confidence(entry, date(2026, 10, 1), 180) == pytest.approx(0.8)
    assert m.effective_confidence(entry, date(2027, 3, 30), 180) == pytest.approx(0.4)
    m.load("user", root)
    assert m.model_path("user", root).read_bytes() == stored


def test_each_model_has_its_own_half_life_and_stable_entries_do_not_decay(root):
    u = add(root, "user")
    s = add(root, "self", kind="behavior", observation="I check repo state before git")
    later = date(2026, 11, 30)  # 60 days on
    assert m.effective_confidence(s, later, m.half_life("self", SETTINGS)) == pytest.approx(0.4)
    assert m.effective_confidence(u, later, m.half_life("user", SETTINGS)) == pytest.approx(0.8 * 0.5 ** (60 / 180))
    stable = m.set_stable("self", s["id"], True, root)
    assert m.effective_confidence(stable, later, 60) == pytest.approx(0.8)


def test_history_is_append_only_for_every_operation(root):
    ops = []
    e = add(root)
    ops.append(lambda: m.apply_change("user", {"op": "affirm", "id": e["id"],
                                               "evidence": [{"session": "s2", "event": "e9"}]}, by="proposal", root=root))
    ops.append(lambda: m.apply_change("user", {"op": "revise", "id": e["id"], "changes": {"confidence": 0.6}},
                                      by="proposal", root=root))
    ops.append(lambda: m.user_edit("user", e["id"], {"scope": "work"}, root))
    ops.append(lambda: m.set_stable("user", e["id"], True, root))
    ops.append(lambda: m.apply_change("user", {"op": "retire", "id": e["id"], "reason": "no longer"},
                                      by="proposal", root=root))
    ops.append(lambda: m.aspire("To leave each repo clearer than I found it", "claude-test", "2026-10", root=root))
    other = add(root, observation="Works late")
    ops.append(lambda: m.delete("user", other["id"], root))
    for op in ops:
        before = history_bytes(root)
        op()
        after = history_bytes(root)
        assert after.startswith(before) and len(after) > len(before)


def test_a_revised_entry_keeps_its_id_and_history_shows_every_version(root):
    e = add(root)
    m.apply_change("user", {"op": "revise", "id": e["id"], "changes": {"observation": "Prefers small, focused PRs"}},
                   by="proposal", root=root)
    m.apply_change("user", {"op": "retire", "id": e["id"], "reason": "changed"}, by="proposal", root=root)
    versions = m.load_history(root, "user", e["id"])
    assert [r["kind"] for r in versions] == ["add", "revise", "retire"]
    assert versions[1]["before"]["observation"] == "Prefers small PRs"
    assert versions[1]["after"]["observation"] == "Prefers small, focused PRs"
    data = m.load("user", root)
    assert m.find(data, e["id"])["status"] == "retired"


def test_affirm_needs_a_session_not_already_cited(root):
    e = add(root)
    with pytest.raises(m.ModelError, match="not already"):
        m.apply_change("user", {"op": "affirm", "id": e["id"], "evidence": [{"session": "s1", "event": "e2"}]},
                       by="proposal", root=root)


def test_a_hand_edit_is_detected_and_recorded(root):
    e = add(root)
    path = m.model_path("user", root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"][0]["observation"] = "Prefers tiny PRs"
    path.write_text(json.dumps(data), encoding="utf-8")
    m.load("user", root)
    last = m.load_history(root, "user", e["id"])[-1]
    assert last["kind"] == "user-edit" and last["by"] == "user"
    assert last["before"]["observation"] == "Prefers small PRs" and last["after"]["observation"] == "Prefers tiny PRs"
    # Reading again records nothing new
    n = len(m.load_history(root))
    m.load("user", root)
    assert len(m.load_history(root)) == n


def test_deleting_by_hand_leaves_a_tombstone_and_it_is_not_added_again(root):
    e = add(root)
    path = m.model_path("user", root)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    data = m.load("user", root)
    assert m.is_tombstoned(data, e["id"])
    with pytest.raises(m.ModelError, match="deleted or forgotten"):
        add(root, observation="Prefers small PRs!")


def test_forget_purge_removes_the_history_and_retain_keeps_it(root):
    e = add(root)
    keep = add(root, observation="Uses they/them")
    m.forget(e["id"], "purge", root)
    records = m.load_history(root, "user")
    assert [r["kind"] for r in records if r["entry_id"] == e["id"]] == ["forget"]  # only the tombstone record
    assert any(r["entry_id"] == keep["id"] for r in records)
    with pytest.raises(m.ModelError):
        add(root, observation="Prefers small PRs")

    root2 = root.parent / "models2"
    e2 = add(root2)
    before = history_bytes(root2)
    m.forget(e2["id"], "retain", root2)
    assert history_bytes(root2).startswith(before)
    assert [r["kind"] for r in m.load_history(root2, "user", e2["id"])] == ["add", "forget"]


def test_aspirations_are_written_without_apply_and_dont_decay(root):
    a = m.aspire("To say plainly what I can't prove", "claude-opus-5-5", "2026-10", root=root, today=date(2026, 1, 1))
    assert a["kind"] == "aspiration" and a["author"] == "daedalus" and a["model_ids"] == ["claude-opus-5-5"]
    assert m.load_history(root, "self", a["id"])[0]["by"] == "daedalus"
    assert m.effective_confidence(a, date(2027, 1, 1), 60) == 1.0
    with pytest.raises(m.ModelError, match="not rewritten"):
        m.user_edit("self", a["id"], {"observation": "Something else"}, root)
    m.delete("self", a["id"], root)  # the user may delete one


def test_unmoved_aspirations_and_lineage_are_flagged(root):
    a = m.aspire("To finish what I start", "claude-old", "2026-06", root=root, today=date(2026, 6, 1))
    moved = m.aspire("To ask before pushing", "claude-old", "2026-06", root=root, today=date(2026, 6, 1))
    add(root, "self", kind="behavior", observation="Asked before every push",
        evidence=[{"session": "s1", "event": "e1"}, {"aspiration": moved["id"]}], model_ids=["claude-new"])
    old = add(root, "self", kind="behavior", observation="Over-used subagents", model_ids=["claude-old"])
    assert m.unmoved_aspirations(date(2026, 10, 1), root) == [a["id"]]
    assert m.lineage_flags({"claude-new"}, root) == [old["id"]]


def test_summary_respects_scope_unknown_retired_and_the_cap(root):
    add(root, observation="Personal: plays piano", scope="personal")
    add(root, observation="Uses they/them", scope="any")
    add(root, observation="Unknown thing", label="unknown")
    gone = add(root, observation="Retired thing")
    m.apply_change("user", {"op": "retire", "id": gone["id"]}, by="proposal", root=root)
    m.aspire("To leave things clearer", "claude-test", "2026-10", root=root)
    text = m.summary("work", SETTINGS, root, today=date(2026, 10, 1))
    assert "they/them" in text and "[aspiration] To leave things clearer" in text
    assert "piano" not in text and "Unknown thing" not in text and "Retired" not in text
    assert "piano" in m.summary("personal", SETTINGS, root, today=date(2026, 10, 1))
    for i in range(200):
        add(root, observation=f"Observation number {i} with some words to make it long enough")
    assert len(m.summary("work", {**SETTINGS, "summary_tokens": 100}, root)) <= 400


def test_dissent_on_a_self_entry_is_recorded_without_touching_it(root):
    s = add(root, "self", kind="stance", observation="I always ask before pushing")
    before = m.model_path("self", root).read_bytes()
    d = m.file_dissent(s["id"], "daedalus", "Too absolute", "Some pushes are pre-approved", "Ask unless approved", root)
    assert d["status"] == "open" and m.load_dissents(root, open_only=True)[0]["entry_id"] == s["id"]
    assert m.model_path("self", root).read_bytes() == before
