"""
Which files the palace reads, and what each one is called.

Every palace scanner (query graph, palace builder, orphan detector, annotation scan, proposals) walks
the tree through `source_files`, so they agree on what's in scope:

- Directories in SKIP_DIRS are never entered (virtualenvs, node_modules, caches, build output).
- Untracked paths git ignores are skipped; tracked files and submodules stay in. Outside a git
  repository this does nothing.
- Non-Python files also skip other ecosystems' build/vendor directories, minified bundles, and
  anything over MAX_FILE_BYTES. Python files keep the rules they always had.
"""

import logging
import os
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Set

logger = logging.getLogger(__name__)

SKIP_DIRS = {"node_modules", "venv", ".venv", "env", "__pycache__", ".git", "dist", "build", ".mind-palace"}
# Build output and vendored dependencies of other ecosystems. Applied to non-Python files only, so Python
# results stay as they were; .gitignore usually covers these anyway.
OTHER_SKIP_DIRS = {".next", ".nuxt", ".svelte-kit", ".output", "bower_components", "target", "vendor", "coverage",
                   ".gradle", "Pods", "DerivedData"}
MAX_FILE_BYTES = 1_000_000  # non-Python sources this big are generated or minified bundles
PYTHON_EXTS = (".py", ".pyi")


def git_ignored(project_root: Path) -> Set[str]:
    """Untracked paths git ignores, relative to project_root (directories end in /). Empty outside git.
    Tracked files are never listed, even when they match an ignore rule."""
    project_root = Path(project_root)
    try:
        r = subprocess.run(["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
                           cwd=project_root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    if r.returncode != 0:
        if (project_root / ".git").exists():  # a repo git couldn't read (dubious ownership, ...): say so
            logger.warning(f"palace: git ls-files failed, .gitignore not applied: {r.stderr.strip()}")
        return set()
    return set(filter(None, r.stdout.split("\0")))


def keep_file(path: Path, rel: Path) -> bool:
    """The per-file rules beyond directory pruning: non-Python generated, vendored or oversized files."""
    if path.suffix in PYTHON_EXTS:
        return True
    if path.name.endswith((".min.js", ".bundle.js")) or OTHER_SKIP_DIRS & set(rel.parts):
        return False
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def source_files(project_root: Path, extensions: Iterable[str], under: Optional[Path] = None,
                 ignored: Optional[Set[str]] = None) -> List[Path]:
    """Source files with the given extensions (matched case-sensitively), sorted. `under` limits the walk
    to a subdirectory; paths stay relative to project_root for ignore matching."""
    project_root = Path(project_root).resolve()
    start = Path(under).resolve() if under is not None else project_root
    exts = set(extensions)
    if ignored is None:
        ignored = git_ignored(project_root)
    if start != project_root and is_ignored_dir(start.relative_to(project_root).as_posix(), ignored):
        return []
    files = []
    for dirpath, dirnames, filenames in os.walk(start):
        rel_dir = Path(dirpath).relative_to(project_root).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and f"{prefix}{d}/" not in ignored)
        for n in filenames:
            if os.path.splitext(n)[1] not in exts or f"{prefix}{n}" in ignored:
                continue
            path = Path(dirpath) / n
            if keep_file(path, path.relative_to(project_root)):
                files.append(path)
    return sorted(files)


def is_ignored_dir(rel_dir: str, ignored: Set[str]) -> bool:
    """The directory, or one it sits in, is git-ignored (git reports an ignored directory, not its files)."""
    parts = rel_dir.strip("/").split("/")
    return any("/".join(parts[: i + 1]) + "/" in ignored for i in range(len(parts)))


def is_ignored(rel_path: str, ignored: Set[str]) -> bool:
    """The file is git-ignored, itself or through a directory it sits in."""
    return rel_path in ignored or ("/" in rel_path and is_ignored_dir(rel_path.rsplit("/", 1)[0], ignored))


def module_id(rel: Path) -> str:
    """Python modules are dotted paths (pkg/mod.py -> pkg.mod); other languages keep their extension
    (src/view.ts -> src.view.ts), so a same-stem file in another language can't collide with it."""
    rel = Path(rel)
    return str(rel.with_suffix("") if rel.suffix in PYTHON_EXTS else rel).replace(os.sep, ".").replace("/", ".")
