"""TUI core (edict 0012): backends, lazy import, cards, the ◆ check."""

import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from daedalus.tui import cards
from daedalus.tui.session import FakeBackend, PtyBackend, TmuxBackend, choose_backend

ROOT = Path(__file__).resolve().parents[1]


def test_importing_the_cli_and_running_help_and_the_hook_do_not_import_textual():
    code = ("import sys, daedalus.hooks; from daedalus.cli.main import main; "
            "from click.testing import CliRunner; CliRunner().invoke(main, ['--help']); "
            "print('textual' in sys.modules or 'daedalus.tui.app' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert out.stdout.strip() == "False", out.stderr


def test_glossary_ships_as_package_data_identical_to_the_design_doc():
    shipped = ROOT / "src/daedalus/tui/data/glossary.md"
    assert shipped.read_text(encoding="utf-8") == (ROOT / "docs/design/tui/glossary.md").read_text(encoding="utf-8")


def test_every_carded_concept_has_three_parts():
    for name, card in cards.all_cards().items():
        assert card.body, name
        if name not in ("ariadne", "momus", "theseus", "mind palace", "delphi", "due", "digest", "self model",
                        "user model", "machine: employer"):
            assert card.cli, name
    for panel, name in cards.PANEL_CARDS.items():
        assert name.lower() in cards.all_cards(), (panel, name)


def test_every_component_in_the_diagrams_has_a_widget_class():
    spec = importlib.util.spec_from_file_location("check", ROOT / "scripts/check_oph_widgets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.missing() == []


def test_backend_choice_falls_back_to_the_pty():
    backend, why = choose_backend("pty")
    assert isinstance(backend, PtyBackend) and why
    backend, why = choose_backend("auto")
    assert isinstance(backend, TmuxBackend if shutil.which("tmux") else PtyBackend)


def _read_until(session, needle: bytes, seconds: float = 5.0) -> bytes:
    got, end = b"", time.time() + seconds
    while needle not in got and time.time() < end:
        got += session.read(0.1)
    return got


@pytest.mark.skipif(sys.platform == "win32", reason="the PTY backend is POSIX only")
def test_the_pty_fallback_runs_a_real_child_that_ends_with_it(tmp_path):
    session = PtyBackend().start("t", ["cat"], tmp_path, 80, 24)
    session.write(b"hello\r")
    assert b"hello" in _read_until(session, b"hello")
    assert session.alive() and not session.persistent
    session.close()
    assert not session.alive()


@pytest.mark.skipif(not TmuxBackend().available(), reason="tmux is not installed; persistence is untested here")
def test_tmux_session_survives_the_client_closing(tmp_path):
    backend = TmuxBackend(socket=f"daedalus-test-{int(time.time())}")
    try:
        s = backend.start("persist", ["cat"], tmp_path, 80, 24)
        s.write(b"first\r")
        assert b"first" in _read_until(s, b"first")
        s.close()  # the TUI quits
        assert "persist" in backend.list()
        again = backend.attach("persist", 80, 24)
        again.write(b"second\r")
        assert b"second" in _read_until(again, b"second")
        again.close()
    finally:
        backend.kill("persist")
        subprocess.run(["tmux", "-L", backend.socket, "kill-server"], capture_output=True)


def test_fake_backend_persistence_matches_the_interface():
    store = {}
    a = FakeBackend(persistent=True, store=store)
    s = a.start("x", ["claude"], Path("."), 80, 24)
    s.write(b"hi")
    s.close()
    assert FakeBackend(persistent=True, store=store).list() == ["x"]
    assert FakeBackend(persistent=False).list() == []


def test_the_suite_never_writes_the_real_config_dir():
    """Guard for the conftest redirect: the config dir every test sees is under its tmp dir."""
    from daedalus.config import get_config_dir

    assert "xdg-config" in str(get_config_dir())
