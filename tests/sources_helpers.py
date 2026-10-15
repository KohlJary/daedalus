"""Shared setup for the source tests (edict 0011): no live service is ever reached.

- sockets are disabled, so a request that slips past the fake transport fails loudly;
- GH_TOKEN and GITHUB_TOKEN are blanked, the keyring is a dict, and `gh` is stubbed;
- every HTTP call goes through FakeTransport, which answers from the synthetic fixtures in
  tests/fixtures/sources/ (hand-written to the documented API shapes; see each file's _docs).
"""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from daedalus import config as cfg
from daedalus import sources
from daedalus.cli import gameplan as gp
from daedalus.cli.main import main
from daedalus.sources import credentials, http

FIXTURES = Path(__file__).parent / "fixtures" / "sources"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class FakeTransport:
    """Answers (method, url) from routes: a list of [method, url substring, status, body or callable]."""

    def __init__(self):
        self.routes: list = []
        self.calls: list = []

    def on(self, method: str, contains: str, body=None, status: int = 200, headers=None):
        self.routes.insert(0, (method, contains, status, body, headers or {}))
        return self

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        for m, contains, status, resp, resp_headers in self.routes:
            if m == method and contains in url:
                if callable(resp):
                    resp = resp(url)
                return status, dict(resp_headers), json.dumps(resp).encode() if resp is not None else b""
        raise AssertionError(f"Unexpected request: {method} {url}")

    def writes(self):
        return [c for c in self.calls if c["method"] in ("PATCH", "POST") and "wiql" not in c["url"]]


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Isolation every source test runs under."""
    def refuse(*a, **k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    keyring: dict = {}
    monkeypatch.setattr(credentials, "from_keyring", lambda name: keyring.get(name))
    monkeypatch.setattr(credentials, "store", lambda name, token: keyring.__setitem__(name, token))
    monkeypatch.setattr(credentials, "from_gh", lambda: None)
    home = tmp_path / "global-config"
    monkeypatch.setattr(cfg, "get_config_file", lambda: home / "config.json")
    monkeypatch.setattr(cfg, "get_config_dir", lambda: home)
    transport = FakeTransport()
    http.set_transport(transport)
    sources.reset()
    yield {"keyring": keyring, "transport": transport}
    http.set_transport(None)
    sources.reset()


@pytest.fixture
def project(tmp_path, monkeypatch, offline):
    """A git repository whose origin is on GitHub, with an empty gameplan and roadmap."""
    repo = tmp_path / "widgets"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", "git@github.com:acme/widgets.git")
    gp.ensure_gameplan(repo)
    (repo / ".daedalus" / "roadmap" / "index.json").write_text('{"items": [], "version": 1}', encoding="utf-8")
    monkeypatch.chdir(repo)
    return repo


def run(*args):
    return CliRunner().invoke(main, list(args), catch_exceptions=False)


def github_routes(transport: FakeTransport, issues=None, since=None):
    data = fixture("github")
    transport.on("GET", "api.github.com/user", data["user"])
    transport.on("GET", "/repos/acme/widgets/issues?state=open", issues if issues is not None else data["issues_open"])
    transport.on("GET", "/repos/acme/widgets/issues?state=all", since if since is not None else [])
    return data


def pending(project_dir, workstream=None):
    path = gp.GameplanPaths.for_project(project_dir, workstream).pending_file
    return json.loads(path.read_text())["proposals"] if path.exists() else []


def index(project_dir):
    return json.loads((Path(project_dir) / ".daedalus" / "roadmap" / "index.json").read_text())
