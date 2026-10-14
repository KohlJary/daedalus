"""
How model-written reflection runs (edict 0010): `inhale` (default), `local`, or `headless`.

- inhale: nothing runs outside the user's session. Inhale asks; the session runs delphi.
- local: `tick` runs the daily level on the local model backend (T-e5). Until that exists it is
  unavailable, and reflection behaves as inhale.
- headless: `tick` runs due levels through `claude -p` on the user's own account.

local and headless run only when `machine.employer` is explicitly false. True or unset means
inhale: no model calls on an employer's machine beyond the session itself.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import DaedalusConfig, load_config


@dataclass
class Runner:
    configured: str
    effective: str
    reason: str = ""


def local_backend_available() -> bool:
    """The local model backend arrives with T-e5. Until then there is none."""
    try:
        from ..worker import local_backend  # type: ignore  # noqa: F401
    except ImportError:
        return False
    return True


def resolve_runner(config: Optional[DaedalusConfig] = None) -> Runner:
    config = config or load_config()
    configured = config.reflection.runner
    if configured == "inhale":
        return Runner(configured, "inhale")
    if config.machine.employer is not False:
        state = "unset" if config.machine.employer is None else "true"
        return Runner(configured, "inhale",
                      f"machine.employer is {state}, so only the inhale runner is allowed")
    if configured == "local" and not local_backend_available():
        return Runner(configured, "inhale", "the local runner is unavailable until the local model backend (T-e5) lands")
    if configured == "headless" and not find_claude():
        return Runner(configured, "inhale", "the headless runner needs `claude` on PATH")
    return Runner(configured, configured)


def find_claude() -> Optional[str]:
    """`claude`, or the `claude.cmd` shim on Windows, found the same way the shell finds it."""
    return shutil.which("claude")


# What an unattended /reflect may use: read anything, write reports, run the reflect CLI and
# read-only jq, and hand work to delphi and Momus. Nothing else.
HEADLESS_TOOLS = "Read Grep Glob Write Agent Bash(daedalus reflect:*) Bash(jq:*)"


def run_headless(project_dir: Path, prompt: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    claude = find_claude()
    if not claude:
        raise RuntimeError("claude is not on PATH")
    return subprocess.run([claude, "-p", prompt, "--allowedTools", HEADLESS_TOOLS], cwd=project_dir,
                          capture_output=True, text=True, encoding="utf-8", timeout=timeout)
