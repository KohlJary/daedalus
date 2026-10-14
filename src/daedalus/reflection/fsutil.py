"""Cross-platform file safety: atomic replace, a lock file, explicit UTF-8. No fcntl."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

STALE_LOCK_SECONDS = 60


def _mode_for(path: Path) -> int:
    """An existing file keeps its mode; a new one gets what open() would give it (0666 less umask)."""
    try:
        return stat.S_IMODE(os.stat(path).st_mode)
    except OSError:
        mask = os.umask(0)
        os.umask(mask)
        return 0o666 & ~mask


def atomic_write_text(path: Path, text: str, newline: str = "\n") -> None:
    """Write via a temporary file in the same directory, then os.replace (atomic on POSIX and Windows)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = _mode_for(path)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if os.name != "nt":
            os.chmod(tmp, mode)  # mkstemp makes 0600; don't change a project file's permissions
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


@contextmanager
def file_lock(path: Path, timeout: float = 10.0):
    """
    An exclusive lock held by creating `<path>.lock` with O_EXCL, which works the same on every OS.
    A lock older than STALE_LOCK_SECONDS is assumed abandoned (a crashed process) and taken over.
    """
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_LOCK_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() > deadline:
                raise TimeoutError(f"Could not lock {path} (held by another process: {lock})")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def append_line(path: Path, line: str) -> None:
    """Append one line (UTF-8, '\\n') and fsync. Callers hold file_lock when others may write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(line.rstrip("\n") + "\n")
        f.flush()
        os.fsync(f.fileno())
