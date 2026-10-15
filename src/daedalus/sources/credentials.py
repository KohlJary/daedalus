"""
Source credentials (edict 0011): never in the repo or a config file.

A token comes from, in order:
1. the environment variable named by `sources.<name>.token_env`;
2. the system keyring (service "daedalus", user "source:<name>"), stored by `daedalus source login`;
3. for GitHub only, an authenticated `gh` CLI (`gh auth token`).
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

KEYRING_SERVICE = "daedalus"


def keyring_user(name: str) -> str:
    return f"source:{name}"


def from_keyring(name: str) -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, keyring_user(name)) or None
    except Exception:  # no keyring module, no backend, a locked keychain: just not available
        return None


def store(name: str, token: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, keyring_user(name), token)


def from_gh() -> Optional[str]:
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def token(name: str, settings: dict, gh_fallback: bool = False) -> Optional[str]:
    env = settings.get("token_env")
    if env and os.environ.get(env):
        return os.environ[env]
    found = from_keyring(name)
    if found:
        return found
    if gh_fallback:
        return from_gh()
    return None
