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
    """Claude Code hooks that init/hydrate register (edict 0007)."""
    session_start: bool = True  # gameplan-first brief at session start
    capture: bool = False       # SessionEnd/PreCompact: propose gameplan updates from commits


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


# Allowed values for string settings that the template branches on
SETTING_CHOICES = {
    "git.authorship": ("daedalus", "user"),
}

# Top-level config groups that template conditionals can read (and that project config may override)
TEMPLATE_SETTING_GROUPS = ("git", "sections", "edicts")

# Groups a project may override in .daedalus/config.json
PROJECT_SETTING_GROUPS = TEMPLATE_SETTING_GROUPS + ("doctor", "hooks", "reconstruct")


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
    }

    get_config_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_nested_value(config: DaedalusConfig, key: str) -> Optional[str]:
    """
    Get a nested config value by dot-separated key.

    Example: get_nested_value(config, "user.name") -> config.user.name
    """
    parts = key.split(".")
    obj = config

    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return None

    return str(obj) if obj is not None else None


def set_nested_value(config: DaedalusConfig, key: str, value: str) -> bool:
    """
    Set a nested config value by dot-separated key.

    Example: set_nested_value(config, "user.name", "Kohl")

    Returns True if successful, False if key path is invalid.
    """
    parts = key.split(".")

    if len(parts) < 2:
        return False

    # Navigate to parent object
    obj = config
    for part in parts[:-1]:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            return False

    # Set the final attribute
    final_key = parts[-1]
    if hasattr(obj, final_key):
        # Handle type conversion for boolean fields
        current_value = getattr(obj, final_key)
        if isinstance(current_value, bool):
            value = value.lower() in ("true", "1", "yes", "on")
        elif isinstance(current_value, int):
            try:
                value = int(value)
            except ValueError:
                return False
        elif key in SETTING_CHOICES and value not in SETTING_CHOICES[key]:
            return False
        setattr(obj, final_key, value)
        return True

    return False


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
    Set a template setting in the project config (.daedalus/config.json).

    Only PROJECT_SETTING_GROUPS (the template's git and sections, plus doctor and hooks) can be
    overridden per project. The value is
    validated and type-converted against the global config's field. Returns False for an unknown key
    or a value outside the allowed choices.
    """
    if key.split(".")[0] not in PROJECT_SETTING_GROUPS:
        return False
    probe = DaedalusConfig()
    if not set_nested_value(probe, key, value):
        return False
    converted = getattr(getattr(probe, key.split(".")[0]), key.split(".")[1])

    data = load_project_overrides(project_dir)
    node = data
    parts = key.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = converted

    path = get_project_config_file(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


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
