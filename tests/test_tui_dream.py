"""The Dream screen (edict 0012 on edict 0013, docs/design/tui/dream.oph): read-only, opened with `D`."""

import json
import os
import re
from datetime import date

import pytest

from daedalus import roadmap
from daedalus.cli import gameplan as gp
from daedalus.dreams import review, store
from daedalus.sources import state as src_state
from daedalus.tui.screens.dream import DreamScreen, SpeculativeLabel, pick_status
from daedalus.tui.widgets import ExplainCard, KeyBar, SendToClaude

from tui_helpers import make_app, tui_project  # noqa: F401
from sources_helpers import offline, project, run  # noqa: F401

pytestmark = pytest.mark.asyncio

REAL_NOW = store._now

SETTINGS = {"enabled": True, "mode": "ab", "seeds": 5, "turns": 2, "max_tokens": 60000, "review_min": 4,
            "recur_min": 3}

WAKING = """## Picks

1. **Glass labyrinth**: from i3. It grew from the stalled task; make it real with a map view.
2. **Wings for the CLI**: from i7. It grew from the open question; ship a release command.
3. **Thread of Ariadne**: from i12. It grew from the backlog; a resumable trail.
"""


def make_dream(project, mode, today, monkeypatch):
    """As tests/test_dreams.py does, with the clock pinned so the dream predates any reflection run."""
    monkeypatch.setattr(store, "_now", lambda: f"{today.isoformat()}T00:00:00Z")
    meta = store.start(project, {**SETTINGS, "mode": mode}, today=today)
    if mode == "narrative":
        for k in range(SETTINGS["turns"]):
            store.append_turn(project, meta["id"], "narrator", f"You walk a corridor {k}.", SETTINGS)
            store.append_turn(project, meta["id"], "dreamer", f"I build a door {k}.", SETTINGS)
        store.write_part(project, meta["id"], "waking", "## Ideas\n\n1. A door\n2. A map\n\n" + WAKING, SETTINGS)
    else:
        ideas = "\n".join(f"{i}. Idea number {i} about the labyrinth" for i in range(1, 13))
        store.write_part(project, meta["id"], "dream", "## Ideas\n\n" + ideas, SETTINGS)
        store.write_part(project, meta["id"], "waking", WAKING, SETTINGS)
    store.done(project, meta["id"], {"dreamer": "claude-opus-5-5"}, 1234)
    return meta["id"]


@pytest.fixture
def dreaming(tui_project, monkeypatch):
    assert run("config", "--project", "dream.enabled", "true").exit_code == 0
    return tui_project


@pytest.fixture
def dreamt(dreaming, monkeypatch):
    """Two dreams (narrative, then plain), picks in every state, one theme, and a reflection run since."""
    p = dreaming
    old = make_dream(p, "narrative", date(2026, 9, 1), monkeypatch)
    new = make_dream(p, "plain", date(2026, 9, 2), monkeypatch)
    monkeypatch.setattr(store, "_now", REAL_NOW)
    # the newer dream's picks reached the roadmap: built, in review, waiting
    items = [{"id": roadmap.item_id_for("dream", f"{new}.p{n}"), "title": t, "status": s, "item_type": "idea",
              "origin": {"source": "dream", "external_id": f"{new}.p{n}"}}
             for n, t, s in ((1, "Glass labyrinth", "done"), (2, "Wings for the CLI", "review"),
                             (3, "Thread of Ariadne", "backlog"))]
    roadmap.save_index(p, {"items": items, "version": 1})
    # the older dream's: one proposed (pending), one dropped, one never synced
    pend = gp.load_pending(p) + [{"id": "P9", "kind": "roadmap-new", "created": "2026-09-03",
                                  "origin": {"source": "dream", "external_id": f"{old}.p1"},
                                  "item": {"id": roadmap.item_id_for("dream", f"{old}.p1"), "title": "Glass labyrinth",
                                           "status": "backlog"}}]
    gp.save_pending(p, pend)
    src_state.record(p, "dream", dropped={f"src:dream:{old}.p2": {"count": 1, "last_dropped_at": "2026-09-04",
                                                                  "recurrences_at_drop": None}})
    bundle = review.build_bundle(p)
    ideas = sorted(bundle["ideas"])
    review.record(p, bundle, {"themes": [{"title": "A map of the labyrinth", "summary": "Seeing the maze whole.",
                                          "ideas": [i for i in ideas if i.endswith((".i2", ".i3"))],
                                          "integrated_by": None}]}, SETTINGS, today=date(2026, 9, 5))
    from daedalus.reflection import explog

    explog.append(p, {"record": "run", "level": "daily", "period": "2026-09-04", "runner": "inhale", "models": {},
                      "sessions": 1, "session_ids": [], "tokens": 1, "findings": {}, "proposals": [],
                      "check_iterations": 1, "report": "daily-2026-09-04.json"})
    return p, old, new


def _text(screen) -> str:
    parts = []
    for w in screen.query("Static, Markdown, MarkdownBlock, OptionList"):
        try:
            parts.append(str(w.render()))
        except Exception:
            continue
    for md in screen.query("Markdown"):
        parts.append(md.source)
    return "\n".join(parts)


async def open_dream(app, pilot):
    await pilot.pause()
    await pilot.press("D")
    await pilot.pause()
    assert isinstance(app.screen, DreamScreen)
    return app.screen


async def test_pick_status_maps_the_roadmap():
    assert pick_status({"status": "done"}, False, False) == "built"
    assert pick_status({"status": "review"}, False, False) == "in review"
    assert pick_status({"status": "backlog"}, False, False) == "waiting"
    assert pick_status({"status": "in_progress"}, False, False) == "in progress"
    assert pick_status(None, True, False) == "proposed"
    assert pick_status(None, False, True) == "dropped"
    assert pick_status(None, False, False) == "not synced yet"


async def test_dream_screen_tabs_label_and_no_mode(dreamt):
    p, old, new = dreamt
    app = make_app(p)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        assert screen.query(KeyBar) and screen.query(SpeculativeLabel)  # the diagram's ◆ components
        label = screen.query_one(SpeculativeLabel)
        assert "speculative" in str(label.render()) and label.display

        # Dreams: newest first; the detail is `dream show`, label and all
        assert [d["id"] for d in screen.dreams] == [new, old]
        seen = _text(screen)
        assert f"# Dream {new}" in seen and "Speculative." in seen
        await pilot.press("down")
        await pilot.pause()
        assert f"# Dream {old}" in _text(screen) and "You walk a corridor" in _text(screen)
        texts = [_text(screen)]

        # Picks: every pick across dreams, with what became of it
        await pilot.press("right")
        await pilot.pause()
        assert screen.tab == "picks"
        status = {pk.id: pk.status for pk in screen.picks}
        assert status == {f"{new}.p1": "built", f"{new}.p2": "in review", f"{new}.p3": "waiting",
                          f"{old}.p1": "proposed", f"{old}.p2": "dropped", f"{old}.p3": "not synced yet"}
        assert screen.query_one(SpeculativeLabel).display
        assert f"dream-{new}.p1" in _text(screen) and "built" in _text(screen)
        texts.append(_text(screen))

        # Themes: from the review's registry
        await pilot.press("3")
        await pilot.pause()
        assert screen.tab == "themes" and [t["title"] for t in screen.themes] == ["A map of the labyrinth"]
        seen = _text(screen)
        assert "t1" in seen and "2 dreams" in seen and "Seeing the maze whole." in seen
        assert screen.query_one(SpeculativeLabel).display
        texts.append(seen)

        # Due: computed, not written; review state and the experiment's totals only
        due_file = store.due_path(p)
        before = due_file.read_text() if due_file.exists() else None
        await pilot.press("4")
        await pilot.pause()
        seen = _text(screen)
        assert "A dream is due" in seen and "Dream review: not due (0 of 4" in seen
        assert "Dreams: 2 · picks: 6 · synced 0 · applied 0 · built 1" in seen
        assert "`daedalus dream log`" in seen and "Forced" not in seen
        assert (due_file.read_text() if due_file.exists() else None) == before
        texts.append(seen)

        # Nothing on any tab, Due included, says or counts which mode made a dream
        for text in texts:
            assert not re.search(r"\b(narrative|plain|modes?)\b", text, re.I), text  # catches "per-mode" too

        # s: a due dream comes first
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and app.screen.prompt == "A dream is due. Run /dream."
        await pilot.press("escape")
        await pilot.pause()

        from daedalus.tui.cards import PANEL_CARDS

        assert PANEL_CARDS["Dream"] == "Dream"
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, ExplainCard)
        card = _text(app.screen)
        assert "Dream" in card and ".daedalus/dreams/" in card and "daedalus dream show" in card
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, DreamScreen)


async def test_unsynced_picks_hand_over_the_sync(dreamt, monkeypatch):
    p, old, new = dreamt
    # by path: another test may have reloaded the module, and the screen imports the live one
    monkeypatch.setattr("daedalus.dreams.store.compute_due",
                        lambda project_dir, today=None: {"due": False, "waiting": None})
    app = make_app(p)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude)
        assert "`daedalus source sync dream`" in app.screen.prompt and "1 dream pick" in app.screen.prompt
    # read-only: nothing was synced, applied or written
    assert len(roadmap.load_index(p)["items"]) == 3
    assert [x["id"] for x in gp.load_pending(p) if x["id"] == "P9"] == ["P9"]


async def test_empty_state_teaches(dreaming):
    app = make_app(dreaming)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        assert "No dreams yet." in _text(screen) and "/dream" in _text(screen)
        await pilot.press("2")
        await pilot.pause()
        assert "No picks yet." in _text(screen) and "daedalus source sync dream" in _text(screen)
        await pilot.press("3")
        await pilot.pause()
        assert "No themes yet." in _text(screen) and "dream.review_min" in _text(screen)
        await pilot.press("4")
        await pilot.pause()
        assert "No dream is due" in _text(screen) and "No dreams finished yet." in _text(screen)


async def test_dreaming_off_says_what_it_is_and_how_to_turn_it_on(tui_project):
    assert not store.dreaming_enabled(tui_project)
    app = make_app(tui_project)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        seen = _text(screen)
        assert "Dreaming is off." in seen and "daedalus config dream.enabled true" in seen
        assert not screen.query_one("#dream-tabs").display and not screen.query_one("#dream-split").display
        await pilot.press("s")
        await pilot.pause()
        assert isinstance(app.screen, SendToClaude) and "dream.enabled" in app.screen.prompt
    assert not store.due_path(tui_project).exists()


async def test_dream_text_is_never_markup(dreaming, monkeypatch):
    bad = "bad [/oops] and [bold unclosed"
    meta = store.start(dreaming, {**SETTINGS, "mode": "list"}, today=date(2026, 9, 1))
    store.write_part(dreaming, meta["id"], "dream", f"## Ideas\n\n1. {bad}\n2. Another", SETTINGS)
    store.write_part(dreaming, meta["id"], "waking", f"## Picks\n\n1. {bad}: from i1.\n", SETTINGS)
    store.done(dreaming, meta["id"], {"dreamer": "claude-opus-5-5"}, 1)
    review.record(dreaming, review.build_bundle(dreaming),
                  {"themes": [{"title": bad, "summary": bad, "ideas": [f"{meta['id']}.i1"], "integrated_by": None}]},
                  SETTINGS, today=date(2026, 9, 2))
    app = make_app(dreaming)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        for key in ("2", "3", "4", "1"):
            await pilot.press(key)
            await pilot.pause()
        await pilot.press("3")
        await pilot.pause()
        assert "[/oops]" in _text(screen)


async def test_s_on_a_selected_pick_or_theme_is_about_that_row_even_when_a_dream_is_due(dreamt):
    p, old, new = dreamt
    app = make_app(p)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        assert screen.due.get("due")
        # Dreams: a due dream still comes first
        assert screen.send_prompt() == ("Dream due", "A dream is due. Run /dream.")
        await pilot.press("2")
        await pilot.pause()
        assert screen.picks[0].id == f"{new}.p1"
        title, prompt = screen.send_prompt()
        assert title == f"Pick {new}.p1" and "built" in prompt
        # an unsynced pick: its sync, not the due dream
        while screen.picks[screen._index()].status != "not synced yet":
            await pilot.press("down")
            await pilot.pause()
        assert "`daedalus source sync dream`" in screen.send_prompt()[1]
        await pilot.press("3")
        await pilot.pause()
        title, prompt = screen.send_prompt()
        assert title == "Theme t1" and "came back in 2 dreams" in prompt
        await pilot.press("4")
        await pilot.pause()
        assert screen.send_prompt() == ("Dream due", "A dream is due. Run /dream.")


def _themes_file(p):
    return review.themes_path(p)


def _edit_themes(p, change):
    path = _themes_file(p)
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


def _each_theme(key, value):
    def change(data):
        for t in data["themes"].values():
            t[key] = value
    return change


MALFORMED = {
    "waking.md not UTF-8": lambda p, new: (store.dream_dir(p, new) / "waking.md").write_bytes(b"## Picks\n\n1. \xff\xfe bad\n"),
    "dream.md not UTF-8": lambda p, new: (store.dream_dir(p, new) / "dream.md").write_bytes(b"\xff\xfe"),
    "themes a list": lambda p, new: _edit_themes(p, lambda d: d.update(themes=[])),
    "themes a list of non-dicts": lambda p, new: _edit_themes(p, lambda d: d.update(themes=["x", 1])),
    "registry not a dict": lambda p, new: _themes_file(p).write_text("[1, 2]"),
    "dreams not a number": lambda p, new: _edit_themes(p, _each_theme("dreams", "many")),
    "seed sets not a number": lambda p, new: _edit_themes(p, _each_theme("distinct_top_seeds", [1])),
    "ideas not a list": lambda p, new: _edit_themes(p, _each_theme("ideas", 5)),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
async def test_a_malformed_store_never_takes_the_screen_down(dreamt, case):
    p, old, new = dreamt
    MALFORMED[case](p, new)
    app = make_app(p)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await open_dream(app, pilot)
        for key in ("1", "down", "up", "2", "down", "3", "s", "escape", "4", "1"):
            await pilot.press(key)
            await pilot.pause()
        assert app.screen is screen and screen.tab == "dreams"
        assert screen.query_one("#dream-tabs").display


def _snapshot(root):
    out = {}
    for folder, dirs, names in os.walk(root):
        if ".git" in folder.split(os.sep):
            continue
        for d in dirs:
            out[os.path.join(folder, d) + "/"] = None
        for name in names:
            path = os.path.join(folder, name)
            with open(path, "rb") as fh:
                out[path] = (os.stat(path).st_mtime_ns, fh.read())
    return out


async def test_using_the_screen_changes_nothing_on_disk(dreamt):
    p, old, new = dreamt
    app = make_app(p)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        app.reload()  # the shell's own first-load writes (board/, .gitignore) happen before the snapshot
        await pilot.pause()
        before = _snapshot(p)
        await open_dream(app, pilot)
        for key in ("1", "down", "s", "escape", "2", "down", "s", "escape", "3", "s", "escape", "4", "s",
                    "escape", "question_mark", "escape", "left", "right", "h", "l"):
            await pilot.press(key)
            await pilot.pause()
        app.reload()
        await pilot.pause()
        after = _snapshot(p)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert changed == []


async def test_the_shell_watches_what_the_dream_screen_reads(dreamt):
    from daedalus.reflection import explog
    from daedalus.tui.app import watched_files

    p, old, new = dreamt
    files = set(watched_files(p))
    assert store.log_path(p) in files and review.themes_path(p) in files and explog.log_path(p) in files
    assert store.dream_dir(p, new) / "meta.json" in files and store.dream_dir(p, old) / "waking.md" in files
