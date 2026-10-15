"""
Config (docs/design/tui/config.oph): every setting in the config schema registry (edict 0011), the layer
its value comes from, and editing at a chosen layer.

- Layers: D default → U user (~/.config/daedalus/config.json) → P project (.daedalus/config.json).
- Writes go through the same functions as `daedalus config`: user is `config_schema.check`,
  `setting_refusal`, `set_nested_value` and `save_config`; project is `set_project_value`.
- Secrets are invisible. A setting marked `secret`, and each source's credentials (kept in the system
  keyring by `daedalus source login`), show only whether a token is set. Nothing here keeps or renders a
  token, and nothing here writes one to a config file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..cards import Card
from ..widgets import ExplainCard, KeyBar

LAYER_NAMES = {"D": "default", "U": "user", "P": "project"}


# ---------- reading (plain data, no Textual) ----------

@dataclass
class Row:
    setting: Any            # config_schema.Setting
    group: str              # "git", "sources.github", ...
    value: Any = None       # the value in effect (never read for a secret)
    layer: str = "D"        # D, U or P
    layers: tuple = ()      # (layer letter, value) for each layer that sets it
    secret_status: str = ""

    @property
    def name(self) -> str:
        return self.setting.key[len(self.group) + 1:]

    @property
    def secret(self) -> bool:
        return bool(self.setting.secret)


def show(value: Any) -> str:
    if value is None:
        return "unset"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


def credential_status(project_dir: Path, name: str, settings: Optional[dict] = None) -> str:
    """Whether source `name` has a token, and where it comes from. Says only set / not set: the token is
    checked for presence and dropped, never kept or shown."""
    from ...sources import credentials

    settings = settings or {}
    env = settings.get("token_env")
    if env and os.environ.get(env):
        return f"from ${env} ✓ set"
    if credentials.from_keyring(name) is not None:
        return "stored in the system keyring ✓ set"
    if name == "github" or settings.get("type") == "github":
        if credentials.from_gh() is not None:
            return "gh CLI token ✓ set"
    return "not set"


def short_status(status: str) -> str:
    """The keys column's form of a credential status: keyring ✓, $ENV ✓, gh ✓ or not set."""
    if "✓" not in status:
        return "not set"
    if "keyring" in status:
        return "keyring ✓"
    return status.split(" ✓")[0].replace("from ", "").replace(" CLI token", "") + " ✓"


def credentials_setting(name: str):
    from ...config_schema import Setting

    return Setting(f"sources.{name}.credentials", "secret", None,
                   f"The token {name} signs in with. It lives in the system keyring (or the environment variable "
                   f"named by sources.{name}.token_env), never in a config file, and is never shown. "
                   f"Store or replace it with `daedalus source login {name}`.", project=True, secret=True)


def source_names(project_dir: Path) -> list[str]:
    """Sources configured here (user or project config), then any active without configuration."""
    from ... import config as cfg

    names = cfg.configured_source_names(project_dir)
    try:
        from ... import sources

        names += [n for n in sources.active(project_dir) if n not in names]
    except Exception:
        pass
    return names


def _dig(node: Any, parts: list[str]) -> tuple[bool, Any]:
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def load_rows(project_dir: Path) -> tuple[list[str], dict[str, list[Row]], dict[str, str]]:
    """(groups in order, rows per group, a note per group that couldn't load)."""
    from ... import config as cfg
    from ... import config_schema

    glob = cfg._global_config_raw()
    proj = cfg.load_project_overrides(project_dir)
    rows: dict[str, list[Row]] = {}
    groups: list[str] = []
    notes: dict[str, str] = {}
    for key, setting in config_schema.core_settings().items():
        group = key.split(".")[0]
        if group not in rows:
            groups.append(group)
            rows[group] = []
        rows[group].append(_row(setting, group, key.split("."), glob, proj))
    for name in source_names(project_dir):
        group = f"sources.{name}"
        groups.append(group)
        rows[group] = []
        stype = cfg.source_type(glob.get("sources", {}) if isinstance(glob.get("sources"), dict) else {},
                                proj.get("sources", {}) if isinstance(proj.get("sources"), dict) else {},
                                f"{group}.x")
        try:
            schema = config_schema.source_settings(name, stype)
        except KeyError as e:
            notes[group] = str(e).strip("'\"")
            continue
        for key, setting in schema.items():
            rows[group].append(_row(setting, group, key.split("."), glob, proj))
        settings = {r.name: r.value for r in rows[group] if not r.secret}
        status = credential_status(project_dir, name, settings)
        rows[group].append(Row(credentials_setting(name), group, None, "U" if "✓" in status else "D", (),
                               status))
        for r in rows[group]:
            if r.secret:
                r.secret_status = status
    return groups, rows, notes


def _row(setting, group: str, parts: list[str], glob: dict, proj: dict) -> Row:
    if setting.secret:  # never read
        return Row(setting, group)
    layers = []
    in_glob, gval = _dig(glob, parts)
    if in_glob and gval != setting.default:
        layers.append(("U", gval))
    in_proj, pval = (_dig(proj, parts) if setting.project else (False, None))
    if in_proj:
        layers.append(("P", pval))
    value = layers[-1][1] if layers else (gval if in_glob else setting.default)
    return Row(setting, group, value, layers[-1][0] if layers else "D", tuple(layers))


# ---------- writing (the same functions as `daedalus config`) ----------

def write_setting(project_dir: Path, key: str, raw: str, layer: str) -> Optional[str]:
    """Set `key` to `raw` at `layer` ("user" or "project"). None when saved, else why not (the CLI's words)."""
    from ... import config as cfg
    from ... import config_schema

    setting = config_schema.lookup(key, cfg.source_type(cfg.load_config().sources, key))
    if key.endswith(".credentials") or (setting is not None and setting.secret):
        name = key.split(".")[1] if key.startswith("sources.") else "<name>"
        return (f"Not set: {key} is a secret. Tokens are never written to a config file; "
                f"store it with `daedalus source login {name}`.")
    if layer == "project":
        if cfg.set_project_value(project_dir, key, raw):
            return None
        if key.split(".")[0] not in cfg.PROJECT_SETTING_GROUPS + ("sources",):
            return f"{key} can't be set per project, only for you (user)."
        stype = cfg.source_type(cfg.load_config().sources, cfg.load_project_overrides(project_dir).get("sources", {}),
                                key)
        _, error = config_schema.check(key, raw, stype)
        return f"Not set: {error or 'invalid value'}"
    config = cfg.load_config()
    _, error = config_schema.check(key, raw, cfg.source_type(config.sources, key))
    if error:
        return f"Not set: {error}"
    refusal = cfg.setting_refusal(config, key, raw)
    if refusal:
        return refusal
    if not cfg.set_nested_value(config, key, raw):
        return f"Unknown config key: {key}"
    cfg.save_config(config)
    return None


def setting_card(row: Row) -> Card:
    """A setting's Explain card: its description is what it is."""
    s = row.setting
    extra = [f"Type: {s.type}."]
    if s.choices:
        extra.append(f"Takes: {', '.join(s.choices)}.")
    if not row.secret:
        extra.append(f"Default: {show(s.default)}.")
    lives = ("the system keyring, never a config file" if row.secret else
             "~/.config/daedalus/config.json (user)" + (" or .daedalus/config.json (project)" if s.project else ""))
    cli = (f"daedalus source login {row.group.split('.', 1)[1]}" if row.secret else
           f"daedalus config {s.key}" + (f", daedalus config --project {s.key}" if s.project else "")
           + f", daedalus config --schema {s.key}")
    return Card(s.key, f"{s.description} {' '.join(extra)}", lives, cli)


# ---------- widgets ----------

class SettingCard(ExplainCard):
    """The ◆ExplainCard for one setting, built from its registry entry rather than the glossary."""

    def __init__(self, card: Card):
        super().__init__(card.title)
        self.the_card = card

    def compose(self):
        c = self.the_card
        with Vertical():
            yield Static(f"? {c.title}", id="card-title", markup=False)
            yield Static(c.body, id="card-body", markup=False)
            yield Static(f"\nLives in {c.lives}.", id="card-lives", markup=False)
            yield Static(f"CLI: {c.cli}", id="card-cli", markup=False)
            yield Static("\ng glossary · esc close", id="card-keys")


class EditSetting(ModalScreen):
    """◆EditSetting: edit one setting at a chosen layer (@modal), or a secret's status only (@secret).
    Dismisses with the layer it saved to, or None."""

    BINDINGS = [("escape", "cancel", "cancel"), ("tab", "layer", "layer"), ("left", "layer", "layer"),
                ("right", "layer", "layer"), ("space", "toggle", "toggle"), ("x", "unset", "unset")]
    DEFAULT_CSS = """
    EditSetting { align: center middle; }
    EditSetting > Vertical { width: 64; height: auto; border: round $accent; background: $surface; padding: 0 1; }
    EditSetting #edit-title { text-style: bold; border-bottom: solid $panel; }
    EditSetting #edit-desc { margin: 1 0; }
    EditSetting OptionList { height: auto; max-height: 10; }
    EditSetting #edit-layer { margin-top: 1; }
    EditSetting #edit-error { color: $error; }
    EditSetting #edit-keys { color: $text-muted; border-top: solid $panel; margin-top: 1; }
    """

    def __init__(self, project_dir: Path, row: Row):
        super().__init__()
        self.project_dir = Path(project_dir)
        self.row = row
        s = row.setting
        self.save_layer = "project" if (s.project and row.layer != "U") else "user"
        self.choices: Optional[list[str]] = None
        if not row.secret:
            if s.choices:
                self.choices = list(s.choices)
            elif s.type == "bool":
                self.choices = ["true", "false"]
            elif s.type == "tristate":
                self.choices = ["true", "false", "unset"]

    def compose(self):
        s, row = self.row.setting, self.row
        with Vertical():
            yield Static(f"{s.key}{' ' * max(2, 50 - len(s.key))}esc cancel", id="edit-title", markup=False)
            yield Static(s.description, id="edit-desc", markup=False)
            if row.secret:
                yield Static(f"Stored in: {row.secret_status or 'not set'}", id="edit-secret", markup=False)
                name = row.group.split(".", 1)[1] if row.group.startswith("sources.") else "<name>"
                yield Static(f"Replace or delete it in a terminal: daedalus source login {name}",
                             id="edit-secret-how", markup=False)
                yield Static("never shown, never written to a config file", id="edit-keys")
                return
            current = show(row.value)
            if self.choices is not None:
                opts = []
                for c in self.choices:
                    tags = [t for t, on in (("current", c == current), ("default", c == show(s.default))) if on]
                    opts.append(Option(f"{c}" + (f"  ({', '.join(tags)})" if tags else ""), id=c))
                olist = OptionList(*opts, id="edit-choices")
                if current in self.choices:
                    olist.highlighted = self.choices.index(current)
                yield olist
            else:
                yield Input(value="" if row.value is None else current, id="edit-input",
                            placeholder="unset" if s.nullable else "")
            yield Static("", id="edit-layer")
            yield Static("", id="edit-error", markup=False)
            keys = "tab layer · enter save" if self.choices is None else "←/→ layer · enter save"
            if s.type == "bool":
                keys += " · space toggle"
            if s.nullable and s.type != "tristate":
                keys += " · x unset" if self.choices is not None else " · type unset to clear"
            yield Static(keys, id="edit-keys")

    def on_mount(self) -> None:
        if not self.row.secret:
            self._show_layer()
            (self.query_one("#edit-choices") if self.choices is not None else self.query_one("#edit-input")).focus()

    def _show_layer(self) -> None:
        if not self.row.setting.project:
            text = "Save to:  [user]   (this setting is for you only, not per project)"
        else:
            text = "Save to:  " + "  ".join(f"[{n}]" if n == self.save_layer else n for n in ("project", "user"))
        self.query_one("#edit-layer", Static).update(text.replace("[", "\\["))

    def action_layer(self) -> None:
        if self.row.secret or not self.row.setting.project:
            return
        self.save_layer = "user" if self.save_layer == "project" else "project"
        self._show_layer()

    def action_toggle(self) -> None:
        if self.row.setting.type == "bool" and self.choices is not None:
            olist = self.query_one("#edit-choices", OptionList)
            olist.highlighted = 1 - (olist.highlighted or 0)

    def action_unset(self) -> None:
        if self.choices is not None and self.row.setting.nullable and self.row.setting.type != "tristate":
            self.save("unset")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.save(event.option.id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.save(event.value if event.value.strip() else "unset")

    def save(self, raw: str) -> None:
        error = write_setting(self.project_dir, self.row.setting.key, raw, self.save_layer)
        if error:
            self.query_one("#edit-error", Static).update(error)
            return
        self.dismiss(self.save_layer)


class ConfigScreen(Screen):
    """The Config screen (@browse): groups → keys → detail. `group` opens it on one group (Sources' `c`)."""

    BINDINGS = [
        ("escape", "back", "back"), ("question_mark", "explain", "explain"), ("enter", "edit", "edit"),
        ("e", "edit", "edit"), ("a", "changed", "all / changed only"), ("slash", "search", "search"),
        ("s", "send", "send to Claude"),
    ]
    DEFAULT_CSS = """
    ConfigScreen { layout: vertical; }
    ConfigScreen #config-title { height: 1; background: $boost; padding: 0 1; text-style: bold; }
    ConfigScreen #config-filter { height: 2; padding: 0 1; border-bottom: solid $panel; }
    ConfigScreen #config-search { display: none; height: 3; }
    ConfigScreen #config-body { height: 1fr; }
    ConfigScreen #config-groups { width: 28; border-right: solid $panel; }
    ConfigScreen #config-keys { width: 1fr; border-right: solid $panel; }
    ConfigScreen #config-detail { width: 36; padding: 0 1; }
    """

    def __init__(self, app, group: Optional[str] = None):
        super().__init__()
        self.shell = app
        self.project_dir = Path(app.project_dir)
        self.group = group
        self.changed_only = False
        self.search = ""
        self.groups: list[str] = []
        self.rows: dict[str, list[Row]] = {}
        self.notes: dict[str, str] = {}
        self.shown_rows: list[Row] = []

    def compose(self):
        yield Static("Config", id="config-title")
        yield Static("", id="config-filter", markup=False)
        yield Input(placeholder="search settings", id="config-search")
        with Horizontal(id="config-body"):
            yield OptionList(id="config-groups")
            yield OptionList(id="config-keys")
            yield Static("", id="config-detail", markup=False)
        yield KeyBar()

    def on_mount(self) -> None:
        self.query_one(KeyBar).show_dashboard(
            "↑/↓ move · tab column · enter edit · ? explain setting · a changed only · / search · esc back")
        width = max(self.size.width - 10, 40)
        self.query_one("#config-title", Static).update("Config" + " " * max(2, width - 6) + "esc back")
        self.refresh_state(getattr(self.shell, "state", None))
        self.query_one("#config-keys" if self.group else "#config-groups").focus()

    # ----- state -----

    def refresh_state(self, state=None) -> None:
        self.groups, self.rows, self.notes = load_rows(self.project_dir)
        if self.group not in self.groups:
            self.group = self.groups[0] if self.groups else None
        glist = self.query_one("#config-groups", OptionList)
        glist.clear_options()
        glist.add_options([Option(("▸" if g == self.group else " ") + g, id=g) for g in self.groups])
        if self.group:
            glist.highlighted = self.groups.index(self.group)
        self._show_keys()

    def _show_keys(self) -> None:
        filt = f"{self.group or ''} ▾   " + ("all · [changed only]" if self.changed_only else "[all] · changed only")
        filt += f" · search: {self.search}" if self.search else " · search /"
        self.query_one("#config-filter", Static).update(filt)
        rows = self.rows.get(self.group, []) if not self.search else [
            r for g in self.groups for r in self.rows[g] if self.search.lower() in r.setting.key.lower()]
        if self.changed_only:
            rows = [r for r in rows if r.layer != "D"]
        self.shown_rows = rows
        klist = self.query_one("#config-keys", OptionList)
        keep = klist.highlighted
        klist.clear_options()
        if not rows:
            msg = self.notes.get(self.group) or ("No settings changed from their defaults here."
                                                  if self.changed_only else "No settings match.")
            klist.add_option(Option(msg, disabled=True))
            self.query_one("#config-detail", Static).update("")
            return
        name_w = max(len(self._label(r)) for r in rows) + 2
        klist.add_options([Option(self._line(r, name_w), id=r.setting.key) for r in rows])
        klist.highlighted = keep if keep is not None and keep < len(rows) else 0
        self._show_detail()

    def _label(self, row: Row) -> str:
        return row.setting.key if self.search else row.name

    def _line(self, row: Row, name_w: int) -> str:
        value = short_status(row.secret_status) if row.secret else show(row.value)
        if len(value) > 24:
            value = value[:23] + "…"
        return f"{self._label(row):<{name_w}}{value:<26}{row.layer}"

    def selected(self) -> Optional[Row]:
        idx = self.query_one("#config-keys", OptionList).highlighted
        return self.shown_rows[idx] if idx is not None and idx < len(self.shown_rows) else None

    def _show_detail(self) -> None:
        row = self.selected()
        if row is None:
            return
        s = row.setting
        lines = [row.name, "", s.description, ""]
        if row.secret:
            lines += [f"Stored in: {row.secret_status or 'not set'}", "", "never shown, never written to a config file"]
        else:
            lines.append(f"type {s.type}" + ("" if s.project else " · user only"))
            if s.choices:
                lines.append(" · ".join(s.choices))
            trail = [f"D {show(s.default)}"] + [f"{lay} {show(v)}" for lay, v in row.layers]
            lines += ["", " → ".join(trail), f"in effect: {show(row.value)} ({LAYER_NAMES[row.layer]})"]
        self.query_one("#config-detail", Static).update("\n".join(lines))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_list.id == "config-groups" and event.option.id and event.option.id != self.group:
            self.group = event.option.id
            self.search = ""
            self.query_one("#config-keys", OptionList).highlighted = None
            self._show_keys()
        elif event.option_list.id == "config-keys":
            self._show_detail()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "config-groups":
            self.query_one("#config-keys").focus()
        else:
            self.action_edit()

    # ----- actions -----

    def action_back(self) -> None:
        search = self.query_one("#config-search", Input)
        if search.styles.display != "none" and self.focused is search:
            search.styles.display = "none"
            self.query_one("#config-keys").focus()
            return
        self.app.pop_screen()

    def action_explain(self) -> None:
        row = self.selected() if self.focused is self.query_one("#config-keys") else None
        if row is None:
            from ..cards import PANEL_CARDS

            self.app.push_screen(ExplainCard(PANEL_CARDS.get("Config", "Config")))
        else:
            self.app.push_screen(SettingCard(setting_card(row)))

    def action_edit(self) -> None:
        row = self.selected()
        if row is None:
            return

        def done(layer: Optional[str]) -> None:
            if layer:
                self.notify(f"Set {row.setting.key} ({layer})")
            self.refresh_state()
            self.query_one("#config-keys").focus()

        self.app.push_screen(EditSetting(self.project_dir, row), done)

    def action_changed(self) -> None:
        self.changed_only = not self.changed_only
        self._show_keys()

    def action_search(self) -> None:
        search = self.query_one("#config-search", Input)
        search.styles.display = "block"
        search.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "config-search":
            self.search = event.value.strip()
            self._show_keys()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "config-search":
            event.input.styles.display = "none"
            self.query_one("#config-keys").focus()

    def action_send(self) -> None:
        row = self.selected()
        if row is None:
            return
        key = row.setting.key
        self.shell.ask_to_send(f"Setting {key}", f"Explain the setting {key} (`daedalus config --schema {key}`) "
                                                  "and whether I should change it for this project. Don't change it.")

