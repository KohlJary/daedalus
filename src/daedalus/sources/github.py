"""
GitHub Issues as a source (edict 0011).

Default mapping: a milestone becomes a `new-phase` proposal, an issue a `roadmap-new` item, and a
sub-issue a task in the phase that references its parent issue's item. Pull requests are not intake
(they are work already in flight), so they are skipped.

With no configuration, in a repository whose `origin` is on GitHub, it syncs that repository's open
issues assigned to you. The token comes from `token_env`, the keyring, or `gh auth token`.

Written to the documented REST API (https://docs.github.com/en/rest/issues/issues and
https://docs.github.com/en/rest/issues/sub-issues); its tests run against synthetic fixtures.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Optional
from urllib.parse import quote, urlencode

from . import credentials, http
from .base import ITEM, PHASE, TASK, RemoteItem, Source, SourceError

API_VERSION = "2022-11-28"
REMOTE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def parse_remote(url: str) -> Optional[str]:
    m = REMOTE.search(url.strip())
    return f"{m.group('owner')}/{m.group('repo')}" if m else None


class GitHubSource(Source):
    title = "GitHub Issues"
    supports_write_back = True
    verified = False  # no live run yet; Kohl or a user flips this once one has
    implicit = True
    config_schema = [
        {"key": "repo", "type": "str", "default": None,
         "description": "owner/name of the repository. Unset means the project's origin remote, when it is on GitHub."},
        {"key": "assignee", "type": "str", "default": None,
         "description": "Whose issues to sync: a GitHub login, '*' for anyone's. Unset means yours (the token's user)."},
        {"key": "api_url", "type": "str", "default": "https://api.github.com",
         "description": "The GitHub API base URL (change it for GitHub Enterprise)."},
    ]
    default_mapping = {
        "owned": ["title", "description", "status"],
        "kinds": {"Milestone": PHASE, "Issue": ITEM, "Sub-issue": TASK},
        "states": {"open": "ready", "closed": "done"},
    }

    # ----- configuration -----

    def repo(self) -> Optional[str]:
        if self.settings.get("repo"):
            return self.settings["repo"]
        try:
            out = subprocess.run(["git", "remote", "get-url", "origin"], cwd=self.project_dir,
                                 capture_output=True, text=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        return parse_remote(out.stdout) if out.returncode == 0 else None

    def is_configured(self) -> bool:
        return self.repo() is not None

    def _headers(self) -> dict:
        tok = credentials.token(self.name, self.settings, gh_fallback=True)
        if not tok:
            raise SourceError(f"No GitHub token for {self.name}: set sources.{self.name}.token_env, run "
                              f"`daedalus source login {self.name}`, or log in with `gh auth login`.", "auth-failed")
        return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION, "User-Agent": "daedalus-cli"}

    def _base(self) -> str:
        repo = self.repo()
        if not repo:
            raise SourceError(f"{self.name}: no repository (set sources.{self.name}.repo)", "unreachable")
        return f"{self.settings.get('api_url') or 'https://api.github.com'}/repos/{repo}"

    def _get_all(self, url: str, headers: dict) -> list[dict]:
        out: list[dict] = []
        while url:
            body, resp_headers = http.request("GET", url, headers)
            out += body or []
            url = http.next_link(resp_headers)
        return out

    # ----- fetch -----

    def fetch(self, known_ids: list[str], since: Optional[str]) -> list[RemoteItem]:
        headers = self._headers()
        base = self._base()
        assignee = self.settings.get("assignee")
        if not assignee:
            me, _ = http.request("GET", f"{self.settings.get('api_url') or 'https://api.github.com'}/user", headers)
            assignee = me["login"]
        issues = self._get_all(f"{base}/issues?{urlencode({'state': 'open', 'assignee': assignee, 'per_page': 100})}",
                               headers)
        seen = {str(i["number"]) for i in issues}
        known = [k for k in known_ids if not k.startswith("m")]
        if known and since:
            # Items synced before that changed since: a closed issue drops out of the open query, so look it up
            changed = self._get_all(f"{base}/issues?{urlencode({'state': 'all', 'since': since, 'per_page': 100})}",
                                    headers)
            issues += [i for i in changed if str(i["number"]) in known and str(i["number"]) not in seen]
            seen = {str(i["number"]) for i in issues}
        # A sub-issue's parent may not be assigned to you: fetch it, so the sub-issue has an item to hang on
        # (as ADO fetches parents). One level, open parents only.
        for number in sorted({i["parent_issue_url"].rstrip("/").rsplit("/", 1)[-1] for i in issues
                              if i.get("parent_issue_url")} - seen):
            if number.isdigit():
                parent, _ = http.request("GET", f"{base}/issues/{number}", headers)
                if isinstance(parent, dict) and parent.get("state") == "open":
                    issues.append(parent)
        return self.to_remote(issues)

    def to_remote(self, issues: list[dict[str, Any]]) -> list[RemoteItem]:
        out: list[RemoteItem] = []
        milestones: dict[str, RemoteItem] = {}
        for issue in issues:
            if "pull_request" in issue:
                continue
            number = str(issue["number"])
            parent_url = issue.get("parent_issue_url")
            milestone = issue.get("milestone")
            if parent_url:
                kind, parent = "Sub-issue", parent_url.rstrip("/").rsplit("/", 1)[-1]
            else:
                kind, parent = "Issue", (f"m{milestone['number']}" if milestone else None)
            if milestone and f"m{milestone['number']}" not in milestones:
                milestones[f"m{milestone['number']}"] = RemoteItem(
                    external_id=f"m{milestone['number']}", kind="Milestone", title=milestone.get("title", ""),
                    state=milestone.get("state", "open"), url=milestone.get("html_url", ""),
                    description=milestone.get("description") or "", updated=milestone.get("updated_at", ""))
            out.append(RemoteItem(
                external_id=number, kind=kind, title=issue.get("title", ""), state=issue.get("state", "open"),
                url=issue.get("html_url", ""), description=issue.get("body") or "", parent=parent,
                updated=issue.get("updated_at", ""), labels=[lb.get("name", "") for lb in issue.get("labels", [])
                                                             if isinstance(lb, dict)]))
        return list(milestones.values()) + out

    # ----- write-back -----

    def write_back(self, external_id: str, comment: Optional[str]) -> None:
        if external_id.startswith("m"):
            raise SourceError("Milestones aren't written back; close it on GitHub.", "unreachable")
        headers = self._headers()
        url = f"{self._base()}/issues/{quote(external_id)}"
        http.request("PATCH", url, headers, {"state": "closed", "state_reason": "completed"})
        if comment:
            http.request("POST", f"{url}/comments", headers, {"body": comment})
