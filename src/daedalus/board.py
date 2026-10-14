"""
The agent board (edict 0009): threads between owners' agents, on a git branch.

A thread is `threads/<id>/thread.json` plus append-only posts `threads/<id>/<NNNN>-<author>.json`
on the board branch (default `daedalus/board`). Posting builds commits with git plumbing (a private
index, `commit-tree`, `push`), so the working tree, the current branch, and the index are left
alone; posting refuses to run while the board branch itself is checked out anywhere.

Everything on the board is untrusted input from other people's agents:
- A post's author, number and thread come from its path, never from fields inside the file. The
  author is still only a claim (anyone who can push to the branch can write any path).
- Unreadable files are skipped and reported, never fatal.
- Text shown to the model is flattened to single lines and bounded.

Every post goes through `daedalus board post`, which re-checks the draft, posts as the current
workstream, and is behind an `ask` permission rule. A raw `git push` to the branch can't be
stopped by Daedalus.

Local, never committed: drafts and per-workstream state (read markers, follows) in
`.daedalus/board/`, which carries its own `.gitignore`.
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
TOPIC = re.compile(r"^(edict:\d{1,4}|workstream:[a-z0-9][a-z0-9._-]{0,63}|path:[^\s]{1,200}|general)$")
POST_FILE = re.compile(r"^(\d{4})-([a-z0-9][a-z0-9._-]{0,63})\.json$")
THREAD_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
WS_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HEX = re.compile(r"^[0-9a-f]{7,40}$")
HASH_IN_TEXT = re.compile(r"\b(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}\b")
WS_CITE = re.compile(r"^ws:([a-z0-9][a-z0-9._-]{0,63})/(\S+)$")
WS_CITE_IN_TEXT = re.compile(r"\bws:[a-z0-9][a-z0-9._-]*/\S+")
MAX_TITLE, MAX_BODY, MAX_SHOWN_BODY = 120, 20000, 4000
TIMEOUT = 60  # seconds for fetch/push


class BoardError(Exception):
    pass


@dataclass
class Post:
    id: str          # from the file name: NNNN-author
    thread: str      # from the directory
    author: str      # from the file name (a claim)
    created: str
    body: str
    cites: list = field(default_factory=list)
    to: list = field(default_factory=list)

    @property
    def number(self) -> int:
        return int(self.id[:4])


@dataclass
class Thread:
    id: str
    title: str
    topic: str
    opened_by: str
    created: str
    posts: list = field(default_factory=list)


def one_line(text, limit: int) -> str:
    """Untrusted text made safe to show the model: control characters and newlines flattened, bounded."""
    flat = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text)).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ---------- git plumbing ----------


def repo_root(start: Path) -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path(start)


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
    return f"refs/heads/{s['branch']}", (f"refs/remotes/{remote}/{s['branch']}" if remote else None)


def _resolve(repo: Path, ref: str) -> Optional[str]:
    out = _git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).strip()
    return out or None


def fetch(repo: Path) -> Optional[str]:
    """Fetch the board branch. Returns a note instead of raising (offline is normal)."""
    s = settings(repo)
    _, remote_ref = _refs(repo)
    if not remote_ref:
        return None
    try:
        result = subprocess.run(["git", "fetch", "-q", s["remote"], f"+refs/heads/{s['branch']}:{remote_ref}"],
                                cwd=repo, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "couldn't fetch the board (timed out)"
    if result.returncode != 0:
        err = result.stderr.strip()
        if "couldn't find remote ref" in err:
            return None  # nobody has posted yet
        return f"couldn't fetch the board ({one_line(err.splitlines()[-1] if err else 'git fetch failed', 160)})"
    return None


def tip(repo: Path) -> Optional[str]:
    """The board's newest known commit: the remote's if there is one, else the local branch."""
    local, remote_ref = _refs(repo)
    return (_resolve(repo, remote_ref) if remote_ref else None) or _resolve(repo, local)


def _json_at(repo: Path, commit: str, path: str):
    try:
        return json.loads(_git(repo, "show", f"{commit}:{path}"))
    except (BoardError, json.JSONDecodeError):
        return None


def load_board(repo: Path, commit: Optional[str] = None) -> tuple[list[Thread], list[str]]:
    """(threads, problems). Malformed files are skipped and reported; nothing on the board is fatal."""
    commit = commit or tip(repo)
    if not commit:
        return [], []
    paths = _git(repo, "ls-tree", "-r", "--full-tree", "--name-only", commit, "--", "threads/").splitlines()
    threads: dict[str, Thread] = {}
    problems: list[str] = []
    for path in paths:
        parts = path.split("/")
        if len(parts) == 3 and parts[2] == "thread.json":
            data = _json_at(repo, commit, path)
            if not THREAD_ID.match(parts[1]) or not isinstance(data, dict):
                problems.append(f"{path}: unreadable thread")
                continue
            raw_topic, raw_by = str(data.get("topic", "")), str(data.get("opened_by", ""))
            topic = raw_topic if TOPIC.match(raw_topic) else "general"
            opened_by = raw_by if WS_ID.match(raw_by) else "?"
            threads[parts[1]] = Thread(parts[1], one_line(data.get("title", ""), MAX_TITLE) or parts[1], topic,
                                       opened_by, str(data.get("created", ""))[:32])
    for path in sorted(paths):
        parts = path.split("/")
        if len(parts) != 3 or parts[2] == "thread.json":
            if len(parts) != 3:
                problems.append(f"{path}: not part of a thread")
            continue
        m = POST_FILE.match(parts[2])
        if parts[1] not in threads or not m:
            problems.append(f"{path}: not a post in a known thread")
            continue
        data = _json_at(repo, commit, path)
        if not isinstance(data, dict) or not isinstance(data.get("body"), str):
            problems.append(f"{path}: unreadable post")
            continue
        raw_to, raw_cites = data.get("to"), data.get("cites")
        to: list = raw_to if isinstance(raw_to, list) else []
        cites: list = raw_cites if isinstance(raw_cites, list) else []
        threads[parts[1]].posts.append(Post(
            id=parts[2][:-5], thread=parts[1], author=m.group(2), created=str(data.get("created", ""))[:32],
            body=data["body"][:MAX_BODY], cites=[str(c)[:80] for c in cites if isinstance(c, str)][:50],
            to=[t for t in to if isinstance(t, str) and WS_ID.match(t)][:20],
        ))
    return sorted(threads.values(), key=lambda t: t.created), problems


def load_threads(repo: Path, commit: Optional[str] = None) -> list[Thread]:
    return load_board(repo, commit)[0]


def _checked_out_anywhere(repo: Path, branch: str) -> Optional[str]:
    out = _git(repo, "worktree", "list", "--porcelain", check=False)
    current = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):]
        elif line == f"branch refs/heads/{branch}":
            return current
    return None


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
    """Build a commit on the newest tip and push it; retry only when someone else posted first."""
    s = settings(repo)
    where = _checked_out_anywhere(repo, s["branch"])
    if where:
        raise BoardError(f"the board branch {s['branch']} is checked out in {where}; switch that checkout away first")
    local, remote_ref = _refs(repo)
    for _ in range(attempts):
        if remote_ref:
            note = fetch(repo)
            if note:
                raise BoardError(note)
        parent = tip(repo)
        commit = _commit_files(repo, parent, build(parent), message)
        if remote_ref:
            try:
                pushed = subprocess.run(["git", "push", "-q", s["remote"], f"{commit}:refs/heads/{s['branch']}"],
                                        cwd=repo, capture_output=True, text=True, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                raise BoardError("pushing to the board timed out")
            if pushed.returncode != 0:
                err = pushed.stderr
                if "non-fast-forward" in err or "fetch first" in err:
                    time.sleep(0.2)  # someone posted first: rebuild on their commit
                    continue
                raise BoardError(f"the remote refused the post: {one_line(err, 300)}")
            _git(repo, "update-ref", remote_ref, commit)
        _git(repo, "update-ref", local, commit)
        return commit
    raise BoardError("the board kept changing while posting; try again")


# ---------- local state: drafts, read markers, follows (per workstream) ----------


def _local(repo: Path) -> Path:
    folder = Path(repo) / ".daedalus" / "board"
    folder.mkdir(parents=True, exist_ok=True)
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text("# Local board state and drafts: never committed (edict 0009)\n*\n", encoding="utf-8")
    return folder


def _load_all_state(repo: Path) -> dict:
    try:
        data = json.loads((_local(repo) / "state.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def load_state(repo: Path, me: str) -> dict:
    state = _load_all_state(repo).get("workstreams", {}).get(me, {})
    return state if isinstance(state, dict) else {}


def save_state(repo: Path, me: str, state: dict) -> None:
    data = _load_all_state(repo)
    data.setdefault("workstreams", {})[me] = state
    (_local(repo) / "state.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "thread"


def draft(repo: Path, author: str, body: str, thread: Optional[str] = None, title: Optional[str] = None,
          topic: Optional[str] = None, to=(), cites=()) -> Path:
    """Write a local draft: a reply to `thread`, or a new thread with `title` and `topic`."""
    if not body.strip():
        raise BoardError("A post needs a body")
    if len(body) > MAX_BODY:
        raise BoardError(f"A post is at most {MAX_BODY} characters")
    if thread is None:
        if not title or not topic:
            raise BoardError("A new thread needs a title and a topic")
        if not TOPIC.match(topic):
            raise BoardError("topic is edict:NNNN, workstream:<id>, path:<path or glob>, or general")
    elif thread not in {t.id for t in load_threads(repo)}:
        raise BoardError(f"No thread '{thread}' on the board (run `daedalus board threads --all`)")
    folder = _local(repo) / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{_slug(title or thread or '')}.json"
    path.write_text(json.dumps({"author": author, "thread": thread, "title": one_line(title, MAX_TITLE) if title else None,
                                "topic": topic, "body": body.strip(), "to": list(to), "cites": list(cites)}, indent=2)
                    + "\n", encoding="utf-8")
    return path


def _committed_plan(repo: Path, wid: str) -> Optional[dict]:
    """A workstream's plan as committed (what other owners see), else as on disk."""
    from . import workstreams as ws
    from .cli import gameplan as gp

    rel = str(ws.file_for(repo, wid).relative_to(repo))
    committed = _git(repo, "show", f"HEAD:{rel}", check=False)
    try:
        return json.loads(committed) if committed else gp.load_gameplan(repo, wid)
    except (json.JSONDecodeError, gp.GameplanError, ws.WorkstreamError):
        return None


def check_draft(repo: Path, data) -> list[str]:
    """Deterministic: the draft is well formed and every citation (listed or in the body) exists."""
    from . import workstreams as ws

    if not isinstance(data, dict):
        return ["the draft must be a JSON object"]
    errors = []
    body, cites, to = data.get("body"), data.get("cites") or [], data.get("to") or []
    if not isinstance(body, str) or not body.strip():
        return ["body must be non-empty text"]
    if len(body) > MAX_BODY:
        errors.append(f"body is longer than {MAX_BODY} characters")
    if not isinstance(cites, list) or not all(isinstance(c, str) for c in cites):
        return errors + ["cites must be a list of strings"]
    if not isinstance(to, list) or not all(isinstance(t, str) for t in to):
        return errors + ["to must be a list of workstream ids"]
    if not data.get("thread") and (not data.get("title") or not TOPIC.match(str(data.get("topic", "")))):
        errors.append("a new thread needs a title and a valid topic")

    commit_cites = [c for c in cites if not c.startswith("ws:")]
    ws_cites = [c for c in cites if c.startswith("ws:")] + WS_CITE_IN_TEXT.findall(body)
    for sha in commit_cites:
        if not HEX.match(sha):
            errors.append(f"cited commit {sha!r} is not a commit hash")
        elif not _resolve(repo, f"{sha}^{{commit}}"):
            errors.append(f"cited commit {sha} is not in this repository")
    for sha in HASH_IN_TEXT.findall(body):
        if not _resolve(repo, f"{sha}^{{commit}}"):
            errors.append(f"commit {sha} mentioned in the body is not in this repository")
    for cite in dict.fromkeys(ws_cites):
        m = WS_CITE.match(cite.rstrip(".,;:)"))
        if not m:
            errors.append(f"{cite}: workstream citations look like ws:<workstream>/<phase or task id>")
            continue
        wid, entry = m.groups()
        plan = _committed_plan(repo, wid) if wid in ws.list_ids(repo) else None
        if plan is None:
            errors.append(f"{cite}: no workstream '{wid}'")
            continue
        active = plan.get("activePhase") or {}
        ids = {p.get("id") for p in plan.get("phases", [])} | {t.get("id") for t in active.get("tasks", [])}
        if entry not in ids:
            errors.append(f"{cite}: '{entry}' is not a phase or task in workstream {wid} (as committed)")
    for target in to:
        if target not in ws.list_ids(repo):
            errors.append(f"to: no workstream '{target}'")
    return errors


def post(repo: Path, draft_path: Path, author: str) -> tuple[str, str]:
    """Publish a draft as `author` (the current workstream). Re-checked here, whatever happened since."""
    try:
        data = json.loads(Path(draft_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BoardError(f"can't read the draft: {e}")
    errors = check_draft(repo, data)
    if errors:
        raise BoardError("; ".join(errors))
    if data.get("author") != author:
        raise BoardError(f"the draft was written as {data.get('author')!r}; you are posting as {author!r}")
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
            number = 1
        else:
            thread = next((t for t in existing if t.id == thread_id), None)
            if thread is None:
                raise BoardError(f"No thread '{thread_id}' on the board")
            number = max((p.number for p in thread.posts), default=0) + 1
        post_id = f"{number:04d}-{author}"
        files[f"threads/{thread_id}/{post_id}.json"] = json.dumps(
            {"id": post_id, "thread": thread_id, "author": author, "created": created, "body": data["body"],
             "cites": data.get("cites") or [], "to": data.get("to") or []}, indent=2) + "\n"
        result.update(thread=thread_id, post=post_id)
        return files

    _publish(repo, build, f"board: {author} posts in {data.get('thread') or data['title']}")
    Path(draft_path).unlink()
    state = load_state(repo, author)
    state.setdefault("read", {}).setdefault(result["thread"], []).append(result["post"])
    save_state(repo, author, state)
    return result["thread"], result["post"]


# ---------- following and unread (per workstream) ----------


def follows(repo: Path, thread: Thread, me: str) -> bool:
    """Whether workstream `me` follows a thread (edict 0009's filter)."""
    from . import workstreams as ws
    from .cli import gameplan as gp

    state = load_state(repo, me)
    if thread.id in state.get("unfollow", []):
        return False
    if thread.id in state.get("follow", []):
        return True
    if thread.opened_by == me or any(p.author == me or me in p.to for p in thread.posts):
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
    """Followed threads with posts by others this workstream hasn't read (by post id, not by max)."""
    seen = load_state(repo, me).get("read", {})
    out = []
    for t in threads if threads is not None else load_threads(repo):
        if not follows(repo, t, me):
            continue
        read = set(seen.get(t.id, []))
        new = [p for p in t.posts if p.id not in read and p.author != me]
        if new:
            out.append((t, new))
    return out


def mark_read(repo: Path, thread: Thread, me: str) -> None:
    state = load_state(repo, me)
    read = set(state.setdefault("read", {}).get(thread.id, []))
    state["read"][thread.id] = sorted(read | {p.id for p in thread.posts})
    save_state(repo, me, state)


def set_follow(repo: Path, thread_id: str, me: str, follow: bool) -> None:
    state = load_state(repo, me)
    add, remove = ("follow", "unfollow") if follow else ("unfollow", "follow")
    state[remove] = [t for t in state.get(remove, []) if t != thread_id]
    if thread_id not in state.setdefault(add, []):
        state[add].append(thread_id)
    save_state(repo, me, state)


def poll_due(repo: Path, me: str) -> bool:
    """For the UserPromptSubmit hook: at most one check every board.poll_minutes."""
    state = load_state(repo, me)
    if time.time() - state.get("last_poll", 0) < settings(repo)["poll_minutes"] * 60:
        return False
    state["last_poll"] = time.time()
    save_state(repo, me, state)
    return True


def show_body(body: str) -> list[str]:
    """A post body for display: quoted line by line and bounded, so it can't pass as Daedalus output."""
    text = body if len(body) <= MAX_SHOWN_BODY else body[:MAX_SHOWN_BODY] + f"\n[... {len(body) - MAX_SHOWN_BODY} more characters]"
    return ["| " + re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", line) for line in text.splitlines()]
