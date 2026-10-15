"""
The context map's incremental index (edict 0015): what fills the context since the last compaction.

Exact accounting. Every main-thread request's `usage` says how big the context was:
input_tokens + cache_read_input_tokens + cache_creation_input_tokens, once per requestId. Between two
consecutive requests the growth is exact. The previous request's output_tokens go to the `output` line
(its text, tool calls and thinking: thinking is resent but barely visible in the transcript). The rest is
split among the other entries added in that step by their serialized size. Where the growth is smaller
than output_tokens (a version that strips thinking), the whole step is split by size and the line is
marked estimated. The first request after a compaction sets the base: everything present before new work.

The index is kept per session under the cache directory and extended from the byte offset it reached, so
a hook never re-reads the whole transcript. A transcript that shrank or whose first line changed resets it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

INDEX_VERSION = 2  # 2: max_seen; API error entries are not requests
TASK_ID = re.compile(r"(?<![\w-])T-[a-z]{0,3}\d+[a-z]?\b")
AGENT_ID = re.compile(r'<agent-message from="([A-Za-z0-9_-]+)"|<task-id>([A-Za-z0-9_-]+)</task-id>')
TOOL_USE_ID = re.compile(r"<tool-use-id>([A-Za-z0-9_-]+)</tool-use-id>")
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit", "NotebookRead"}
AGENT_TOOLS = {"Agent", "Task"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
SEPARATORS = re.compile(r"\|\||&&|;|\|")
SEGMENT_KEEP = 10  # finished segments (one per compaction) kept for plans, recall and checks
SHELL_SKIP = {"for", "while", "until", "if", "case", "done", "fi", "esac", "}", "[", "[[", "test"}
SHELL_LEAD = {"do", "then", "else", "elif", "time", "!", "env", "exec", "nohup", "{"}
SUBSTITUTION = re.compile(r"\$\([^()]*\)|`[^`]*`")
GIT_GLOBAL_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}


def _git_subcommand(words: list) -> list:
    """The words from git's subcommand on, past global options (`git -C x commit` -> [commit, ...])."""
    i = 1
    while i < len(words) and words[i].startswith("-"):
        i += 2 if words[i] in GIT_GLOBAL_WITH_VALUE else 1
    return words[i:]


def _resolve(value: str, cmd) -> str:
    """A -m value, with any $(...) in it replaced by the heredoc text its commands carry."""
    for key, inner in cmd.substs.items():
        if key in value:
            value = value.replace(key, "\n".join(b for c in inner for b in c.heredocs))
    return value


def marker_texts(command: str) -> list:
    """The text in a Bash command that names the task in play: a commit's message (each -m/--message
    value, in the -am, -qm and -mVALUE forms too, `-m "$(cat <<'EOF' ...)"`, and a heredoc given to
    `-F -`), and the task id of `daedalus gameplan [-w X] task <verb> <id>`. Nothing else: not other
    heredocs, quoted strings or tool output."""
    from daedalus_hookkit.shell import parse

    out = []
    for cmd in parse(command or ""):
        words = cmd.words
        if words[0] == "git":
            sub = _git_subcommand(words)
            if sub[:1] != ["commit"]:
                continue
            args, i = sub[1:], 0
            while i < len(args):
                w = args[i]
                if w in ("-m", "--message") or (w.startswith("-") and not w.startswith("--") and w.endswith("m")
                                                and len(w) > 2 and w[1:].isalpha()):
                    if i + 1 < len(args):
                        out.append(_resolve(args[i + 1], cmd))
                    i += 2
                    continue
                if w.startswith("--message="):
                    out.append(_resolve(w.split("=", 1)[1], cmd))
                elif w.startswith("-m") and len(w) > 2:
                    out.append(_resolve(w[2:], cmd))
                elif ((w in ("-F", "--file") and i + 1 < len(args) and args[i + 1] == "-") or w == "--file=-") \
                        and cmd.heredocs:
                    out.append(cmd.heredocs[0])
                i += 1
        elif words[:2] == ["daedalus", "gameplan"]:
            rest = words[2:]
            while rest and (rest[0] in ("-w", "--workstream") or rest[0].startswith("--workstream=")):
                rest = rest[1:] if "=" in rest[0] else rest[2:]
            if rest[:1] == ["task"] and len(rest) >= 3:
                out.append(rest[2])
    return out


def command_name(command: str) -> str:
    """The command a Bash line runs: split on && || ; |, drop segments that only cd or set variables, and take
    the first word of the first segment left (`cd x && FOO=1 pytest -q` -> pytest)."""
    first_line = SUBSTITUTION.sub("X", (command or "").split("\n", 1)[0])
    for seg in SEPARATORS.split(first_line):
        words = [w if w.endswith("()") else w.strip("()") for w in seg.strip().split()]
        words = [w for w in words if w]
        while words and (ASSIGNMENT.match(words[0]) or words[0] in SHELL_LEAD or words[0].endswith("()")):
            words = words[1:]
        if not words or words[0] == "cd" or words[0] in SHELL_SKIP:
            continue
        return words[0].rsplit("/", 1)[-1]
    return "?"


def path_subject(path: str, root: str) -> tuple[str, str]:
    """(kind, label) for a file: relative to the project, two directories deep; outside it, its first two parts."""
    p = (path or "").replace("\\", "/")
    root = (root or "").replace("\\", "/").rstrip("/")
    if root and (p == root or p.startswith(root + "/")):
        parts = p[len(root):].strip("/").split("/")
        dirs = parts[:-1][:2]
        return "file", ("/".join(dirs) + "/") if dirs else parts[-1]
    parts = [x for x in p.split("/") if x]
    return "file", "outside: " + "/".join(parts[:2])


def _size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str)) if obj is not None else 0


def empty_segment(boundary_uuid: Optional[str] = None, at: Optional[str] = None) -> dict:
    return {
        "boundary": boundary_uuid, "started": at,
        "base": None, "base_estimate": {}, "last_ctx": None, "last_request": None, "last_output": 0,
        "exact": True,
        "subjects": {},     # key -> {kind, label, tokens, chars, last_touched, uuids, how}
        "tasks": {},        # key -> {label, tokens, last_touched}
        "pending": [],      # [subject key, task key, chars, uuid, is_output] since the last request
        "task": None, "branch": None,
        "summary_uuid": None,
    }


def empty_index(path: str, first_hash: str) -> dict:
    return {"version": INDEX_VERSION, "transcript": path, "first_line_hash": first_hash, "offset": 0,
            "ratio": {"chars": 0, "tokens": 0}, "tool_subjects": {}, "max_seen": 0, "segment": empty_segment(),
            "finished": [], "last_at": None, "root": None}


def _first_line_hash(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.readline()).hexdigest()[:16]
    except OSError:
        return ""


def ratio(index: dict) -> float:
    """Characters per token measured in this session; 3.0 until there is enough to measure."""
    r = index["ratio"]
    return r["chars"] / r["tokens"] if r["tokens"] > 2000 else 3.0


class Indexer:
    def __init__(self, index: dict, agent_types: dict):
        self.ix = index
        self.agent_types = agent_types  # agentId -> agentType, from subagents/*.meta.json

    # ---------- subjects ----------

    def _subject(self, seg: dict, kind: str, label: str) -> str:
        key = f"{kind}:{label}"
        if key not in seg["subjects"]:
            seg["subjects"][key] = {"kind": kind, "label": label, "tokens": 0.0, "chars": 0, "last_touched": None,
                                    "uuids": [], "how": "attributed"}
        return key

    def _task_key(self, seg: dict) -> str:
        if seg["task"]:
            return "task:" + seg["task"]
        if seg["branch"]:
            return "branch:" + seg["branch"]
        return "unassigned"

    def _add(self, seg: dict, subject: str, chars: int, uuid, at, is_output: bool = False) -> None:
        task = self._task_key(seg)
        seg["pending"].append([subject, task, chars, uuid, is_output])
        s = seg["subjects"][subject]
        s["chars"] += chars
        if at:
            s["last_touched"] = at
        if uuid and (not s["uuids"] or s["uuids"][-1] != uuid):
            s["uuids"].append(uuid)
        t = seg["tasks"].setdefault(task, {"tokens": 0.0, "last_touched": None})
        if at:
            t["last_touched"] = at

    def _tool_subject(self, seg: dict, block: dict) -> str:
        name = str(block.get("name") or "?")
        inp = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name in FILE_TOOLS:
            kind, label = path_subject(str(inp.get("file_path") or inp.get("notebook_path") or ""), self.ix["root"] or "")
        elif name == "Bash":
            kind, label = "command", command_name(str(inp.get("command") or ""))
        elif name in AGENT_TOOLS:
            kind, label = "agent", f"Agent: {inp.get('subagent_type') or 'general-purpose'} (launch)"
        elif name == "Skill":
            kind, label = "other", f"Skill: {str(inp.get('skill') or '?').rsplit(':', 1)[-1]}"
        else:
            kind, label = "other", name
        return self._subject(seg, kind, label)

    def _markers(self, seg: dict, text: str) -> None:
        ids = TASK_ID.findall(text or "")
        if ids:
            seg["task"] = ids[-1]

    # ---------- events ----------

    def feed(self, ev: dict) -> None:
        etype = ev.get("type")
        if ev.get("isSidechain"):
            return
        at = ev.get("timestamp") if isinstance(ev.get("timestamp"), str) else None
        if at:
            self.ix["last_at"] = at
        if self.ix["root"] is None and isinstance(ev.get("cwd"), str):
            self.ix["root"] = ev["cwd"]
        seg = self.ix["segment"]
        branch = ev.get("gitBranch")
        if isinstance(branch, str) and branch and branch != seg["branch"]:
            if seg["branch"] is not None:
                seg["task"] = None  # a branch change starts a new segment of work
            seg["branch"] = branch
        uuid = ev.get("uuid")
        if etype == "system":
            if ev.get("subtype") == "compact_boundary":
                self._boundary(ev, at)
            return
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        if etype == "assistant":
            synthetic = ev.get("isApiErrorMessage") or str(msg.get("model") or "").startswith("<")
            if msg.get("model") and not synthetic:
                self.ix["model"] = str(msg["model"])
            if not synthetic:  # an API error notice carries zero usage: it isn't a request
                self._request(seg, ev, msg)
            for block in msg.get("content") if isinstance(msg.get("content"), list) else []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    key = self._tool_subject(seg, block)
                    self.ix["tool_subjects"][str(block.get("id"))] = key
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    if block.get("name") == "Bash":
                        for text in marker_texts(str(inp.get("command") or "")):
                            self._markers(seg, text)
                out = self._subject(seg, "output", "output")
                self._add(seg, out, _size(block), uuid, at, is_output=True)
            return
        if etype == "user":
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            if results:
                for b in results:
                    key = self.ix["tool_subjects"].get(str(b.get("tool_use_id")))
                    if key is None or key not in seg["subjects"]:
                        key = self._subject(seg, "other", "tool results")
                    self._add(seg, key, _size(b), uuid, at)
                return
            text = content if isinstance(content, str) else " ".join(
                str(b.get("text", "")) for b in blocks if isinstance(b, dict))
            if ev.get("isCompactSummary"):
                seg["summary_uuid"] = uuid
                key = self._subject(seg, "other", "compaction summary")
            elif AGENT_ID.search(text[:300]) and ("<task-notification" in text[:50] or "agent-message" in text[:300]):
                m = AGENT_ID.search(text[:300])
                agent_id = m.group(1) or m.group(2)
                use = TOOL_USE_ID.search(text[:600])
                origin = self.ix["tool_subjects"].get(use.group(1)) if use else None
                if agent_id in self.agent_types:
                    key = self._subject(seg, "agent", f"Agent: {self.agent_types[agent_id]}")
                elif origin and origin in seg["subjects"] and seg["subjects"][origin]["kind"] != "agent":
                    key = origin  # a background command's completion notice: it belongs to that command
                else:
                    key = self._subject(seg, "agent", "Agent: agent")
            elif ev.get("isMeta"):
                key = self._subject(seg, "other", "reminders and attachments")
            else:
                self._markers(seg, text)
                key = self._subject(seg, "conversation", "your messages")
            self._add(seg, key, _size(content), uuid, at)
            return
        if etype == "attachment":
            key = self._subject(seg, "other", "reminders and attachments")
            self._add(seg, key, _size(ev.get("attachment")), uuid, at)

    def _request(self, seg: dict, ev: dict, msg: dict) -> None:
        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else None
        rid = ev.get("requestId") or msg.get("id")
        if usage is None:
            return
        if rid == seg["last_request"]:
            seg["last_output"] = max(seg["last_output"], int(usage.get("output_tokens") or 0))
            return
        ctx = sum(int(usage.get(k) or 0) for k in
                  ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        self.ix["max_seen"] = max(int(self.ix.get("max_seen") or 0), ctx)
        if seg["base"] is None:
            seg["base"] = ctx
            for subject, task, chars, *_ in seg["pending"]:
                seg["base_estimate"][subject] = seg["base_estimate"].get(subject, 0) + chars
                seg["subjects"][subject]["chars"] -= chars  # it's in the base line, not the subject's
            seg["pending"] = []
        else:
            self._attribute(seg, ctx - seg["last_ctx"], seg["last_output"])
        seg["last_ctx"] = ctx
        seg["last_request"] = rid
        seg["last_output"] = int(usage.get("output_tokens") or 0)

    def _attribute(self, seg: dict, growth: int, output: int) -> None:
        pending = seg["pending"]
        seg["pending"] = []
        if growth < 0:  # Claude Code cleared something (old tool results): a negative line keeps the sum exact
            self._credit(seg, self._subject(seg, "other", "cleared by Claude Code"), self._task_key(seg), growth)
            growth = 0
        if growth >= output:
            out_key = self._subject(seg, "output", "output")
            self._credit(seg, out_key, self._task_key(seg) if not pending else pending[-1][1], output)
            rest = [p for p in pending if not p[4]]
            remainder = growth - output
            exact = True
        else:
            rest, remainder, exact = pending, growth, False
            seg["exact"] = False
        total = sum(p[2] for p in rest)
        if not rest or total <= 0:
            if remainder:
                self._credit(seg, self._subject(seg, "other", "everything else"), self._task_key(seg), remainder)
            return
        if exact:
            self.ix["ratio"]["chars"] += total
            self.ix["ratio"]["tokens"] += remainder
        for subject, task, chars, *_ in rest:
            self._credit(seg, subject, task, remainder * chars / total)
            if not exact:
                seg["subjects"][subject]["how"] = "estimated"

    def _credit(self, seg: dict, subject: str, task: str, tokens: float) -> None:
        seg["subjects"][subject]["tokens"] += tokens
        seg["tasks"].setdefault(task, {"tokens": 0.0, "last_touched": None})["tokens"] += tokens

    def _boundary(self, ev: dict, at) -> None:
        meta = ev.get("compactMetadata") if isinstance(ev.get("compactMetadata"), dict) else {}
        self.ix["max_seen"] = max(int(self.ix.get("max_seen") or 0), int(meta.get("preTokens") or 0))
        seg = self.ix["segment"]
        if seg["base"] is not None or seg["subjects"]:
            done = dict(seg)
            done["ended"] = at
            self.ix["finished"] = (self.ix["finished"] + [done])[-SEGMENT_KEEP:]
        new = empty_segment(ev.get("uuid"), at)
        new["branch"], new["task"] = seg["branch"], seg["task"]
        self.ix["segment"] = new


def agent_types_for(transcript: Path) -> dict:
    """agentId -> agentType from the session's subagents/*.meta.json."""
    folder = Path(transcript).with_suffix("") / "subagents"
    out = {}
    if folder.is_dir():
        for meta in folder.glob("agent-*.meta.json"):
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("agentType"):
                out[meta.name[len("agent-"):-len(".meta.json")]] = str(data["agentType"])
    return out


def update(index: Optional[dict], transcript: Path, max_bytes: Optional[int] = None) -> tuple[dict, bool]:
    """Extend the index from the transcript's new bytes. Returns (index, caught_up). With max_bytes, read at
    most that much (a cold start in slices); caught_up is False while more remains."""
    from ..reflection.digest import iter_events_from

    transcript = Path(transcript)
    first = _first_line_hash(transcript)
    try:
        size = transcript.stat().st_size
    except OSError:
        return (index or empty_index(str(transcript), first)), True
    if (not index or index.get("version") != INDEX_VERSION or index.get("first_line_hash") != first
            or index.get("transcript") != str(transcript) or index.get("offset", 0) > size):
        index = empty_index(str(transcript), first)
    indexer = Indexer(index, agent_types_for(transcript))
    start = index["offset"]
    for event, offset in iter_events_from(transcript, start, {}):
        indexer.feed(event)
        index["offset"] = offset
        if max_bytes is not None and offset - start >= max_bytes:
            return index, offset >= size
    return index, True
