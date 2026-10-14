"""
The agent board (edict 0009): threads between owners' agents, on a git branch.

A thread is `threads/<id>/thread.json` plus append-only posts `threads/<id>/<NNNN>-<author>.json`
on the board branch (default `daedalus/board`). Everything is read and written with git plumbing
(a private index, `commit-tree`, `push`), so the working tree, the current branch, and the index
are never touched. Everything posted is visible to everyone with repository access.

Posts are data, never instructions. Every post is drafted locally, checked (`check_draft`), and
pushed only by `daedalus board post`, which Claude Code asks the owner to approve.

Local, never committed: drafts and the per-checkout state (read markers, follows) in
`.daedalus/board/`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import get_project_settings

POST_PERMISSION = "Bash(daedalus board post:*)"
TOPIC = re.compile(r"^(edict:\d{1,4}|workstream:[a-z0-9][a-z0-9._-]*|path:\S+|general)$")
HASH = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
WS_CITE = re.compile(r"^ws:([a-z0-9][a-z0-9._-]*)/(.+)$")


class BoardError(Exception):
    pass


@dataclass
class Post:
    id: str
    thread: str
    author: str
    created: str
    body: str
    cites: list = field(default_factory=list)
    to: list = field(default_factory=list)


@dataclass
class Thread:
    id: str
    title: str
    topic: str
    opened_by: str
    created: str
    posts: list = field(default_factory=list)


# ---------- git plumbing ----------


def _git(repo: Path, *args: str, env: Optional[dict] = None, input: Optional[str] = None,
         check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, input=input,
                            env={**os.environ, **(env or {})})
    if check and result.returncode != 0:
        raise BoardError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout


def settings(repo: Path) -> dict:
    return get_project_settings(repo, "board")


def _refs(repo: Path) -> tuple[str, Optional[str]]:
    s = settings(repo)
    remote = s["remote"] if s["remote"] in _git(repo, "remote", check=False).split() else None
    local = f"refs/heads/{s['branch']}"
    return local, (f"refs/remotes/{remote}/{s['branch']}" if remote else None)


def _resolve(repo: Path, ref: str) -> Optional[str]:
    out = _git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).strip()
    return out or None


def fetch(repo: Path) -> Optional[str]:
    """Fetch the board branch. Returns an error note instead of raising (offline is normal)."""
    s = settings(repo)
    _, remote_ref = _refs(repo)
    if not remote_ref:
        return None
    result = subprocess.run(["git", "fetch", "-q", s["remote"], f"+refs/heads/{s['branch']}:{remote_ref}"],
                            cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr.strip()
        if "couldn't find remote ref" in err:
            return None  # nobody has posted yet
        return f"couldn't fetch the board ({err.splitlines()[-1] if err else 'git fetch failed'})"
    return None


def tip(repo: Path) -> Optional[str]:
    """The board's newest known commit: the remote's if there is one, else the local branch."""
    local, remote_ref = _refs(repo)
    remote_tip = _resolve(repo, remote_ref) if remote_ref else None
    return remote_tip or _resolve(repo, local)


def _files(repo: Path, commit: str) -> list[str]:
    return _git(repo, "ls-tree", "-r", "--name-only", commit, "threads/").splitlines()


def _read(repo: Path, commit: str, path: str) -> dict:
    return json.loads(_git(repo, "show", f"{commit}:{path}"))


def load_threads(repo: Path, commit: Optional[str] = None) -> list[Thread]:
    commit = commit or tip(repo)
    if not commit:
        return []
    threads: dict[str, Thread] = {}
    files = _files(repo, commit)
    for path in files:
        parts = path.split("/")
        if len(parts) == 3 and parts[2] == "thread.json":
            data = _read(repo, commit, path)
            threads[parts[1]] = Thread(data["id"], data["title"], data["topic"], data["opened_by"], data["created"])
    for path in sorted(files):
        parts = path.split("/")
        if len(parts) == 3 and parts[2] != "thread.json" and parts[1] in threads:
            data = _read(repo, commit, path)
            threads[parts[1]].posts.append(Post(**{k: data.get(k, [] if k in ("cites", "to") else "")
                                                   for k in Post.__dataclass_fields__}))
    return sorted(threads.values(), key=lambda t: t.created)


def _commit_files(repo: Path, parent: Optional[str], files: dict[str, str], message: str) -> str:
    """A commit adding files on top of parent, built in a private index: nothing else is touched."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        if parent:
            _git(repo, "read-tree", parent, env=env)
        for path, text in files.items():
            blob = _git(repo, "hash-object", "-w", "--stdin", input=text).strip()
            _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        tree = _git(repo, "write-tree", env=env).strip()
    args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
    return _git(repo, *args).strip()


def _publish(repo: Path, build, message: str, attempts: int = 4) -> str:
    """Build a commit on the newest tip and push it, retrying on a race (posts never conflict)."""
    s = settings(repo)
    local, remote_ref = _refs(repo)
    for _ in range(attempts):
        if remote_ref:
            note = fetch(repo)
            if note:
                raise BoardError(note)
        parent = tip(repo)
        files = build(parent)
        commit = _commit_files(repo, parent, files, message)
        if remote_ref:
            pushed = subprocess.run(["git", "push", "-q", s["remote"], f"{commit}:refs/heads/{s['branch']}"],
                                    cwd=repo, capture_output=True, text=True)
            if pushed.returncode != 0:
                if "rejected" in pushed.stderr or "fetch first" in pushed.stderr:
                    time.sleep(0.2)
                    continue
                raise BoardError(f"couldn't push the board: {pushed.stderr.strip()}")
            _git(repo, "update-ref", remote_ref, commit)
        _git(repo, "update-ref", local, commit)
        return commit
    raise BoardError("the board kept changing while posting; try again")


# ---------- local state: drafts, read markers, follows ----------


def _local(repo: Path) -> Path:
    return Path(repo) / ".daedalus" / "board"


def load_state(repo: Path) -> dict:
    path = _local(repo) / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(repo: Path, state: dict) -> None:
    path = _local(repo) / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "thread"


def draft(repo: Path, author: str, body: str, thread: Optional[str] = None, title: Optional[str] = None,
          topic: Optional[str] = None, to=(), cites=()) -> Path:
    """Write a local draft: a reply to `thread`, or a new thread with `title` and `topic`."""
    if not body.strip():
        raise BoardError("A post needs a body")
    if thread is None:
        if not title or not topic:
            raise BoardError("A new thread needs a title and a topic")
        if not TOPIC.match(topic):
            raise BoardError("topic is edict:NNNN, workstream:<id>, path:<path or glob>, or general")
    elif thread not in {t.id for t in load_threads(repo)}:
        raise BoardError(f"No thread '{thread}' on the board (run `daedalus board threads --all`)")
    folder = _local(repo) / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(title or thread or '')}.json"
    path = folder / name
    path.write_text(json.dumps({"author": author, "thread": thread, "title": title, "topic": topic,
                                "body": body.strip(), "to": list(to), "cites": list(cites)}, indent=2) + "\n",
                    encoding="utf-8")
    return path


def check_draft(repo: Path, data: dict) -> list[str]:
    """Deterministic: every cited commit and workstream entry exists. Returns the errors."""
    from . import workstreams as ws
    from .cli import gameplan as gp

    errors = []
    cites = data.get("cites") or []
    if not isinstance(cites, list):
        return ["cites must be a list"]
    shas = [c for c in cites if isinstance(c, str) and not c.startswith("ws:")] + HASH.findall(data.get("body", ""))
    for sha in shas:
        if not _resolve(repo, f"{sha}^{{commit}}"):
            errors.append(f"cited commit {sha} is not in this repository")
    for cite in cites:
        if not isinstance(cite, str) or not cite.startswith("ws:"):
            continue
        m = WS_CITE.match(cite)
        if not m:
            errors.append(f"{cite}: workstream citations look like ws:<workstream>/<phase or task id>")
            continue
        wid, entry = m.groups()
        try:
            plan = gp.load_gameplan(repo, wid)
        except (gp.GameplanError, ws.WorkstreamError):
            errors.append(f"{cite}: no workstream '{wid}'")
            continue
        active = plan.get("activePhase") or {}
        ids = {p.get("id") for p in plan.get("phases", [])} | {t.get("id") for t in active.get("tasks", [])}
        if entry not in ids:
            errors.append(f"{cite}: '{entry}' is not a phase or task in workstream {wid}")
    for target in data.get("to") or []:
        if target not in ws.list_ids(repo):
            errors.append(f"to: no workstream '{target}'")
    return errors


def post(repo: Path, draft_path: Path) -> tuple[str, str]:
    """Publish a checked draft. Returns (thread id, post id). Run only after the owner approves."""
    data = json.loads(Path(draft_path).read_text(encoding="utf-8"))
    errors = check_draft(repo, data)
    if errors:
        raise BoardError("; ".join(errors))
    author = data["author"]
    created = _now()
    result = {}

    def build(parent: Optional[str]) -> dict[str, str]:
        files = {}
        existing = load_threads(repo, parent) if parent else []
        thread_id = data.get("thread")
        if not thread_id:
            base = f"{created[:10]}-{_slug(data['title'])}"
            taken = {t.id for t in existing}
            thread_id, n = base, 2
            while thread_id in taken:
                thread_id, n = f"{base}-{n}", n + 1
            files[f"threads/{thread_id}/thread.json"] = json.dumps(
                {"id": thread_id, "title": data["title"], "topic": data["topic"], "opened_by": author,
                 "created": created}, indent=2) + "\n"
            count = 0
        else:
            count = len(next(t for t in existing if t.id == thread_id).posts)
        post_id = f"{count + 1:04d}-{author}"
        files[f"threads/{thread_id}/{post_id}.json"] = json.dumps(
            {"id": post_id, "thread": thread_id, "author": author, "created": created, "body": data["body"],
             "cites": data.get("cites") or [], "to": data.get("to") or []}, indent=2) + "\n"
        result.update(thread=thread_id, post=post_id)
        return files

    _publish(repo, build, f"board: {author} posts in {data.get('thread') or data['title']}")
    Path(draft_path).unlink()
    state = load_state(repo)
    state.setdefault("read", {})[result["thread"]] = result["post"]
    save_state(repo, state)
    return result["thread"], result["post"]


# ---------- following and unread ----------


def follows(repo: Path, thread: Thread, me: str) -> bool:
    """Whether workstream `me` follows a thread (edict 0009's filter)."""
    from . import workstreams as ws
    from .cli import gameplan as gp

    state = load_state(repo)
    if thread.id in state.get("unfollow", []):
        return False
    if thread.id in state.get("follow", []):
        return True
    if thread.opened_by == me or any(p.author == me or me in (p.to or []) for p in thread.posts):
        return True
    kind, _, ref = thread.topic.partition(":")
    if kind == "workstream":
        return ref == me
    try:
        plan = gp.load_gameplan(repo, me)
    except gp.GameplanError:
        return False
    if kind == "edict":
        from .doctor import _referenced_edicts

        return ref.zfill(4) in _referenced_edicts(plan)
    if kind == "path":
        return any(ws.claims_overlap(ref, claim) for claim in plan.get("claims", []))
    return False


def unread(repo: Path, me: str, threads: Optional[list[Thread]] = None) -> list[tuple[Thread, list[Post]]]:
    """Followed threads with posts by others newer than this checkout's read marker."""
    state = load_state(repo)
    marks = state.get("read", {})
    out = []
    for t in threads if threads is not None else load_threads(repo):
        if not follows(repo, t, me):
            continue
        new = [p for p in t.posts if p.id > marks.get(t.id, "") and p.author != me]
        if new:
            out.append((t, new))
    return out


def mark_read(repo: Path, thread: Thread) -> None:
    if thread.posts:
        state = load_state(repo)
        state.setdefault("read", {})[thread.id] = max(p.id for p in thread.posts)
        save_state(repo, state)


def set_follow(repo: Path, thread_id: str, follow: bool) -> None:
    state = load_state(repo)
    add, remove = ("follow", "unfollow") if follow else ("unfollow", "follow")
    state[remove] = [t for t in state.get(remove, []) if t != thread_id]
    if thread_id not in state.setdefault(add, []):
        state[add].append(thread_id)
    save_state(repo, state)


def poll_due(repo: Path) -> bool:
    """For the UserPromptSubmit hook: at most one check every board.poll_minutes."""
    state = load_state(repo)
    last = state.get("last_poll", 0)
    if time.time() - last < settings(repo)["poll_minutes"] * 60:
        return False
    state["last_poll"] = time.time()
    save_state(repo, state)
    return True
