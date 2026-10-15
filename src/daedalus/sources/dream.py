"""
The `dream` source (edict 0013): the one way a dream reaches the plan.

It brings in, as `roadmap-new` proposals the owner applies or drops:
- each finished dream's waking picks (`<dream-id>.p<n>`), as `idea` items, priority P2;
- each elevated theme from a dream review (`theme:<id>`), as `idea` items, priority P1, labelled
  `recurring (<n> dreams)`.

A dropped pick stays dropped. A dropped theme comes back once, after it has recurred in dream.recur_min
more dreams since the drop; a second drop retires it. There is no write-back: a dream can't be closed
from the plan. It syncs only where dreaming is on (`dream.enabled`).

Everything it reads is local; no network.
"""

from __future__ import annotations

from typing import Optional

from .base import ITEM, RemoteItem, Source


class DreamSource(Source):
    title = "Dreams (speculative)"
    supports_write_back = False
    verified = True  # local files only: nothing to verify against a live service
    implicit = True
    config_schema = []
    default_mapping = {"owned": ["title"], "kinds": {"Pick": ITEM, "Theme": ITEM}, "states": {"open": "backlog"}}

    def _dream_settings(self) -> dict:
        from ..config import get_project_settings

        try:
            return get_project_settings(self.project_dir, "dream")
        except (AttributeError, TypeError):
            return {}

    def is_configured(self) -> bool:
        return bool(self._dream_settings().get("enabled"))

    def item_type(self, remote: RemoteItem) -> str:
        return "idea"

    def priority(self, remote: RemoteItem) -> str:
        return "P1" if remote.kind == "Theme" else "P2"

    def fetch(self, known_ids: list[str], since: Optional[str]) -> list[RemoteItem]:
        from ..dreams import review, store
        from . import state
        from .sync import drop_records

        settings = self._dream_settings()
        recur_min = int(settings.get("recur_min", 3))
        out: list[RemoteItem] = []
        for dream_id in store.list_dreams(self.project_dir):
            if store.load_meta(self.project_dir, dream_id).get("status") != "done":
                continue
            for p in store.picks(self.project_dir, dream_id):
                out.append(RemoteItem(
                    external_id=p["id"], kind="Pick", title=p["title"], state="open",
                    description=(f"From a dream (speculative): `daedalus dream show {dream_id}`.\n\n{p['text']}"),
                    url=f"daedalus dream show {dream_id}"))
        drops = drop_records(state.load(self.project_dir).get(self.name, {}))
        for theme in review.elevated(self.project_dir):
            key = f"src:{self.name}:theme:{theme['id']}"
            drop = drops.get(key)
            reproposable = False
            if drop:
                since_drop = theme["distinct_top_seeds"] - int(drop.get("recurrences_at_drop") or 0)
                reproposable = int(drop.get("count") or 0) == 1 and since_drop >= recur_min
            note = ""
            if drop and reproposable:
                note = f" You dropped it on {str(drop.get('last_dropped_at') or '')[:10]}; it has come back since."
            out.append(RemoteItem(
                external_id=f"theme:{theme['id']}", kind="Theme", title=theme["title"], state="open",
                description=(f"recurring ({theme['dreams']} dreams). {theme['summary']}{note}\n\n"
                             f"Ideas: {', '.join(theme['ideas'])}. See `daedalus dream review show`."),
                url="daedalus dream review show", reproposable=reproposable,
                recurrences=theme["distinct_top_seeds"]))
        return out

    def on_proposed(self, proposals: list[dict]) -> None:
        from ..dreams import store

        dream_ids = set()
        for p in proposals:
            ext = str((p.get("origin") or {}).get("external_id", ""))
            m = store.ITEM_ID.match(ext)
            if m:
                dream_ids.add(m.group(1))
                store.log(self.project_dir, {"record": "resolution", "item": ext, "dream": m.group(1),
                                             "outcome": "synced"})
            elif ext.startswith("theme:"):
                store.log(self.project_dir, {"record": "resolution", "item": ext, "dream": None,
                                             "outcome": "synced"})
        store.mark_synced(self.project_dir, sorted(dream_ids))

    def on_resolved(self, proposal: dict, outcome: str) -> None:
        from ..dreams import store

        ext = str((proposal.get("origin") or {}).get("external_id", ""))
        m = store.ITEM_ID.match(ext)
        store.log(self.project_dir, {"record": "resolution", "item": ext if (m or ext.startswith("theme:")) else "",
                                     "dream": m.group(1) if m else None, "outcome": outcome})
