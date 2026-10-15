"""
Cross-platform configuration management for Daedalus.

Uses platformdirs for OS-appropriate paths:
- Linux: ~/.config/daedalus/
- macOS: ~/Library/Application Support/daedalus/
- Windows: %APPDATA%/daedalus/
"""

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir, user_cache_dir


@dataclass
class UserConfig:
    """User-specific settings."""
    name: str = "the user"
    communication_style: str = "Not specified"
    email: Optional[str] = None  # Defaults to git config user.email


@dataclass
class IcarusConfig:
    """Icarus bus configuration."""
    enabled: bool = False
    bus_root: Optional[str] = None


@dataclass
class AriadneConfig:
    """Ariadne orchestration configuration."""
    enabled: bool = False
    autonomy: str = "hybrid"  # supervised, hybrid, full
    auto_dispatch_threshold: int = 3  # Complexity threshold for auto-dispatch in hybrid mode
    require_approval_for: list = field(default_factory=lambda: [
        "breaking_change", "security", "architecture", "database"
    ])
    max_parallel_workers: int = 4
    theseus_analysis: bool = True  # Run Theseus before planning
    # Model casting (edict 0002): None means the SDK default. "none" or "default" also unset.
    worker_model: Optional[str] = None
    judge_model: Optional[str] = None
    # Verification: build the .NET projects a diff touches (dotnet build) as their type check
    build_gate: bool = True
    # Per-language test commands replacing the built-in runners, e.g. {"TypeScript": ["pnpm", "vitest", "run"]}
    test_cmds: dict = field(default_factory=dict)


@dataclass
class GitConfig:
    """How the CLAUDE.md template tells Daedalus to commit."""
    # daedalus: commits authored as Daedalus (--author). user: authored as the configured git identity,
    # with a '- Daedalus' sign-off in the body (for repos where other people read the history).
    authorship: str = "daedalus"


@dataclass
class SectionsConfig:
    """Optional sections of the CLAUDE.md template."""
    squash: bool = True
    versioning: bool = True


@dataclass
class EdictsConfig:
    """Edicts: design decisions handed to Daedalus as docs (edict 0005). Off unless a project opts in."""
    enabled: bool = False


@dataclass
class DoctorConfig:
    """Thresholds for `daedalus doctor` (edict 0007)."""
    stale_commits: int = 10    # commits after the gameplan's last update before it counts as behind
    stale_task_days: int = 14  # days a task may sit in_progress before it is flagged


@dataclass
class HooksConfig:
    """Claude Code hooks that init/hydrate register (edicts 0007, 0009)."""
    session_start: bool = True  # gameplan-first brief at session start
    capture: bool = False       # SessionEnd/PreCompact: propose gameplan updates from commits
    board: bool = True          # UserPromptSubmit: note new posts in followed board threads (throttled)


@dataclass
class BoardConfig:
    """The agent board (edict 0009): threads between owners' agents on a git branch."""
    branch: str = "daedalus/board"
    remote: str = "origin"
    poll_minutes: int = 5  # the UserPromptSubmit hook checks at most this often


@dataclass
class ReconstructConfig:
    """Evidence gathering for memory reconstruction (edict 0006).

    Evidence paths outside git (e.g. gitignored run logs) are a list set in .daedalus/config.json:
    {"reconstruct": {"evidence_paths": ["projects/runs"]}}
    """
    score_threshold: int = 50  # commits whose message scores below this get their diff in the bundle
    sample_size: int = 3       # high-scoring commits that get diffs anyway, to check the score
    diff_cap: int = 8000       # max characters of patch per commit
    doc_paths: list = field(default_factory=lambda: ["docs/", "analyses/", "release-notes/", "CHANGELOG.md"])


@dataclass
class ReflectionConfig:
    """Reflection over session logs (edict 0010). Defaults are the edict's."""
    runner: str = "inhale"          # inhale | local | headless (local/headless need machine.employer false)
    model_summary: str = "ab"       # off | on | ab: the models at inhale, as an A/B test
    forget: str = "purge"           # purge | retain: what `forget` does to a user-model entry's history
    scope: str = "work"             # work | private: this project's scope (set per project; personal = private)
    share_private: bool = False     # show private model entries in work projects' inhale summary
    activity_threshold: int = 20    # a day with fewer tool calls is not due as a daily
    retry_window: int = 5           # tool calls after a failure in which the same call is a retry
    half_life_self: int = 60        # days
    half_life_user: int = 180       # days
    summary_tokens: int = 400       # cap on the inhale summary (estimated as characters / 4)
    cleanup_warning_days: int = 7   # doctor warns this many days before Claude Code's cleanup


@dataclass
class MachineConfig:
    """Facts about this machine. Set by the user; nothing infers them."""
    # Whether this is an employer's machine. Unset (None) is treated as an employer's on purpose:
    # the local and headless reflection runners run only when this is explicitly false.
    employer: Optional[bool] = None


@dataclass
class DreamConfig:
    """Dreaming (edict 0013). Off unless a project turns it on."""
    enabled: bool = False
    mode: str = "ab"            # list | narrative | plain | ab (drawn in code)
    seeds: int = 5
    turns: int = 4              # narrative mode: turns each for the Labyrinth and the dreamer
    max_tokens: int = 60000     # a dream that would pass this stops and is recorded as truncated
    temperature: Optional[str] = None          # no runner can set one yet; logged as unset
    waking_temperature: Optional[str] = None
    review_min: int = 4         # dreams since the last review before a review is due
    recur_min: int = 3          # dreams (with different top seeds) before a theme is elevated


@dataclass
class TuiConfig:
    """The Daedalus TUI (edict 0012)."""
    prs: str = "local"       # local: branches ahead of main; gh: the GitHub CLI
    escape: str = "ctrl+]"   # returns focus from the Claude pane to the dashboard
    backend: str = "auto"    # how the Claude pane hosts its session: auto (tmux if installed) | tmux | pty


# Allowed values for string settings (the registry in config_schema.py reads these)
SETTING_CHOICES = {
    "git.authorship": ("daedalus", "user"),
    "ariadne.autonomy": ("supervised", "hybrid", "full"),
    "tui.prs": ("local", "gh"),
    "tui.backend": ("auto", "tmux", "pty"),
    "dream.mode": ("list", "narrative", "plain", "ab"),
    "reflection.runner": ("inhale", "local", "headless"),
    "reflection.model_summary": ("off", "on", "ab"),
    "reflection.forget": ("purge", "retain"),
    "reflection.scope": ("work", "private", "personal"),
}

# Settings that hold true, false, or unset (null)
TRISTATE_SETTINGS = ("machine.employer",)

# Top-level config groups that template conditionals can read (and that project config may override)
TEMPLATE_SETTING_GROUPS = ("git", "sections", "edicts")

# Groups a project may override in .daedalus/config.json
PROJECT_SETTING_GROUPS = TEMPLATE_SETTING_GROUPS + ("doctor", "hooks", "reconstruct", "board", "reflection", "tui", "dream")


@dataclass
class DaedalusConfig:
    """Full Daedalus configuration."""
    user: UserConfig = field(default_factory=UserConfig)
    icarus: IcarusConfig = field(default_factory=IcarusConfig)
    ariadne: AriadneConfig = field(default_factory=AriadneConfig)
    git: GitConfig = field(default_factory=GitConfig)
    sections: SectionsConfig = field(default_factory=SectionsConfig)
    edicts: EdictsConfig = field(default_factory=EdictsConfig)
    doctor: DoctorConfig = field(default_factory=DoctorConfig)
    hooks: HooksConfig = field(default_factory=HooksConfig)
    reconstruct: ReconstructConfig = field(default_factory=ReconstructConfig)
    board: BoardConfig = field(default_factory=BoardConfig)
    reflection: ReflectionConfig = field(default_factory=ReflectionConfig)
    machine: MachineConfig = field(default_factory=MachineConfig)
    tui: TuiConfig = field(default_factory=TuiConfig)
    dream: DreamConfig = field(default_factory=DreamConfig)
    # Sources (edict 0011): {name: {key: value}}, free-form here and validated by config_schema
    sources: dict = field(default_factory=dict)


def get_config_dir() -> Path:
    """Get cross-platform config directory."""
    return Path(user_config_dir("daedalus"))


def get_cache_dir() -> Path:
    """Get cross-platform cache directory."""
    return Path(user_cache_dir("daedalus"))


def get_config_file() -> Path:
    """Get path to config.json."""
    return get_config_dir() / "config.json"


def get_git_user_email() -> Optional[str]:
    """Get user.email from git config."""
    try:
        result = subprocess.run(
            ["git", "config", "--global", "user.email"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def cast_model(value: Optional[str]) -> Optional[str]:
    """A configured model name, or None for the SDK default ("", "none", "default" also mean default)."""
    if value is None or str(value).strip().lower() in ("", "none", "default"):
        return None
    return str(value).strip()


def get_daedalus_email(config: Optional[DaedalusConfig] = None) -> str:
    """
    Get the email to use for Daedalus git commits.

    Priority:
    1. User-configured email in config
    2. Git user.email
    3. Fallback to daedalus@localhost
    """
    if config and config.user.email:
        return config.user.email

    git_email = get_git_user_email()
    if git_email:
        return git_email

    return "daedalus@localhost"


def load_config() -> DaedalusConfig:
    """Load configuration from disk."""
    config_file = get_config_file()

    if not config_file.exists():
        return DaedalusConfig()

    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        return DaedalusConfig(
            user=UserConfig(**data.get("user", {})),
            icarus=IcarusConfig(**data.get("icarus", {})),
            ariadne=AriadneConfig(**data.get("ariadne", {})),
            git=GitConfig(**data.get("git", {})),
            sections=SectionsConfig(**data.get("sections", {})),
            edicts=EdictsConfig(**data.get("edicts", {})),
            doctor=DoctorConfig(**data.get("doctor", {})),
            hooks=HooksConfig(**data.get("hooks", {})),
            reconstruct=ReconstructConfig(**data.get("reconstruct", {})),
            board=BoardConfig(**data.get("board", {})),
            reflection=ReflectionConfig(**data.get("reflection", {})),
            machine=MachineConfig(**data.get("machine", {})),
            tui=TuiConfig(**data.get("tui", {})),
            dream=DreamConfig(**data.get("dream", {})),
            sources=data["sources"] if isinstance(data.get("sources"), dict) else {},
        )
    except (json.JSONDecodeError, TypeError, KeyError):
        # Return defaults on any parse error
        return DaedalusConfig()


def save_config(config: DaedalusConfig) -> None:
    """Save configuration to disk."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "user": asdict(config.user),
        "icarus": asdict(config.icarus),
        "ariadne": asdict(config.ariadne),
        "git": asdict(config.git),
        "sections": asdict(config.sections),
        "edicts": asdict(config.edicts),
        "doctor": asdict(config.doctor),
        "hooks": asdict(config.hooks),
        "reconstruct": asdict(config.reconstruct),
        "board": asdict(config.board),
        "reflection": asdict(config.reflection),
        "machine": asdict(config.machine),
        "tui": asdict(config.tui),
        "dream": asdict(config.dream),
    }
    if config.sources:
        data["sources"] = config.sources

    get_config_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_nested_value(config: DaedalusConfig, key: str) -> Optional[str]:
    """
    Get a nested config value by dot-separated key.

    Example: get_nested_value(config, "user.name") -> config.user.name
    """
    parts = key.split(".")
    obj = config

    for part in parts:
        if isinstance(obj, dict):
            if part not in obj:
                return None
            obj = obj[part]
        elif hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None

    if isinstance(obj, (dict, list)):
        return json.dumps(obj)
    return str(obj) if obj is not None else None


def set_nested_value(config: DaedalusConfig, key: str, value: str) -> bool:
    """
    Set a nested config value by dot-separated key, validated against the config schema registry.

    Example: set_nested_value(config, "user.name", "Kohl")

    Returns True if successful, False for an unknown key or a value the setting doesn't take
    (`config_schema.check` says why).
    """
    from . import config_schema

    converted, error = config_schema.check(key, value, source_type(config.sources, key))
    if error:
        return False
    parts = key.split(".")
    if parts[0] == "sources":
        entry = config.sources.setdefault(parts[1], {})
        if converted is None:
            entry.pop(parts[2], None)
        else:
            entry[parts[2]] = converted
        return True
    setattr(getattr(config, parts[0]), parts[1], converted)
    return True


def source_type(*layers_and_key) -> Optional[str]:
    """The plugin type configured for the source a `sources.<name>.<key>` key names, from any of the given
    sources dicts (later ones win), or None. Called as source_type(sources_dict, ..., key)."""
    *layers, key = layers_and_key
    parts = key.split(".")
    if len(parts) < 2 or parts[0] != "sources":
        return None
    found = None
    for layer in layers:
        entry = layer.get(parts[1]) if isinstance(layer, dict) else None
        if isinstance(entry, dict) and entry.get("type"):
            found = entry["type"]
    return found


def setting_refusal(config: DaedalusConfig, key: str, value: str) -> Optional[str]:
    """Why a setting is refused even though the key and value are valid, or None (edict 0010)."""
    if key == "reflection.runner" and value in ("local", "headless") and config.machine.employer is not False:
        return (f"Refused: the {value} runner makes model calls outside your session, so it runs only on a "
                "machine marked as not an employer's. If this is your own machine, run "
                "`daedalus config machine.employer false` first.")
    return None


def get_project_config_file(project_dir: Path) -> Path:
    """Per-project overrides, deep-merged over the global config for template settings."""
    return Path(project_dir) / ".daedalus" / "config.json"


def load_project_overrides(project_dir: Path) -> dict:
    """Raw per-project overrides ({} when the file is missing or unreadable)."""
    path = get_project_config_file(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def set_project_value(project_dir: Path, key: str, value: str) -> bool:
    """
    Set a setting in the project config (.daedalus/config.json).

    Only PROJECT_SETTING_GROUPS and `sources.<name>.<key>` can be overridden per project. The value is
    validated and converted against the config schema registry. Returns False for an unknown key or a
    value the setting doesn't take.
    """
    from . import config_schema

    group = key.split(".")[0]
    if group not in PROJECT_SETTING_GROUPS and group != "sources":
        return False
    data = load_project_overrides(project_dir)
    stype = source_type(load_config().sources, data.get("sources", {}), key)
    converted, error = config_schema.check(key, value, stype)
    if error:
        return False

    node = data
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    if converted is None and group == "sources":
        node.pop(parts[-1], None)
    else:
        node[parts[-1]] = converted

    path = get_project_config_file(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def get_source_settings(project_dir: Path, name: str, config: Optional[DaedalusConfig] = None) -> dict:
    """One source's settings: the registry's defaults, then the global config, then the project's
    .daedalus/config.json (edict 0011). Keys the registry doesn't know are dropped."""
    from . import config_schema

    config = config or load_config()
    glob = config.sources.get(name, {}) if isinstance(config.sources.get(name), dict) else {}
    proj_all = load_project_overrides(project_dir).get("sources", {})
    proj = proj_all.get(name, {}) if isinstance(proj_all, dict) and isinstance(proj_all.get(name), dict) else {}
    stype = proj.get("type") or glob.get("type") or None
    schema = config_schema.source_settings(name, stype)
    out = {}
    for full, setting in schema.items():
        k = full.split(".")[-1]
        out[k] = proj.get(k, glob.get(k, setting.default))
    return out


def configured_source_names(project_dir: Path, config: Optional[DaedalusConfig] = None) -> list[str]:
    """Names of sources set in the global or project config, in order of first appearance."""
    config = config or load_config()
    proj = load_project_overrides(project_dir).get("sources", {})
    names = list(config.sources)
    if isinstance(proj, dict):
        names += [n for n in proj if n not in names]
    return names


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_template_settings(project_dir: Path, config: Optional[DaedalusConfig] = None) -> dict:
    """
    Settings the CLAUDE.md template's conditionals read: the global git and sections groups, with the
    project's .daedalus/config.json deep-merged over them. Only known keys are kept, so a typo in the
    project file can't add a setting the template doesn't know.
    """
    config = config or load_config()
    base = {group: asdict(getattr(config, group)) for group in TEMPLATE_SETTING_GROUPS}
    overrides = {k: v for k, v in load_project_overrides(project_dir).items() if k in TEMPLATE_SETTING_GROUPS}
    merged = _deep_merge(base, overrides)
    settings = {group: {k: v for k, v in merged[group].items() if k in base[group]} for group in base}
    settings["edicts"]["enabled"], _ = edicts_setting(project_dir)
    return settings


def _global_config_raw() -> dict:
    try:
        data = json.loads(get_config_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def edicts_setting(project_dir: Path) -> tuple[bool, str]:
    """
    Whether edicts are on for this project, and why: "project" or "global" when edicts.enabled is
    set there, "detected" when it is set nowhere but docs/edicts/ exists (so an upgrade never
    silently drops edicts from a project already using them), "default" otherwise (off).
    """
    project = load_project_overrides(project_dir).get("edicts", {})
    if isinstance(project, dict) and "enabled" in project:
        return bool(project["enabled"]), "project"
    glob = _global_config_raw().get("edicts", {})
    if isinstance(glob, dict) and "enabled" in glob:
        return bool(glob["enabled"]), "global"
    if (Path(project_dir) / "docs" / "edicts").is_dir():
        return True, "detected"
    return False, "default"


def get_project_settings(project_dir: Path, group: str, config: Optional[DaedalusConfig] = None) -> dict:
    """One config group (e.g. "doctor", "hooks") with the project's overrides merged over the global value."""
    config = config or load_config()
    base = asdict(getattr(config, group))
    override = load_project_overrides(project_dir).get(group, {})
    if not isinstance(override, dict):
        return base
    return {k: override.get(k, v) for k, v in base.items()}
