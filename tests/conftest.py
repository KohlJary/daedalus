import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_dir(tmp_path, monkeypatch):
    """No test reads the real ~/.claude: reflection and doctor scan Claude Code's transcripts."""
    home = tmp_path / "claude-config-dir"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    # doctor's install check looks at how this machine installed daedalus-cli, not at the test's project
    monkeypatch.setenv("DAEDALUS_DOCTOR_SKIP_INSTALL", "1")
    # No test may touch the real ~/.config/daedalus or ~/.cache/daedalus (a stale module copy once wrote test
    # model entries to the real models directory): point platformdirs at the test's tmp dir, every test
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


@pytest.fixture(autouse=True)
def _isolate_hook_kit(tmp_path, monkeypatch):
    """The hook kit (edict 0016) finds its dirs itself: point it at the test's tmp dir on every OS. And
    registration uses the older per-feature commands unless a test asks for the kit, whether or not this
    machine has `daedalus-hook` installed."""
    from daedalus import hooks
    from daedalus_hookkit import paths

    monkeypatch.setattr(paths, "config_dir", lambda: tmp_path / "xdg-config" / "daedalus")
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "xdg-cache" / "daedalus")
    monkeypatch.setattr(hooks, "kit_installed", lambda: False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
