import pytest


@pytest.fixture(autouse=True)
def _isolate_claude_dir(tmp_path, monkeypatch):
    """No test reads the real ~/.claude: reflection and doctor scan Claude Code's transcripts."""
    home = tmp_path / "claude-config-dir"
    home.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
