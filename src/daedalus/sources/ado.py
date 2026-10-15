"""
Azure DevOps work items as a source (edict 0011).

Default mapping: an Epic or Feature becomes a `new-phase` proposal, a User Story, Product Backlog
Item or Bug a `roadmap-new` item, and a Task a task in the phase that references its parent's item.

Given organization and project, it runs a WIQL query (default: open work items assigned to you in
the current iteration, through `@Me` and `@CurrentIteration`), then fetches those items and their
parents, two levels up, so a story's Feature and a task's story are known even when they aren't
assigned to you. The token is a personal access token, from `token_env` or the keyring.

**Unverified.** Written to the documented REST API 7.1
(https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/wiql/query-by-wiql and
https://learn.microsoft.com/en-us/rest/api/azure/devops/wit/work-items/list) and tested only
against synthetic fixtures. `daedalus source status` reports it as `unverified` until someone has
run it live (Kohl, on the work machine) and set `verified = True` below.
"""

from __future__ import annotations

import base64
from typing import Optional
from urllib.parse import quote

from . import credentials, http
from .base import ITEM, PHASE, TASK, RemoteItem, Source, SourceError

API_VERSION = "7.1"
COMMENTS_API_VERSION = "7.1-preview.4"
BATCH = 200  # the work-items list endpoint takes at most 200 ids

DEFAULT_QUERY = (
    "SELECT [System.Id] FROM WorkItems "
    "WHERE [System.TeamProject] = @project "
    "AND [System.AssignedTo] = @Me "
    "AND [System.IterationPath] = @CurrentIteration "
    "AND [System.State] NOT IN ('Closed', 'Removed', 'Done', 'Resolved') "
    "ORDER BY [System.ChangedDate] DESC"
)

FIELDS = ("System.Id", "System.WorkItemType", "System.Title", "System.State", "System.Description",
          "System.ChangedDate", "System.Tags")


class AdoSource(Source):
    title = "Azure DevOps"
    supports_write_back = True
    verified = False
    config_schema = [
        {"key": "organization", "type": "str", "default": None,
         "description": "The Azure DevOps organization (the name in dev.azure.com/<organization>)."},
        {"key": "project", "type": "str", "default": None, "description": "The Azure DevOps project."},
        {"key": "team", "type": "str", "default": None,
         "description": "The team whose current iteration @CurrentIteration means. Unset means the project's default team."},
        {"key": "query", "type": "str", "default": None,
         "description": "A WIQL query selecting the work items to sync. Unset means open items assigned to you "
                        "in the current iteration."},
        {"key": "done_state", "type": "str", "default": "Closed",
         "description": "The state a write-back moves a work item to (e.g. Closed, Done)."},
        {"key": "base_url", "type": "str", "default": "https://dev.azure.com",
         "description": "The server URL (change it for Azure DevOps Server)."},
    ]
    default_mapping = {
        "owned": ["title", "description", "status"],
        "kinds": {"Epic": PHASE, "Feature": PHASE, "User Story": ITEM, "Product Backlog Item": ITEM,
                  "Bug": ITEM, "Task": TASK},
        "states": {
            "New": "backlog", "Proposed": "backlog", "To Do": "backlog", "Approved": "ready",
            "Active": "in_progress", "Committed": "in_progress", "In Progress": "in_progress", "Doing": "in_progress",
            "Resolved": "review", "Closed": "done", "Done": "done", "Removed": "done",
        },
    }

    def is_configured(self) -> bool:
        return bool(self.settings.get("organization") and self.settings.get("project"))

    def _headers(self) -> dict:
        tok = credentials.token(self.name, self.settings)
        if not tok:
            raise SourceError(f"No Azure DevOps token for {self.name}: set sources.{self.name}.token_env or run "
                              f"`daedalus source login {self.name}`.", "auth-failed")
        basic = base64.b64encode(f":{tok}".encode()).decode()
        return {"Authorization": f"Basic {basic}", "Accept": "application/json", "User-Agent": "daedalus-cli"}

    def _project_url(self) -> str:
        base = (self.settings.get("base_url") or "https://dev.azure.com").rstrip("/")
        return f"{base}/{quote(self.settings['organization'])}/{quote(self.settings['project'])}"

    def _wiql_url(self) -> str:
        url = self._project_url()
        if self.settings.get("team"):
            url += f"/{quote(self.settings['team'])}"
        return f"{url}/_apis/wit/wiql?api-version={API_VERSION}"

    def _get_items(self, ids: list[int], headers: dict) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), BATCH):
            chunk = ",".join(str(x) for x in ids[i:i + BATCH])
            url = (f"{self._project_url()}/_apis/wit/workitems?ids={chunk}&$expand=relations"
                   f"&errorPolicy=Omit&api-version={API_VERSION}")
            body, _ = http.request("GET", url, headers)
            out += [w for w in (body or {}).get("value", []) if w]
        return out

    def fetch(self, known_ids: list[str], since: Optional[str]) -> list[RemoteItem]:
        if not self.is_configured():
            raise SourceError(f"{self.name}: set sources.{self.name}.organization and .project", "unreachable")
        headers = self._headers()
        result, _ = http.request("POST", self._wiql_url(), headers, {"query": self.settings.get("query") or DEFAULT_QUERY})
        ids = [w["id"] for w in (result or {}).get("workItems", [])]
        # Items synced before, so a closed one is seen (the query only selects open ones)
        ids += [int(k) for k in known_ids if k.isdigit() and int(k) not in ids]
        items = self._get_items(ids, headers) if ids else []
        have = {w["id"] for w in items}
        for _ in range(2):  # parents, two levels up: a task's story, a story's feature
            parents = {p for w in items if (p := parent_id(w)) is not None and p not in have}
            if not parents:
                break
            more = self._get_items(sorted(parents), headers)
            items += more
            have |= {w["id"] for w in more}
        return [self.to_remote(w) for w in items]

    def to_remote(self, w: dict) -> RemoteItem:
        f = w.get("fields", {})
        tags = [t.strip() for t in (f.get("System.Tags") or "").split(";") if t.strip()]
        parent = parent_id(w)
        return RemoteItem(
            external_id=str(w["id"]), kind=f.get("System.WorkItemType", ""), title=f.get("System.Title", ""),
            state=f.get("System.State", ""), url=((w.get("_links") or {}).get("html") or {}).get("href", w.get("url", "")),
            description=f.get("System.Description") or "", parent=str(parent) if parent is not None else None,
            updated=f.get("System.ChangedDate", ""), labels=tags)

    def write_back(self, external_id: str, comment: Optional[str]) -> None:
        headers = self._headers()
        url = f"{self._project_url()}/_apis/wit/workitems/{quote(external_id)}?api-version={API_VERSION}"
        http.request("PATCH", url, headers,
                     [{"op": "add", "path": "/fields/System.State", "value": self.settings.get("done_state") or "Closed"}],
                     content_type="application/json-patch+json")
        if comment:
            http.request("POST", f"{self._project_url()}/_apis/wit/workItems/{quote(external_id)}/comments"
                                 f"?api-version={COMMENTS_API_VERSION}", headers, {"text": comment})


def parent_id(w: dict) -> Optional[int]:
    """The parent's id, from the System.Parent field or a Hierarchy-Reverse relation."""
    f = w.get("fields", {})
    if isinstance(f.get("System.Parent"), int):
        return f["System.Parent"]
    for rel in w.get("relations") or []:
        if rel.get("rel") == "System.LinkTypes.Hierarchy-Reverse":
            tail = str(rel.get("url", "")).rstrip("/").rsplit("/", 1)[-1]
            if tail.isdigit():
                return int(tail)
    return None
