"""
Sources (docs/design/tui/sources.oph): where work comes from. Each source's health, last sync, item count,
mapping and write-back, read from the same places as `daedalus source status` (the sync state file and
the roadmap index). Nothing here touches the network: a sync is offered to Claude as a dry run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from .. import state as st
from ..widgets import ExplainCard, KeyBar

# Health as a symbol and words, never colour alone
HEALTH = {
    "ok": ("●", "synced"), "unverified": ("●", "synced (unverified)"), "never-synced": ("○", "never synced"),
    "auth-failed": ("⚠", "auth failed"), "unreachable": ("⚠", "unreachable"), "broken": ("⚠", "plugin missing"),
}
ROLE_NAMES = {"phase": "phase", "item": "roadmap item", "task": "gameplan task"}

EMPTY = ("No sources here.\n\n"
         "A source connects an outside tracker (GitHub Issues, Azure DevOps, or a plugin like Jira) to the "
         "roadmap: a sync turns its items into pending proposals you apply or drop.\n\n"
         "GitHub works with no setup in a repository whose origin is on GitHub. To add another:\n"
         "  daedalus config --project sources.<name>.type ado\n"
         "  daedalus source login <name>\n"
         "See what's installed with `daedalus source list`.")


def source_rows(project_dir: Path) -> list[dict[str, Any]]:
    """One dict per source configured, active or with sync state, like `daedalus source status`."""
    from ... import roadmap, sources
    from ...config import configured_source_names
    from ...sources import state
    from .config import credential_status

    project_dir = Path(project_dir)
    states = state.load(project_dir)
    names = configured_source_names(project_dir)
    try:
        active = sources.active(project_dir)
    except Exception:
        active = []
    names += [n for n in active if n not in names]
    names += [n for n in states if n not in names]
    try:
        index = roadmap.load_index(project_dir)
    except Exception:
        index = {"items": []}
    out = []
    for name in names:
        entry = states.get(name, {})
        row: dict[str, Any] = {
            "name": name, "active": name in active, "health": entry.get("health") or "never-synced",
            "last_sync": entry.get("last_sync"), "error": entry.get("error"), "skipped": entry.get("skipped") or [],
            "count": len(roadmap.by_external(index, name)), "title": name, "where": "", "mapping": {},
            "write_back": None, "auth": "", "enabled": True, "problem": None,
        }
        try:
            src = sources.create(project_dir, name)
        except KeyError as e:
            row["health"], row["problem"] = "broken", str(e).strip("'\"")
            out.append(row)
            continue
        cls = type(src)
        row["title"] = cls.title
        row["enabled"] = src.settings.get("enabled", True)
        row["mapping"] = src.mapping()
        row["where"] = _where(src)
        if cls.supports_write_back:
            row["write_back"] = "state on task done" + (", plus a resolution comment"
                                                        if src.settings.get("write_back_comment") else "")
        row["auth"] = credential_status(project_dir, name, src.settings)
        out.append(row)
    return out


def _where(src) -> str:
    repo = getattr(src, "repo", None)
    if callable(repo):
        found = repo()
        if found:
            return found + ("" if src.settings.get("repo") else " (from origin)")
        return "no repository (set sources.%s.repo)" % src.name
    org, proj = src.settings.get("organization"), src.settings.get("project")
    if org or proj:
        return f"{org or '?'}/{proj or '?'}"
    return "" if src.is_configured() else "not configured yet"


def mapping_lines(mapping: dict) -> list[str]:
    by_role: dict[str, list[str]] = {}
    for kind, role in (mapping.get("kinds") or {}).items():
        by_role.setdefault(role, []).append(kind)
    parts = [f"{' / '.join(kinds)} → {ROLE_NAMES.get(role, role)}" for role, kinds in by_role.items()]
    return parts


class SourcesScreen(Screen):
    """The Sources screen (@expanded): the list of sources, then the selected one's detail."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("c", "configure", "configure"),
        ("s", "send", "send to Claude"),
    ]
    DEFAULT_CSS = """
    SourcesScreen { layout: vertical; }
    SourcesScreen #sources-title { height: 1; background: $boost; padding: 0 1; text-style: bold; }
    SourcesScreen #sources-body { height: 1fr; }
    SourcesScreen #sources-list { width: 40; border-right: solid $panel; }
    SourcesScreen #sources-right { width: 1fr; }
    SourcesScreen #sources-detail { height: 1fr; padding: 0 1; }
    SourcesScreen #sources-keys { height: 2; padding: 0 1; color: $text-muted; border-top: solid $panel; }
    SourcesScreen #sources-empty { height: 1fr; padding: 1 2; }
    """

    def __init__(self, app):
        super().__init__()
        self.shell = app
        self.project_dir = Path(app.project_dir)
        self.sources: list[dict[str, Any]] = []

    def compose(self):
        yield Static("Sources", id="sources-title")
        yield Static(EMPTY, id="sources-empty", markup=False)
        with Horizontal(id="sources-body"):
            yield OptionList(id="sources-list")
            with Vertical(id="sources-right"):
                with VerticalScroll(id="sources-detail"):
                    yield Static("", id="sources-detail-body", markup=False)
                yield Static("c configure (opens Config) · s send to Claude (dry-run sync) · ? explain",
                             id="sources-keys", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(KeyBar).show_dashboard("↑/↓ source · c configure · s send to Claude · ? explain · esc back")
        width = max(self.size.width - 10, 40)
        self.query_one("#sources-title", Static).update("Sources" + " " * max(2, width - 7) + "esc back")
        self.refresh_state(getattr(self.shell, "state", None))
        self.query_one("#sources-list").focus()

    def refresh_state(self, state=None) -> None:
        self.sources = source_rows(self.project_dir)
        has = bool(self.sources)
        self.query_one("#sources-empty").styles.display = "none" if has else "block"
        self.query_one("#sources-body").styles.display = "block" if has else "none"
        olist = self.query_one("#sources-list", OptionList)
        keep = olist.highlighted
        olist.clear_options()
        if not has:
            return
        olist.add_options([Option(self._line(r), id=r["name"]) for r in self.sources])
        olist.highlighted = keep if keep is not None and keep < len(self.sources) else 0
        self._show_detail()

    def _line(self, r: dict) -> str:
        symbol, words = HEALTH.get(r["health"], ("?", r["health"]))
        if r["health"] in ("ok", "unverified") and r["last_sync"]:
            words = f"synced {st.age(r['last_sync'])}" + (" ?" if r["health"] == "unverified" else "")
        if not r["enabled"]:
            words = "disabled"
        count = f"{r['count']} items" if r["health"] not in ("broken",) else "—"
        return f"{symbol} {r['name']:<10}{words:<16}{count:>9}"

    def selected(self) -> Optional[dict]:
        idx = self.query_one("#sources-list", OptionList).highlighted
        return self.sources[idx] if idx is not None and idx < len(self.sources) else None

    def _show_detail(self) -> None:
        r = self.selected()
        if r is None:
            return
        head = f"{r['name']} · {r['title']}" + (f" · {r['where']}" if r["where"] else "")
        lines = [head, ""]
        if r["problem"]:
            lines += [r["problem"], "", f"Set sources.{r['name']}.type to an installed plugin, or install it."]
        else:
            symbol, words = HEALTH.get(r["health"], ("?", r["health"]))
            lines.append(f"Health: {symbol} {r['health']}" + (f" ({words})" if words != r["health"] else ""))
            lines.append(f"Last sync: {r['last_sync'] or 'never'}" + ("" if r["active"] else
                                                                      " · not active (disabled or not configured)"))
            lines.append(f"Items in the roadmap: {r['count']}")
            if r["error"] and r["health"] in ("auth-failed", "unreachable"):
                lines.append(f"Last error: {r['error']}")
            if r["skipped"]:
                lines.append(f"{len(r['skipped'])} item(s) waiting for a phase; first: {r['skipped'][0]}")
            maps = mapping_lines(r["mapping"])
            if maps:
                lines += ["", "Maps: " + maps[0]] + [f"      {m}" for m in maps[1:]]
            states = (r["mapping"].get("states") or {})
            if states:
                lines.append("States: " + " · ".join(f"{k} → {v}" for k, v in states.items()))
            lines.append("Writes back: " + (f"{r['write_back']} (asks first)" if r["write_back"] else "never (read-only)"))
            lines.append(f"Auth: {r['auth']}")
        lines += ["", f"CLI: daedalus source status · daedalus source sync {r['name']} --dry-run"]
        self.query_one("#sources-detail-body", Static).update("\n".join(lines))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._show_detail()

    # ----- actions -----

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_explain(self) -> None:
        from ..cards import PANEL_CARDS

        self.app.push_screen(ExplainCard(PANEL_CARDS.get("Sources", "Source")))

    def action_configure(self) -> None:
        from .config import ConfigScreen

        r = self.selected()
        self.app.push_screen(ConfigScreen(self.shell, group=f"sources.{r['name']}" if r else None))

    def action_send(self) -> None:
        r = self.selected()
        if r is None:
            self.shell.ask_to_send("Sources", "Run `daedalus source list` and help me connect a tracker to this "
                                              "project's roadmap. Don't sync anything yet.")
            return
        name = r["name"]
        self.shell.ask_to_send(f"Source {name}", f"Run `daedalus source sync {name} --dry-run` and summarise the "
                                                 "proposals it would make. Don't run a real sync until I say so.")
