"""
The config schema registry (edict 0011).

One registry of every setting Daedalus reads: key, type, default, description and allowed choices.
`daedalus config` validates against it, and the TUI's config screen (edict 0012) edits through it.

Core keys come from the dataclasses in config.py, with their choices from SETTING_CHOICES and their
descriptions from DESCRIPTIONS below (a test checks that every core key has one). Source keys live
under `sources.<name>.<key>`: a few common to every source, registered here, plus each source's own
keys, which it declares through its entry point (see daedalus.sources).

Nothing here imports a source plugin until a `sources.*` key is looked up, so loading the registry
for core keys stays cheap.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Optional

TYPES = ("str", "bool", "int", "list", "dict", "tristate")

TRUE_WORDS = ("true", "1", "yes", "on")
FALSE_WORDS = ("false", "0", "no", "off")
UNSET_WORDS = ("unset", "none", "null")


@dataclass(frozen=True)
class Setting:
    key: str
    type: str
    default: Any
    description: str
    choices: Optional[tuple] = None
    # A project may override it in .daedalus/config.json
    project: bool = False
    # Never shown or written to a config file (credentials live in the keyring; edict 0012)
    secret: bool = False
    nullable: bool = False


DESCRIPTIONS = {
    "user.name": "Your name, as Daedalus writes it in CLAUDE.md and memory.",
    "user.communication_style": "How you like to be spoken to; copied into the CLAUDE.md template.",
    "user.email": "Email for Daedalus's commits. Unset means git's user.email.",
    "icarus.enabled": "Whether Icarus parallel workers are available.",
    "icarus.bus_root": "Directory of the Icarus work bus. Unset means the default location.",
    "ariadne.enabled": "Whether Ariadne orchestration is available.",
    "ariadne.autonomy": "How much Ariadne dispatches without asking: supervised, hybrid or full.",
    "ariadne.auto_dispatch_threshold": "In hybrid mode, the complexity below which work is dispatched without asking.",
    "ariadne.require_approval_for": "Kinds of change that always need approval before dispatch.",
    "ariadne.max_parallel_workers": "The most workers Ariadne runs at once.",
    "ariadne.theseus_analysis": "Run Theseus's complexity analysis before planning.",
    "ariadne.worker_model": "Model for Icarus workers (edict 0002). Unset or 'default' means the SDK default.",
    "ariadne.judge_model": "Model for the semantic-review judge (edict 0002). Unset or 'default' means the SDK default.",
    "ariadne.build_gate": "Build the .NET projects a diff touches as its type check.",
    "ariadne.test_cmds": "Per-language test commands that replace the built-in runners, as JSON.",
    "git.authorship": "Who commits: 'daedalus' (authored as Daedalus) or 'user' (your identity, with a sign-off).",
    "sections.squash": "Include the squash-for-merge procedure in CLAUDE.md.",
    "sections.versioning": "Include the versioning rules in CLAUDE.md.",
    "edicts.enabled": "Use edicts in this project: design decisions handed to Daedalus as docs (edict 0005).",
    "doctor.stale_commits": "Commits after the gameplan's last update before doctor says it has fallen behind.",
    "doctor.stale_task_days": "Days a task may stay in progress before doctor flags it.",
    "hooks.session_start": "Print the gameplan-first brief when a Claude Code session starts.",
    "hooks.capture": "At session end and before compaction, propose gameplan updates from new commits.",
    "hooks.board": "On each prompt, note new posts in board threads you follow (throttled).",
    "hooks.budget_per_hour": "At most this many hook nudges per session-hour; extra ones are dropped and logged.",
    "hooks.efficacy_window": "A hook nudge counts as followed if the tool it names is used within this many events.",
    "hooks.momus_gate": "Daedalus's own `gh pr merge` needs a Momus trial covering the branch: gate (deny), nudge, or off.",
    "board.branch": "The git branch the agent board lives on (edict 0009).",
    "board.remote": "The remote the board branch is pushed to and fetched from.",
    "board.poll_minutes": "How often, at most, the board hook checks for new posts.",
    "reconstruct.score_threshold": "Commits whose message scores below this get their diff in the evidence bundle.",
    "reconstruct.sample_size": "High-scoring commits that get their diff anyway, to check the score.",
    "reconstruct.diff_cap": "Most characters of patch kept per commit.",
    "reconstruct.doc_paths": "Paths whose changes count as documentation evidence.",
    "reflection.runner": "Who runs reflection: inhale (in your session), local or headless (need machine.employer false).",
    "reflection.model_summary": "Show the user and self models at inhale: off, on, or ab (as an A/B test).",
    "reflection.forget": "What forgetting a user-model entry does to its history: purge or retain.",
    "reflection.scope": "Whether this project is work or private (personal is the earlier name); entries stay in their scope.",
    "reflection.share_private": "Show private model entries in work projects' inhale summary (it then goes to the work account).",
    "reflection.activity_threshold": "A day with fewer tool calls than this is not due for a daily reflection.",
    "reflection.retry_window": "Tool calls after a failure within which the same call counts as a retry.",
    "reflection.half_life_self": "Days for a self-model entry's weight to halve.",
    "reflection.half_life_user": "Days for a user-model entry's weight to halve.",
    "reflection.summary_tokens": "Cap on the inhale summary, in estimated tokens.",
    "reflection.cleanup_warning_days": "Days before Claude Code deletes old transcripts that doctor starts warning.",
    "machine.employer": "Whether this is an employer's machine. Unset counts as yes; set false on your own.",
    "dream.enabled": "Dream in this project (edict 0013): scheduled after reflection, and the dream source syncs.",
    "dream.mode": "How a dream is made: list, narrative, plain (no dream frame), or ab (drawn at random, logged).",
    "dream.seeds": "The most seeds one dream starts from.",
    "dream.turns": "Narrative mode: how many turns the Labyrinth and the dreamer each take. No early waking.",
    "dream.max_tokens": "A dream that would pass this many tokens stops and is recorded as truncated.",
    "dream.temperature": "Temperature for the dream, when a runner can set one (none can yet; logged as unset).",
    "dream.waking_temperature": "Temperature for the waking pass, when a runner can set one.",
    "dream.review_min": "Dreams since the last review before a dream review is due.",
    "dream.recur_min": "Dreams, with different top seeds, a theme needs before it is elevated to the roadmap.",
    "oph.components": "Components a ◆Name in docs/design may refer to (class names, or package directories to scan), for doctor's diagram lint.",
    # The TUI's own keys (edict 0012) register here so its config screen can edit them
    "tui.prs": "Where the TUI's NeedsYou finds PRs: 'local' (branches ahead of main) or 'gh' (the GitHub CLI).",
    "tui.escape": "The key chord that returns focus from the Claude pane to the dashboard.",
    "tui.backend": "How the Claude pane hosts its session: auto (tmux when installed, so it outlives the TUI), tmux, or pty (ends with the TUI).",
    "tui.send_form": "What s sends Claude: prose (the prompt alone, not logged), text (the prompt plus the panel's state as plain text), ophanic (the same state as an Ophanic diagram), or ab (text or ophanic drawn per send at the paste, logged to .daedalus/tui/sends.jsonl). text and ophanic carry the same facts, so ab compares form alone; prose carries less, so it isn't an arm.",
}

ON_CONFLICT_CHOICES = ("propose", "source", "local")

# Keys every source has, whatever its type. A source's own keys come from its plugin.
COMMON_SOURCE_KEYS = (
    ("type", "str", None, "Which installed source plugin this is. Unset means the source's name.", None),
    ("enabled", "bool", True, "Whether `daedalus source sync` with no name syncs this source.", None),
    ("on_conflict", "str", "propose",
     "When an item changed both here and in the tracker since the last sync: propose (a pending update), "
     "source (take the tracker's value) or local (keep ours).", ON_CONFLICT_CHOICES),
    ("write_back_comment", "bool", False,
     "When a write-back is applied, also post the task's resolution as a comment.", None),
    ("token_env", "str", None,
     "Name of an environment variable holding this source's token. The token itself is never stored in config.",
     None),
    ("mapping", "dict", None,
     "Overrides for the source's default mapping, as JSON: kinds, states and owned fields.", None),
)


def _field_type(value: Any, key: str) -> str:
    from .config import TRISTATE_SETTINGS

    if key in TRISTATE_SETTINGS:
        return "tristate"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "str"


def core_settings() -> dict[str, Setting]:
    """Every core setting, keyed by its dotted name."""
    from .config import PROJECT_SETTING_GROUPS, SETTING_CHOICES, DaedalusConfig

    out: dict[str, Setting] = {}
    config = DaedalusConfig()
    for group in fields(config):
        value = getattr(config, group.name)
        if not is_dataclass(value):
            continue
        for f in fields(value):
            key = f"{group.name}.{f.name}"
            default = getattr(value, f.name)
            out[key] = Setting(
                key=key, type=_field_type(default, key), default=default,
                description=DESCRIPTIONS.get(key, ""), choices=SETTING_CHOICES.get(key),
                project=group.name in PROJECT_SETTING_GROUPS, nullable=default is None,
            )
    return out


def source_settings(name: str, source_type: Optional[str] = None) -> dict[str, Setting]:
    """Settings for the source called `name`: the common keys plus its plugin's own.

    Raises KeyError when no installed source plugin matches (the error lists the installed ones).
    """
    from . import sources

    plugin = sources.plugin_class(source_type or name)
    out: dict[str, Setting] = {}
    for k, typ, default, desc, choices in COMMON_SOURCE_KEYS:
        key = f"sources.{name}.{k}"
        if k == "type":
            choices = tuple(sources.installed())
        out[key] = Setting(key, typ, default, desc, choices=choices, project=True, nullable=default is None)
    for spec in plugin.config_schema:
        key = f"sources.{name}.{spec['key']}"
        out[key] = Setting(key, spec.get("type", "str"), spec.get("default"), spec["description"],
                           choices=tuple(spec["choices"]) if spec.get("choices") else None, project=True,
                           secret=bool(spec.get("secret")), nullable=spec.get("default") is None)
    return out


def lookup(key: str, source_type: Optional[str] = None) -> Optional[Setting]:
    """The Setting for a dotted key, or None when the registry has no such key.

    For `sources.<name>.<key>`, `source_type` names the plugin when the source's config sets `type`.
    """
    if key.startswith("sources."):
        parts = key.split(".")
        if len(parts) != 3:
            return None
        if parts[2] == "type":
            from . import sources

            k, typ, default, desc, _ = COMMON_SOURCE_KEYS[0]
            return Setting(key, typ, default, desc, choices=tuple(sources.installed()), project=True, nullable=True)
        try:
            return source_settings(parts[1], source_type).get(key)
        except KeyError:
            return None
    return core_settings().get(key)


def convert(setting: Setting, value: str) -> Any:
    """A command-line string as the setting's type. Raises ValueError with a message saying what is allowed."""
    raw = value.strip()
    if setting.nullable and raw.lower() in UNSET_WORDS and setting.type != "tristate":
        return None
    if setting.type == "tristate":
        if raw.lower() in TRUE_WORDS:
            return True
        if raw.lower() in FALSE_WORDS:
            return False
        if raw.lower() in UNSET_WORDS:
            return None
        raise ValueError(f"{setting.key} takes true, false or unset")
    if setting.type == "bool":
        if raw.lower() in TRUE_WORDS:
            return True
        if raw.lower() in FALSE_WORDS:
            return False
        raise ValueError(f"{setting.key} takes true or false")
    if setting.type == "int":
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{setting.key} takes a whole number")
    if setting.type in ("list", "dict"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError(f"{setting.key} takes a JSON {'list' if setting.type == 'list' else 'object'}")
        if not isinstance(parsed, list if setting.type == "list" else dict):
            raise ValueError(f"{setting.key} takes a JSON {'list' if setting.type == 'list' else 'object'}")
        return parsed
    if setting.key.endswith(".token_env") and not re.fullmatch(r"[A-Z_][A-Z0-9_]*", raw):
        raise ValueError(f"{setting.key} is the NAME of an environment variable (like GITHUB_TOKEN), in capitals. "
                         "Never put the token itself in config; `daedalus source login` stores it in the keyring.")
    if setting.choices and value not in setting.choices:
        raise ValueError(f"invalid value for {setting.key}: {value!r}. Allowed: {', '.join(setting.choices)}")
    return value


def check(key: str, value: str, source_type: Optional[str] = None) -> tuple[Any, Optional[str]]:
    """(converted value, None), or (None, why it is refused): an unknown key, or a value it doesn't take."""
    setting = lookup(key, source_type)
    if setting is None:
        if key.startswith("sources."):
            from . import sources

            parts = key.split(".")
            if len(parts) != 3:
                return None, f"Source settings are sources.<name>.<key>, not {key}"
            installed = ", ".join(sources.installed()) or "none"
            try:
                sources.plugin_class(source_type or parts[1])
            except KeyError:
                return None, (f"No installed source plugin named {source_type or parts[1]!r} (installed: {installed}). "
                              f"Set sources.{parts[1]}.type to one of them first.")
            return None, f"Unknown setting {key}. See `daedalus config --schema sources.{parts[1]}`."
        return None, f"Unknown config key: {key}"
    try:
        return convert(setting, value), None
    except ValueError as e:
        return None, str(e)
