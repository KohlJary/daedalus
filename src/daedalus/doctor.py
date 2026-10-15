"""
Memory drift checks (edict 0007).

`daedalus doctor` compares the gameplan, edicts, and memory files against the repository and
reports where they have fallen behind. Every check is deterministic: git, the file system, and
JSON, no model calls. Each finding has a stable name so hooks and CI can key on it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from .cli import gameplan as gp
from .config import get_project_settings, load_project_overrides

EDICT_STATUSES = ("proposed", "accepted", "done")
EDICT_FILE = re.compile(r"^(\d{4})-.+\.md$")
STATUS_LINE = re.compile(r"^Status:\s*(.*?)\s*$", re.MULTILINE)

# Files the session-start hook reads, with the content `daedalus init` writes into them
SESSION_START_READS = {
    ".daedalus/session-summaries.md": "# Session Summaries",
    ".daedalus/roadmap/index.json": None,  # empty when it has no items
}

SKIP_DIRS = {"venv", ".venv", "env", "node_modules", "build", "dist", "site-packages", "__pycache__", "tests", "test"}


@dataclass
class Finding:
    name: str
    message: str


def _git(project_dir: Path, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", *args], cwd=project_dir, capture_output=True, text=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip()


def _is_git_repo(project_dir: Path) -> bool:
    return _git(project_dir, "rev-parse", "--is-inside-work-tree") == "true"


def _gameplan_rel(project_dir: Path, workstream: Optional[str] = None) -> str:
    return str(gp.GameplanPaths.for_project(project_dir, workstream).gameplan_file.relative_to(project_dir))


# ---------- gameplan ----------


def check_commits_after_gameplan(project_dir: Path, threshold: int, workstream: Optional[str] = None,
                                 author: Optional[str] = None) -> list[Finding]:
    """Commits since the plan last changed; for a workstream with an owner pattern, only theirs."""
    if not _is_git_repo(project_dir):
        return []
    rel = _gameplan_rel(project_dir, workstream)
    last = _git(project_dir, "log", "-1", "--format=%H %as", "--", rel)
    if not last:
        return []  # never committed: check_gameplan_ignored / untracked covers it
    sha, when = last.split()
    who = [f"--author={author}"] if author else []
    count = int(_git(project_dir, "rev-list", "--count", "--no-merges", *who, f"{sha}..HEAD") or 0)
    if count < threshold:
        return []
    whose = f" by {author}" if author else ""
    return [Finding(
        "commits-after-gameplan",
        f"{count} commits{whose} since the gameplan was last updated ({when}, {sha[:7]}). "
        "Record what shipped, or run /reconstruct.",
    )]


def check_phase_all_done(data: dict) -> list[Finding]:
    active = data.get("activePhase")
    if not active:
        return []
    tasks = active.get("tasks", [])
    phase = gp.find_phase(data, active.get("id", "")) or {}
    if tasks and all(t.get("status") == "done" for t in tasks) and phase.get("status", "in_progress") == "in_progress":
        return [Finding(
            "phase-tasks-all-done",
            f"Active phase {active.get('id')} is still in_progress but all {len(tasks)} tasks are done. "
            "Close it or add the remaining work.",
        )]
    return []


def check_stale_tasks(data: dict, max_days: int, today: Optional[date] = None) -> list[Finding]:
    active = data.get("activePhase")
    if not active:
        return []
    today = today or date.today()
    findings = []
    for task in active.get("tasks", []):
        if task.get("status") != "in_progress":
            continue
        since = task.get("updated") or active.get("started")
        try:
            age = (today - date.fromisoformat(since)).days
        except (TypeError, ValueError):
            continue
        if age > max_days:
            findings.append(Finding(
                "stale-task",
                f"Task {task.get('id')} has been in_progress for {age} days (since {since}).",
            ))
    return findings


def check_gameplan_ignored(project_dir: Path, workstream: Optional[str] = None) -> list[Finding]:
    if not _is_git_repo(project_dir):
        return []
    rel = _gameplan_rel(project_dir, workstream)
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", rel], cwd=project_dir, capture_output=True
        ).returncode == 0
    except FileNotFoundError:
        return []
    if ignored:
        return [Finding(
            "gameplan-ignored",
            f"{rel} is ignored by git, so the plan never leaves this machine. "
            "Run `daedalus init` to fix .gitignore, or un-ignore it by hand.",
        )]
    return []


# ---------- edicts ----------


def edicts_dir(project_dir: Path) -> Path:
    return project_dir / "docs" / "edicts"


def edicts_enabled(project_dir: Path) -> bool:
    """edicts.enabled (edict 0005): project, then global config, else whether docs/edicts/ exists."""
    from .config import edicts_setting

    return edicts_setting(project_dir)[0]


def load_edicts(project_dir: Path) -> list[dict]:
    """[{number, file, status}] for every docs/edicts/NNNN-*.md (README and dissents excluded)."""
    folder = edicts_dir(project_dir)
    if not folder.is_dir():
        return []
    edicts = []
    for path in sorted(folder.glob("*.md")):
        m = EDICT_FILE.match(path.name)
        if not m:
            continue
        status = STATUS_LINE.search(path.read_text(encoding="utf-8"))
        edicts.append({"number": m.group(1), "file": path.name, "status": status.group(1) if status else None})
    return edicts


def check_edict_status(edicts: list[dict]) -> list[Finding]:
    return [
        Finding(
            "edict-bad-status",
            f"{e['file']}: Status is {e['status']!r}, not one of {', '.join(EDICT_STATUSES)}.",
        )
        for e in edicts
        if (e["status"] or "").lower() not in EDICT_STATUSES
    ]


def check_duplicate_edicts(edicts: list[dict]) -> list[Finding]:
    by_number: dict[str, list[str]] = {}
    for e in edicts:
        by_number.setdefault(e["number"], []).append(e["file"])
    return [
        Finding("edict-duplicate-number", f"Edict {n} is used by {len(files)} files: {', '.join(files)}.")
        for n, files in sorted(by_number.items())
        if len(files) > 1
    ]


def _referenced_edicts(data: dict) -> set[str]:
    refs = set()
    entries = list(data.get("phases", []))
    active = data.get("activePhase") or {}
    entries += [active] + active.get("tasks", []) + active.get("deferred", [])
    for entry in entries:
        if entry.get("edict"):
            refs.add(str(entry["edict"]).zfill(4))
    return refs


def check_unreferenced_edicts(edicts: list[dict], data) -> list[Finding]:
    """data: one gameplan, or a list of them (every workstream)."""
    plans = data if isinstance(data, list) else [data]
    refs = set().union(*(_referenced_edicts(d) for d in plans)) if plans else set()
    return [
        Finding(
            "edict-not-in-gameplan",
            f"Accepted edict {e['number']} ({e['file']}) is not referenced by any gameplan phase or task.",
        )
        for e in edicts
        if (e["status"] or "").lower() == "accepted" and e["number"] not in refs
    ]


# ---------- memory files ----------


def _root_packages(project_dir: Path, max_depth: int = 4) -> list[Path]:
    """Python packages whose parent is not a package, skipping venvs, build output, and tests."""
    found = []

    def walk(folder: Path, depth: int):
        if depth > max_depth:
            return
        for child in sorted(folder.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS \
                    or child.name.endswith(".egg-info"):
                continue
            if (child / "__init__.py").exists():
                found.append(child)
            else:
                walk(child, depth + 1)

    walk(project_dir, 0)
    return found


def source_packages(project_dir: Path) -> list[str]:
    """Top-level source packages: the root packages, or a lone root package's direct subpackages."""
    roots = _root_packages(project_dir)
    if len(roots) == 1:
        subs = [c for c in sorted(roots[0].iterdir()) if c.is_dir() and (c / "__init__.py").exists()
                and c.name not in SKIP_DIRS]
        if subs:
            return [c.name for c in subs]
    return [r.name for r in roots]


def _is_empty_template(rel: str, text: str) -> bool:
    if rel.endswith("index.json"):
        try:
            return not json.loads(text).get("items")
        except (json.JSONDecodeError, AttributeError):
            return False
    return text.strip() == SESSION_START_READS[rel]


def check_project_map(project_dir: Path) -> list[Finding]:
    path = project_dir / ".daedalus" / "project-map.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    if text.strip() in ("", "# Project Map"):
        return []  # an empty map isn't stale, just unwritten
    lowered = text.lower()
    missing = [
        name for name in source_packages(project_dir)
        if name.lower() not in lowered and name.lower().replace("_", "-") not in lowered
    ]
    if not missing:
        return []
    return [Finding(
        "project-map-missing-packages",
        f"project-map.md doesn't mention {len(missing)} source package(s): {', '.join(missing)}.",
    )]


def session_start_hook_registered(project_dir: Path) -> bool:
    for name in ("settings.json", "settings.local.json"):
        path = project_dir / ".claude" / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if any(c in text for c in ("daedalus hook session-start", "daedalus-hook SessionStart", "session-start.sh")):
            return True
    return False


def check_empty_templates_read(project_dir: Path, max_days: int, today: Optional[date] = None) -> list[Finding]:
    """Empty templates the hook reads that have stayed empty past max_days (a fresh init is fine)."""
    if not session_start_hook_registered(project_dir):
        return []
    today = today or date.today()
    findings = []
    for rel in SESSION_START_READS:
        path = project_dir / rel
        if not path.exists() or not _is_empty_template(rel, path.read_text(encoding="utf-8")):
            continue
        age = (today - date.fromtimestamp(path.stat().st_mtime)).days
        if age > max_days:
            findings.append(Finding(
                "empty-file-read-by-hook",
                f"{rel} has been an empty template for {age} days, but the session-start hook reads it "
                "every session. Start using it, or stop the hook reading it.",
            ))
    return findings


# ---------- entry point ----------


def collisions(plans: dict) -> list[tuple[str, str, str, str]]:
    """Every collision between two workstreams' plans, as (kind, a, b, detail), a before b by ID:
    - ("edict", a, b, "0002"): both have open work citing edict 0002, one tuple per edict;
    - ("claims", a, b, "src/x/ / src/x/y.py; ..."): their path claims overlap, one tuple per pair of workstreams.
    `check_collisions` words these as findings; `oph map workstreams` draws them."""
    from . import workstreams as ws

    out: list[tuple[str, str, str, str]] = []
    ids = sorted(plans)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            for number in sorted(ws.open_edicts(plans[a]) & ws.open_edicts(plans[b])):
                out.append(("edict", a, b, number))
            pairs = sorted({(x, y) for x in plans[a].get("claims", []) or [] for y in plans[b].get("claims", []) or []
                            if ws.claims_overlap(x, y)})
            if pairs:
                listed = "; ".join(f"{x} / {y}" for x, y in pairs[:4]) + (" ..." if len(pairs) > 4 else "")
                out.append(("claims", a, b, listed))
    return out


def check_collisions(plans: dict) -> list[Finding]:
    """Two workstreams with open work citing the same edict, or with overlapping path claims."""
    findings = []
    for kind, a, b, detail in collisions(plans):
        if kind == "edict":
            findings.append(Finding(
                "collision-edict",
                f"Workstreams {a} and {b} both have open work on edict {detail}. Agree who takes what.",
            ))
        else:
            findings.append(Finding(
                "collision-claims",
                f"Workstreams {a} and {b} claim overlapping paths: {detail}.",
            ))
    return findings


def check_board_ask_rule(project_dir: Path) -> list[Finding]:
    """A project using the board must have the rule that makes every post ask its owner (0009)."""
    from .board import POST_PERMISSION

    if not (project_dir / ".daedalus" / "board").is_dir():
        return []
    for name in ("settings.json", "settings.local.json"):
        path = project_dir / ".claude" / name
        try:
            if POST_PERMISSION in json.loads(path.read_text(encoding="utf-8")).get("permissions", {}).get("ask", []):
                return []
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
    return [Finding("board-ask-rule-missing",
                    f"This checkout uses the board, but no permissions.ask rule \"{POST_PERMISSION}\" makes posts "
                    "ask the owner first. Run `daedalus hydrate` or add it to .claude/settings.json.")]


def check_undigested_sessions(project_dir: Path) -> list[Finding]:
    """Session transcripts Claude Code will delete soon that reflection hasn't digested (edict 0010)."""
    if not (Path(project_dir) / ".daedalus").is_dir():
        return []
    from .reflection.tick import cleanup_period_days, undigested_near_cleanup

    warning = int(get_project_settings(project_dir, "reflection")["cleanup_warning_days"])
    try:
        soon = undigested_near_cleanup(project_dir, warning)
    except OSError:
        return []
    if not soon:
        return []
    first = min(left for _, left in soon)
    return [Finding(
        "undigested-sessions-near-cleanup",
        f"{len(soon)} session transcript(s) not yet digested will be deleted by Claude Code's cleanup "
        f"(cleanupPeriodDays {cleanup_period_days()}) in {first} day(s) or less. Run `daedalus reflect digest`.",
    )]


def _installed_from() -> tuple[Optional[str], Optional[Path], bool]:
    """(installed version, local source directory it was installed from, editable) for daedalus-cli.
    The source is known when pip recorded a file:// direct_url (pip install <dir>, pip install -e <dir>)."""
    from importlib import metadata
    from urllib.parse import urlparse
    from urllib.request import url2pathname

    try:
        dist = metadata.distribution("daedalus-cli")
    except metadata.PackageNotFoundError:
        return None, None, False
    try:
        info = json.loads(dist.read_text("direct_url.json") or "{}")
    except (OSError, ValueError):
        info = {}
    url = info.get("url", "")
    if url.startswith("file:"):
        parsed = urlparse(url)
        path = url2pathname(parsed.path)  # url2pathname decodes %-escapes itself
        if parsed.netloc and parsed.netloc != "localhost":
            path = f"//{parsed.netloc}{path}"  # a UNC share
        return dist.version, Path(path), bool(info.get("dir_info", {}).get("editable"))
    if url:
        return dist.version, None, False  # installed from an index, a git URL, an archive: nothing local
    # An older editable install records no direct_url: the code runs straight from a checkout
    import daedalus
    checkout = Path(daedalus.__file__).resolve().parents[2]  # <checkout>/src/daedalus/__init__.py
    try:
        is_checkout = 'name = "daedalus-cli"' in (checkout / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        is_checkout = False
    return dist.version, (checkout if is_checkout else None), is_checkout


def _source_version(source: Path) -> Optional[str]:
    """`version` from the [project] table of the checkout's pyproject.toml."""
    try:
        text = (source / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', section.group(1), re.M) if section else None
    return m.group(1) if m else None


def _same_version(a: str, b: str) -> bool:
    """PEP 440 equality (0.2 == 0.2.0, 1.0rc1 == 1.0-rc.1), without depending on `packaging`."""
    try:
        from packaging.version import Version
        return Version(a) == Version(b)
    except Exception:
        pass

    def norm(v: str):
        v = v.lower().replace("-", "").replace("_", "").lstrip("v")
        m = re.match(r"(\d+(?:\.\d+)*)(.*)", v)
        if not m:
            return (v,)
        release = [int(x) for x in m.group(1).split(".")]
        while len(release) > 1 and release[-1] == 0:
            release.pop()
        return tuple(release) + (m.group(2).replace(".", ""),)
    return norm(a) == norm(b)


def _marker_holds(marker: str) -> bool:
    """Whether a PEP 508 environment marker holds here; unknown markers count as holding."""
    try:
        from packaging.markers import Marker

        return Marker(marker.strip()).evaluate()
    except Exception:
        return True


def _declared(source: Path) -> tuple[dict[str, set], set]:
    """({entry-point group: names}, dependency distribution names) that the checkout's pyproject.toml declares."""
    try:
        text = (source / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return {}, set()
    try:
        import tomllib  # Python 3.11+: real TOML, any formatting

        project = tomllib.loads(text).get("project", {})
        groups = {g: set(eps) for g, eps in (project.get("entry-points") or {}).items()}
        deps = set()
        for spec in project.get("dependencies") or []:
            name, _, marker = spec.partition(";")
            if marker.strip() and not _marker_holds(marker):
                continue  # e.g. tomli; python_version < '3.11' on a newer Python
            deps.add(re.split(r"[\s<>=!~\[(]", name.strip(), maxsplit=1)[0].lower().replace("_", "-"))
        return groups, deps
    except ImportError:
        pass
    except Exception:
        return {}, set()
    groups: dict[str, set] = {}
    for m in re.finditer(r'^\[project\.entry-points\."([^"]+)"\]\s*$(.*?)(?=^\[|\Z)', text, re.M | re.S):
        groups[m.group(1)] = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*=", m.group(2), re.M))
    deps = set()
    block = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.M | re.S)
    for m in re.finditer(r'^\s*"([A-Za-z0-9_.-]+)', block.group(1) if block else "", re.M):
        deps.add(m.group(1).lower().replace("_", "-"))
    return groups, deps


def check_install_metadata(source: Path, dist_name: str = "daedalus-cli") -> list[Finding]:
    """What the install's metadata lacks that the checkout declares (an editable install's metadata goes
    stale when entry points or dependencies are added later: same version, missing plugins), and any other
    distribution that also provides the `daedalus` package (an old install shadowing the new one)."""
    from importlib import metadata

    findings: list[Finding] = []
    groups, deps = _declared(source)
    try:
        installed = {(e.group, e.name) for e in metadata.distribution(dist_name).entry_points}
    except metadata.PackageNotFoundError:
        installed = set()
    missing_eps = sorted(f"{g}:{n}" for g, names in groups.items() for n in names if (g, n) not in installed)
    missing_deps = []
    for dep in sorted(deps):
        try:
            metadata.distribution(dep)
        except metadata.PackageNotFoundError:
            missing_deps.append(dep)
    if missing_eps or missing_deps:
        parts = []
        if missing_eps:
            parts.append(f"entry points {', '.join(missing_eps[:6])}" + (" ..." if len(missing_eps) > 6 else ""))
        if missing_deps:
            parts.append(f"dependencies {', '.join(missing_deps)}")
        findings.append(Finding(
            "install-stale",
            f"The installed daedalus-cli lacks {' and '.join(parts)} that {source}/pyproject.toml declares, so "
            f"plugins (sources, the TUI) won't load. Reinstall from {source} (pipx install --force --editable, "
            "or pip install -e in a venv)."))
    try:
        others = [d for d in metadata.packages_distributions().get("daedalus", []) if d != dist_name]
    except Exception:
        others = []
    for other in sorted(set(others)):
        try:
            ver = metadata.distribution(other).version
        except metadata.PackageNotFoundError:
            ver = "?"
        findings.append(Finding(
            "install-shadowed",
            f"Another distribution, '{other}' {ver}, also provides the daedalus package and can shadow daedalus-cli "
            f"(an old install). Uninstall it: pip uninstall {other} (add --break-system-packages on a system Python)."))
    return findings


def check_install(installed_from=_installed_from) -> list[Finding]:
    """The installed daedalus-cli is out of step with the local checkout it was installed from (a later
    `git pull` doesn't reinstall), or its palace grammars are missing."""
    import importlib.util

    findings: list[Finding] = []
    version, source, editable = installed_from()
    if version and source is not None:
        current = _source_version(source)
        if current and not _same_version(current, version):
            if editable:
                why = ("The code is live, but the install's metadata and dependencies are from the older version "
                       f"(new dependencies may be missing). Reinstall: pip install -e \"{source}\"")
            else:
                why = f"Reinstall to pick up its code and dependencies: pip install \"{source}\""
            findings.append(Finding(
                "install-stale", f"daedalus-cli {version} is installed from {source}, which is now at {current}. {why}"))
    if version and source is not None:
        findings += check_install_metadata(source)
    if version and importlib.util.find_spec("tree_sitter") is None:
        findings.append(Finding(
            "palace-grammars-missing",
            "tree-sitter isn't installed, so the palace only reads Python. It's a dependency of daedalus-cli: "
            "reinstall it.",
        ))
    return findings


def check_dispatch_rules(project_dir: Path) -> list[Finding]:
    """Dispatch rules the palace skips (malformed), and a shared rules file git ignores (so the team never
    gets it)."""
    from .labyrinth.query import _rule_ok, all_dispatch_rules

    findings: list[Finding] = []
    bad = [r for r in all_dispatch_rules(project_dir) if not _rule_ok(r)]
    if bad:
        findings.append(Finding(
            "palace-dispatch-invalid",
            f"{len(bad)} palace dispatch rule(s) are skipped: {', '.join(json.dumps(r) for r in bad[:3])}. "
            'A rule is {"publish": "Type.Method", "to": "enclosing:Iface.Method" or "Type.Method"} or '
            '{"factory": "Iface.Method", "entry": "Base.Method"}.'))
    shared = project_dir / ".daedalus" / "dispatch.json"
    if shared.is_file() and _is_git_repo(project_dir) and _git(project_dir, "check-ignore", "-q",
                                                                 ".daedalus/dispatch.json") is not None:
        findings.append(Finding(
            "palace-dispatch-ignored",
            ".daedalus/dispatch.json is ignored by git, so teammates won't get these rules. "
            "Run `daedalus hydrate`, or add `!.daedalus/dispatch.json` to .gitignore."))
    return findings


def check_hook_commands(project_dir: Path) -> list[Finding]:
    """Daedalus hooks registered with a command this machine can't run (edict 0016). Claude Code reports a
    missing command as a non-blocking error, so the hook would be silently dead: say so here instead."""
    import shutil

    missing: set[str] = set()
    for name in ("settings.json", "settings.local.json"):
        path = project_dir / ".claude" / name
        try:
            hooks = json.loads(path.read_text(encoding="utf-8")).get("hooks", {})
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        for groups in hooks.values() if isinstance(hooks, dict) else []:
            for group in groups if isinstance(groups, list) else []:
                for h in group.get("hooks", []) if isinstance(group, dict) else []:
                    words = str(h.get("command", "") if isinstance(h, dict) else "").split()
                    if words and words[0] in ("daedalus-hook", "daedalus") and shutil.which(words[0]) is None:
                        missing.add(words[0])
    return [Finding("hook-command-missing",
                    f"Hooks in .claude/ run `{cmd}`, which isn't on this machine's PATH, so they fail silently. "
                    "Reinstall daedalus-cli (pip install -e, or pipx), then run `daedalus hydrate`.")
            for cmd in sorted(missing)]


def run_checks(project_dir: Path, today: Optional[date] = None) -> tuple[list[Finding], list[str]]:
    """(findings, hints). Hints are informational and never fail the run."""
    from . import workstreams as ws

    project_dir = Path(project_dir)
    settings = get_project_settings(project_dir, "doctor")
    findings: list[Finding] = []
    hints: list[str] = []

    plans: dict = {}
    ids = ws.list_ids(project_dir)
    if not ids:
        hints.append("No gameplan in this project. `daedalus init` creates one.")
    several = len(ids) > 1
    for wid in ids:
        label = (lambda f, wid=wid: Finding(f.name, f"[{wid}] {f.message}")) if several else (lambda f: f)
        try:
            data = gp.load_gameplan(project_dir, wid)
        except gp.GameplanError as e:
            findings.append(label(Finding("gameplan-unreadable", str(e))))
            continue
        plans[wid] = data
        author = ws.owner(data, wid).get("git_author") if wid != ws.DEFAULT else None
        if author and _is_git_repo(project_dir) and not ws.author_pattern_ok(project_dir, author):
            findings.append(label(Finding(
                "workstream-author-invalid",
                f"git_author {author!r} is not a pattern git accepts, so this workstream's drift can't be measured.",
            )))
            author = None
        elif several and wid != ws.DEFAULT and not author:
            hints.append(f"Workstream {wid} has no git_author, so its drift counts every author's commits.")
        found = check_commits_after_gameplan(project_dir, settings["stale_commits"], wid, author)
        found += check_phase_all_done(data)
        found += check_stale_tasks(data, settings["stale_task_days"], today=today)
        found += check_gameplan_ignored(project_dir, wid)
        findings += [label(f) for f in found]
    findings += check_collisions(plans)

    edicts = load_edicts(project_dir)
    findings += check_edict_status(edicts)
    findings += check_duplicate_edicts(edicts)
    if plans and edicts_enabled(project_dir):
        findings += check_unreferenced_edicts(edicts, list(plans.values()))

    findings += check_board_ask_rule(project_dir)
    findings += check_undigested_sessions(project_dir)
    findings += check_dispatch_rules(project_dir)
    # The install, not the project: reported as hints, so a machine's setup never fails a project's CI.
    # DAEDALUS_DOCTOR_SKIP_INSTALL turns it off (the test suite does).
    if not os.environ.get("DAEDALUS_DOCTOR_SKIP_INSTALL"):
        hints += [f"{f.name}: {f.message}" for f in check_install()]
        hints += [f"{f.name}: {f.message}" for f in check_hook_commands(project_dir)]
    from . import epitaphs as _ep

    hints += [f"intake-dropped-repeatedly: '{r['title']}' was dropped {r['count']} times (from {', '.join(r['sources'])}). "
              "An unmet need, or a decision worth writing down. `daedalus roadmap epitaphs --recurring`"
              for r in _ep.recurring(project_dir)]
    hints += edict_test_hints(project_dir, edicts)
    findings += check_project_map(project_dir)
    findings += check_empty_templates_read(project_dir, settings["stale_task_days"], today=today)
    findings += check_sources(project_dir, plans)
    findings += check_design_diagrams(project_dir)
    return findings, hints


def check_design_diagrams(project_dir: Path) -> list[Finding]:
    """Design diagrams under docs/design that don't pass `daedalus oph check` (edict 0017).

    Joins, widths, box styles and slugs are always checked. An unresolved `◆Name` is reported only when the project
    sets `oph.components` (`daedalus config set oph.components ...`): without it doctor can't know the code's
    components, and a fresh clone would report every widget the designs name. That setting lives in the untracked
    `.daedalus/config.json`; there is no committed per-project default for it."""
    design = Path(project_dir) / "docs" / "design"
    if not design.is_dir():
        return []
    from .ophanic.lint import check_paths, components_from_package

    known: set[str] = set()
    configured = get_project_settings(project_dir, "oph").get("components") or []
    for c in configured:
        p = Path(project_dir) / c
        known |= components_from_package(p) if p.is_dir() else {c}
    problems = check_paths([design], known)
    if not configured:
        problems = [p for p in problems if p.kind != "components"]
    if not problems:
        return []
    first = problems[0]
    return [Finding("design-diagram-invalid",
                    f"{len(problems)} problem(s) in design diagrams, e.g. {first.path}:{first.line}: {first.message}. "
                    "Run `daedalus oph check docs/design`.")]


# ---------- sources (edict 0011) ----------
#
# From the last sync's state, the roadmap index and the plans: no network, no plugin imports, so the
# session-start hook can run them too.


def check_sources(project_dir: Path, plans: Optional[dict] = None) -> list[Finding]:
    """A source that couldn't authenticate or reach its server at its last sync; an item the tracker has
    closed that is still open here; a done task whose write-back is neither pending nor recorded."""
    from . import roadmap
    from .sources import state as source_state

    project_dir = Path(project_dir)
    states = source_state.load(project_dir)
    findings: list[Finding] = []
    for name, entry in sorted(states.items()):
        health = entry.get("health")
        if health == "auth-failed":
            findings.append(Finding("source-auth-failed", f"Source {name} couldn't authenticate at its last sync "
                                    f"({entry.get('last_attempt', '?')}): {entry.get('error', '')} "
                                    f"Fix the token (`daedalus source login {name}`), then `daedalus source sync {name}`."))
        elif health == "unreachable":
            findings.append(Finding("source-unreachable", f"Source {name} couldn't be reached at its last sync "
                                    f"({entry.get('last_attempt', '?')}): {entry.get('error', '')}"))
    try:
        index = roadmap.load_index(project_dir)
    except roadmap.RoadmapError:
        return findings
    items = {i.get("id"): i for i in index.get("items", [])}
    for item in index.get("items", []):
        if not roadmap.is_sourced(item):
            continue
        seen = (item.get("synced") or {}).get("fields", {})
        if seen.get("status") == "done" and item.get("status") != "done":
            o = roadmap.origin(item)
            findings.append(Finding("source-drift", f"Roadmap item {item.get('id')} is closed in {o['source']} "
                                    f"({o.get('external_id')}) but {item.get('status')} here. Apply its pending "
                                    "update, or mark it done (`daedalus roadmap show` it first)."))

    if plans is None:
        from . import workstreams as ws

        plans = {}
        for wid in ws.list_ids(project_dir):
            try:
                plans[wid] = gp.load_gameplan(project_dir, wid)
            except gp.GameplanError:
                continue
    writable = {n for n, e in states.items() if e.get("supports_write_back")}
    if not writable:
        return findings
    pending_keys = set()
    for wid in plans:
        path = gp.GameplanPaths.for_project(project_dir, wid).pending_file
        try:
            props = json.loads(path.read_text(encoding="utf-8")).get("proposals", []) if path.exists() else []
        except (OSError, ValueError, AttributeError):
            props = []
        for p in props:
            if p.get("kind") == "write-back":
                pending_keys.add(p.get("task"))
    for wid, data in plans.items():
        for _, task in roadmap.all_tasks(data):
            if task.get("status") != "done" or task.get("writeBack") or task.get("id") in pending_keys:
                continue
            origin = task.get("origin") if isinstance(task.get("origin"), dict) else None
            item = items.get(task.get("roadmapItem"))
            if not origin or origin.get("source") in (None, "local"):
                if item is None or not roadmap.is_sourced(item) or (item.get("synced") or {}).get("write_back"):
                    continue
                origin = roadmap.origin(item)
            if origin["source"] not in writable:
                continue
            findings.append(Finding("source-write-back-missing", f"[{wid}] Task {task.get('id')} is done, but nothing "
                                    f"was written back to {origin['source']} {origin.get('external_id')} and no "
                                    "write-back is pending or recorded. Set it done again with "
                                    "`daedalus gameplan task status` to propose one, then apply or drop it."))
    return findings


def edict_test_hints(project_dir: Path, edicts: list[dict]) -> list[str]:
    """Hints, never findings: an accepted edict whose criteria tests (tests/edicts/) are still skeletons."""
    from . import edict_tests as et

    hints = []
    for e in edicts:
        if e.get("status") != "accepted" or not et.skeleton_path(project_dir, e["number"]).exists():
            continue
        try:
            state = et.status(project_dir, e["number"])
        except Exception:
            continue
        open_ = [cid for cid, s in state.items() if s != "tested"]
        if open_:
            hints.append(f"edict-criteria-untested: edict {e['number']} has {len(open_)} of {len(state)} acceptance "
                         f"criteria without a real test (`daedalus edict tests {e['number']}`)")
    return hints

