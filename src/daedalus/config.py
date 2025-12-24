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
class DaedalusConfig:
    """Full Daedalus configuration."""
    user: UserConfig = field(default_factory=UserConfig)
    icarus: IcarusConfig = field(default_factory=IcarusConfig)
    ariadne: AriadneConfig = field(default_factory=AriadneConfig)


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
        data = json.loads(config_file.read_text())
        return DaedalusConfig(
            user=UserConfig(**data.get("user", {})),
            icarus=IcarusConfig(**data.get("icarus", {})),
            ariadne=AriadneConfig(**data.get("ariadne", {})),
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
    }

    get_config_file().write_text(json.dumps(data, indent=2))


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
        setattr(obj, final_key, value)
        return True

    return False
