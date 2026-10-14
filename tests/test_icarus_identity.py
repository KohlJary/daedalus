"""The worker identity loads for real (gameplan T-e13: from c2fb6b2, 2025-12-24, it silently fell back to a stub)."""

import warnings
from pathlib import Path

import pytest

from daedalus.identity import seed
from daedalus.worker import harness

REPO_AGENT = Path(__file__).resolve().parents[1] / ".claude-plugin" / "agents" / "icarus.md"
SHIPPED = Path(harness.__file__).resolve().parents[1] / "identity" / "data" / "agents" / "icarus.md"


def test_full_identity_loads_without_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        identity = harness.load_icarus_identity()
    assert identity != harness._FALLBACK_IDENTITY
    assert "## Execution Mode" in identity and len(identity) > 1000


def test_frontmatter_is_not_part_of_the_system_prompt():
    identity = harness.load_icarus_identity()
    assert not identity.startswith("---")
    assert "tools: Read" not in identity and "model: sonnet" not in identity
    assert identity.startswith("# Icarus")


def test_missing_identity_warns_and_falls_back(monkeypatch):
    def missing(_package):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(harness.importlib.resources, "files", missing)
    with pytest.warns(RuntimeWarning, match="Icarus identity not found"):
        assert harness.load_icarus_identity() == harness._FALLBACK_IDENTITY


def test_agent_definition_api_finds_it():
    assert "## Execution Mode" in seed.load_agent_definition("icarus")


@pytest.mark.skipif(not REPO_AGENT.exists(), reason="installed without the repository's .claude-plugin/")
def test_shipped_identity_matches_the_plugin_agent():
    # Two copies drifted once (c2fb6b2 moved the agent and nothing noticed); keep them identical.
    assert SHIPPED.read_text(encoding="utf-8") == REPO_AGENT.read_text(encoding="utf-8")


@pytest.mark.parametrize("text, body", [
    ("---\nname: x\ndescription: a---b\n---\n# Body\n\n---\n\nmore\n", "# Body\n\n---\n\nmore\n"),
    ("---\r\nname: x\r\n---\r\n# Body\r\n", "# Body\r\n"),
    ("# No frontmatter\n\n---\n\nrule above\n", "# No frontmatter\n\n---\n\nrule above\n"),
    ("--- not frontmatter\ntext\n", "--- not frontmatter\ntext\n"),
])
def test_strip_frontmatter_only_removes_a_leading_block(text, body):
    assert harness._strip_frontmatter(text) == body


def test_identity_is_not_a_hydrated_agent():
    # hydrate copies every plugin/agents/*.md into each project's .claude/agents/; icarus must not be one
    from daedalus.plugin import get_agents_dir
    assert not (get_agents_dir() / "icarus.md").exists()
