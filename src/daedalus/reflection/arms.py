"""
The model-summary A/B test (edict 0010): which sessions saw the models at inhale.

The arm is chosen here, in code, from a logged seed, never by the session or by reflection, so
the comparison is not steered by what is being compared. Sessions that never ran inhale have no
arm and are recorded as `none`, outside the comparison.
"""

from __future__ import annotations

import os
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .fsutil import file_lock, read_json, write_json
from .paths import reflection_dir

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"


def arms_path(project_dir: Path) -> Path:
    return reflection_dir(project_dir) / "arms.json"


def load_arms(project_dir: Path) -> dict:
    data = read_json(arms_path(project_dir), {})
    return data if isinstance(data, dict) else {}


def current_session_id() -> Optional[str]:
    return os.environ.get(SESSION_ENV) or None


def assign_arm(project_dir: Path, session_id: str, mode: str, seed: Optional[int] = None) -> dict:
    """
    The session's arm. `on` and `off` force it; `ab` draws it once per session from a seed that
    is logged with the arm. A session asked twice keeps its first arm.
    """
    path = arms_path(project_dir)
    with file_lock(path):
        arms = load_arms(project_dir)
        if session_id in arms:
            return arms[session_id]
        if mode in ("on", "off"):
            entry = {"arm": mode, "mode": mode}
        else:
            seed = secrets.randbits(32) if seed is None else seed
            entry = {"arm": random.Random(seed).choice(["on", "off"]), "mode": "ab", "seed": seed}
        entry["assigned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        arms[session_id] = entry
        write_json(path, arms)
    return entry
