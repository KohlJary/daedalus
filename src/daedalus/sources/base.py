"""
The source plugin interface (edict 0011).

A plugin is a subclass of `Source`, registered under the entry-point group `daedalus.sources`:

    [project.entry-points."daedalus.sources"]
    jira = "daedalus_jira:JiraSource"

It declares:
- `config_schema`: its own settings, as dicts with key, type, default, description (and choices).
  They appear under `sources.<name>.<key>` next to the keys every source has (on_conflict,
  write_back_comment, token_env, mapping, enabled, type);
- `default_mapping`: which fields it owns, which tracker kinds become phases, roadmap items or tasks,
  and how the tracker's states map onto roadmap statuses;
- `supports_write_back`, and `write_back()` when it does.

It implements `fetch()`, which returns the tracker's items as `RemoteItem`s. Everything else
(proposals, conflicts, idempotency, write-back records, doctor) is Daedalus's, so a plugin never
touches the gameplan or roadmap itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# What a tracker kind becomes
PHASE, ITEM, TASK = "phase", "item", "task"

HEALTH = ("ok", "unverified", "never-synced", "auth-failed", "unreachable")


class SourceError(Exception):
    """A sync or write-back that couldn't reach the tracker. `health` is auth-failed or unreachable."""

    def __init__(self, message: str, health: str = "unreachable"):
        super().__init__(message)
        self.health = health


@dataclass
class RemoteItem:
    external_id: str
    kind: str                       # the tracker's own type: "Issue", "Milestone", "User Story", ...
    title: str
    state: str                      # the tracker's state, before the state map
    url: str = ""
    description: str = ""
    parent: Optional[str] = None    # the parent's external id
    updated: str = ""               # the tracker's last-changed time
    labels: list = field(default_factory=list)


class Source:
    """Base class for source plugins."""

    # Shown in `daedalus source list`
    title: str = "source"
    # Settings of the plugin's own, besides the common ones (see config_schema.COMMON_SOURCE_KEYS)
    config_schema: list[dict[str, Any]] = []
    default_mapping: dict[str, Any] = {"owned": ["title", "description", "status"], "kinds": {}, "states": {}}
    supports_write_back: bool = False
    # False until someone has run it against the live service; `source status` then says `unverified`
    verified: bool = True
    # Syncs with no configuration when is_configured() says it can (GitHub in a GitHub repository)
    implicit: bool = False

    def __init__(self, name: str, settings: dict[str, Any], project_dir: Path):
        self.name = name
        self.settings = settings
        self.project_dir = Path(project_dir)

    # ----- for plugins to implement -----

    def is_configured(self) -> bool:
        """Whether there is enough configuration to sync."""
        return True

    def fetch(self, known_ids: list[str], since: Optional[str]) -> list[RemoteItem]:
        """The tracker's items: the ones the query selects, plus any of `known_ids` (items synced before)
        that changed since `since`, so a closed item is seen. Raises SourceError."""
        raise NotImplementedError

    def write_back(self, external_id: str, comment: Optional[str]) -> None:
        """Mark the item done in the tracker, and post `comment` when it is given. Raises SourceError."""
        raise SourceError(f"{self.name} doesn't support write-back")

    # ----- shared -----

    def mapping(self) -> dict[str, Any]:
        """The default mapping with `sources.<name>.mapping` laid over it (kinds and states merge)."""
        base = self.default_mapping
        override = self.settings.get("mapping") or {}
        out = {
            "owned": list(override.get("owned", base.get("owned", []))),
            "kinds": {**base.get("kinds", {}), **override.get("kinds", {})},
            "states": {**base.get("states", {}), **override.get("states", {})},
        }
        return out

    def role(self, remote: RemoteItem) -> Optional[str]:
        """phase, item, task, or None to ignore."""
        return self.mapping()["kinds"].get(remote.kind)

    def status_for(self, remote: RemoteItem) -> str:
        states = {k.lower(): v for k, v in self.mapping()["states"].items()}
        return states.get(remote.state.lower(), "backlog")

    def item_type(self, remote: RemoteItem) -> str:
        if remote.kind.lower() == "bug" or any(str(lb).lower() == "bug" for lb in remote.labels):
            return "bug"
        return "feature"

    def fields(self, remote: RemoteItem) -> dict[str, Any]:
        """The owned fields as this item would have them."""
        all_fields = {"title": remote.title, "description": remote.description or "", "status": self.status_for(remote)}
        return {k: all_fields[k] for k in self.mapping()["owned"] if k in all_fields}

    def health_when_ok(self) -> str:
        return "ok" if self.verified else "unverified"
