"""
Session digests (edict 0010): one JSON summary per Claude Code session, with no model calls.

A digest keeps what reflection needs after Claude Code's cleanup deletes the transcript: token
totals, tool calls and failures, retries, re-reads, permission denials and rejections,
interruptions, subagents, and the event UUIDs behind each count, so findings can cite them.

The transcript format is undocumented and changes between versions. The parser skips what it
doesn't know (counting it), and never fails a digest over one event.

Heuristic counts (retries, re-reads, interruptions before a reply) are labelled `inferred`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from .fsutil import read_json, write_json
from .paths import norm_path, owner_project, projects_dir, sessions_dir

SCHEMA_VERSION = 1
RETRY_WINDOW = 5  # tool calls after a failure in which the same call counts as a retry

KNOWN_TYPES = {
    "user", "assistant", "system", "attachment", "summary", "file-history-snapshot",
    "file-history-delta", "queue-operation", "ai-title", "custom-title", "last-prompt", "mode",
    "permission-mode", "atis-latch", "pr-link", "api-request", "api-request-blob",
    "api-request-shape", "bridge-session", "tag",
}

INTERRUPTED = "[Request interrupted by user]"
INTERRUPTED_FOR_TOOL = "[Request interrupted by user for tool use]"
REJECTED_PREFIX = "The user doesn't want to proceed with this tool use"
REJECTED_RESULT = "User rejected tool use"
CLASSIFIER_DENIED = "denied by the Claude Code auto mode classifier"
# User-role messages the harness injects, which are not prompts the user typed
INJECTED_PREFIXES = ("<task-notification", "<command-name>", "<local-command", "<command-message>",
                     "<system-reminder>", "Another Claude session sent a message",
                     "[SYSTEM NOTIFICATION", "Caveat:")
EDITING_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# A background agent's completion notice carries its real token total. Its own transcript does
# not: subagent assistant events record streaming placeholders (stop_reason null, a few tokens).
NOTICE_TASK = re.compile(r"<task-id>([^<]+)</task-id>")
NOTICE_TOKENS = re.compile(r"<subagent_tokens>(\d+)</subagent_tokens>")

COUNTERS = ("failures", "retries", "re_reads", "denied_by_classifier", "rejected_by_user",
            "interruptions", "interruptions_before_reply")
INFERRED = ("retries", "re_reads", "interruptions_before_reply")


# ---------- reading ----------


def iter_events(path: Path, skipped: dict) -> Iterator[dict]:
    """Events of a JSONL transcript. Unreadable lines are counted in skipped['bad_lines']."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    skipped["bad_lines"] = skipped.get("bad_lines", 0) + 1
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError:
        return


def first_cwd(path: Path) -> Optional[str]:
    """The cwd of the first event that has one (the session's starting directory)."""
    for event in iter_events(path, {}):
        if isinstance(event.get("cwd"), str):
            return event["cwd"]
    return None


def transcript_state(path: Path) -> dict:
    """What decides whether a transcript changed since it was digested: its size and last UUID."""
    last = None
    for event in iter_events(path, {}):
        if event.get("uuid"):
            last = event["uuid"]
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {"size": size, "last_uuid": last}


def subagent_files(session_file: Path) -> list[Path]:
    folder = session_file.with_suffix("") / "subagents"
    return sorted(folder.glob("agent-*.jsonl")) if folder.is_dir() else []


# ---------- one stream (a session, or a subagent) ----------


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_text_of(c.get("text", c.get("content", ""))) if isinstance(c, dict) else str(c)
                         for c in content)
    return ""


def _call_key(call: dict) -> str:
    inp = call.get("input") or {}
    if call["tool"] == "Bash":
        return f"command:{inp.get('command', '')}"
    if "file_path" in inp:
        return f"file_path:{inp['file_path']}"
    return "input:" + json.dumps(inp, sort_keys=True, default=str)


@dataclass
class Stream:
    """What one transcript file says. Sessions and subagents are parsed the same way."""
    messages: dict = field(default_factory=dict)       # message.id -> usage
    calls: list = field(default_factory=list)          # tool calls in order
    results: dict = field(default_factory=dict)        # tool_use_id -> result
    prompts: list = field(default_factory=list)        # (index, uuid) of prompts the user typed
    assistant_at: list = field(default_factory=list)   # indexes of assistant events
    interruptions: list = field(default_factory=list)
    timestamps: list = field(default_factory=list)
    versions: set = field(default_factory=set)
    models: set = field(default_factory=set)
    branches: set = field(default_factory=set)
    cwd: Optional[str] = None
    unknown_types: dict = field(default_factory=dict)
    missing_usage: int = 0
    sidechain_events: list = field(default_factory=list)
    reported_agent_tokens: dict = field(default_factory=dict)  # task id -> tokens it reported


def parse_stream(events: Iterator[dict], keep_sidechain: bool = False) -> Stream:
    s = Stream()
    seen_calls = set()
    for index, ev in enumerate(events):
        etype = ev.get("type")
        if etype not in KNOWN_TYPES:
            key = str(etype)
            s.unknown_types[key] = s.unknown_types.get(key, 0) + 1
            continue
        if ev.get("isSidechain") and not keep_sidechain:
            s.sidechain_events.append(ev)  # old transcripts kept subagents inline
            continue
        if isinstance(ev.get("timestamp"), str):
            s.timestamps.append(ev["timestamp"])
        if ev.get("version"):
            s.versions.add(str(ev["version"]))
        if ev.get("gitBranch"):
            s.branches.add(str(ev["gitBranch"]))
        if s.cwd is None and isinstance(ev.get("cwd"), str):
            s.cwd = ev["cwd"]
        msg: dict = ev["message"] if isinstance(ev.get("message"), dict) else {}
        att = ev.get("attachment") if etype == "attachment" else None
        if isinstance(att, dict) and isinstance(att.get("usage"), dict) and att["usage"].get("totalTokens"):
            # A background agent's completion notice, queued for the session
            task = NOTICE_TASK.search(str(att.get("prompt") or ""))
            key = task.group(1) if task else str(ev.get("uuid"))
            s.reported_agent_tokens[key] = max(s.reported_agent_tokens.get(key, 0), int(att["usage"]["totalTokens"]))
        if etype == "assistant":
            s.assistant_at.append(index)
            if msg.get("model"):
                s.models.add(str(msg["model"]))
            mid = msg.get("id") or ev.get("uuid")
            usage = msg.get("usage")
            if isinstance(usage, dict):
                s.messages[mid] = usage  # one message is split over several events; count it once
            elif mid not in s.messages:
                s.missing_usage += 1
            content = msg.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if block.get("id") in seen_calls:
                        continue
                    seen_calls.add(block.get("id"))
                    s.calls.append({"tool": block.get("name", "?"), "id": block.get("id"),
                                    "input": block.get("input") if isinstance(block.get("input"), dict) else {},
                                    "uuid": ev.get("uuid"), "index": index})
        elif etype == "user":
            content = msg.get("content")
            blocks = content if isinstance(content, list) else []
            results = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
            for b in results:
                text = _text_of(b.get("content"))
                tur = ev.get("toolUseResult")
                s.results[b.get("tool_use_id")] = {
                    "is_error": b.get("is_error") is True, "text": text, "uuid": ev.get("uuid"),
                    "rejected": text.startswith(REJECTED_PREFIX) or tur == REJECTED_RESULT,
                    "classifier": CLASSIFIER_DENIED in text[:200],
                }
            if results:
                continue
            text = _text_of(content).strip()
            if text.startswith("<task-notification"):
                task, tokens = NOTICE_TASK.search(text), NOTICE_TOKENS.search(text)
                if task and tokens:
                    key = task.group(1)
                    s.reported_agent_tokens[key] = max(s.reported_agent_tokens.get(key, 0), int(tokens.group(1)))
            if text == INTERRUPTED:
                s.interruptions.append(ev.get("uuid"))
            elif text == INTERRUPTED_FOR_TOOL:
                pass  # follows a rejection; counted there
            elif text and not ev.get("isMeta") and not ev.get("isCompactSummary") \
                    and not text.startswith(INJECTED_PREFIXES):
                s.prompts.append((index, ev.get("uuid")))
    return s


def _tokens(messages: dict) -> dict:
    total = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "messages": len(messages)}
    for usage in messages.values():
        total["input"] += int(usage.get("input_tokens") or 0)
        total["output"] += int(usage.get("output_tokens") or 0)
        total["cache_read"] += int(usage.get("cache_read_input_tokens") or 0)
        total["cache_creation"] += int(usage.get("cache_creation_input_tokens") or 0)
    return total


def _hit_rate(tokens: dict) -> Optional[float]:
    denominator = tokens["input"] + tokens["cache_read"] + tokens["cache_creation"]
    return round(tokens["cache_read"] / denominator, 4) if denominator else None


def count_stream(s: Stream) -> dict:
    """Counters, each with the event UUIDs behind it."""
    events = {k: [] for k in COUNTERS}
    tools: dict[str, dict] = {}
    failed_at: list[int] = []
    read_paths: set[str] = set()
    for i, call in enumerate(s.calls):
        t = tools.setdefault(call["tool"], {"calls": 0, "failures": 0})
        t["calls"] += 1
        result = s.results.get(call["id"])
        # A retry: the same call again within RETRY_WINDOW calls after a failure
        for f in failed_at:
            if 0 < i - f <= RETRY_WINDOW and s.calls[f]["tool"] == call["tool"] \
                    and _call_key(s.calls[f]) == _call_key(call):
                events["retries"].append(call["uuid"])
                failed_at.remove(f)
                break
        inp = call["input"]
        if call["tool"] == "Read" and inp.get("file_path"):
            if inp["file_path"] in read_paths:
                events["re_reads"].append(call["uuid"])
            read_paths.add(inp["file_path"])
        elif call["tool"] in EDITING_TOOLS and inp.get("file_path"):
            read_paths.discard(inp["file_path"])
        if result is None:
            continue
        if result["rejected"]:
            events["rejected_by_user"].append(result["uuid"])
        elif result["classifier"]:
            events["denied_by_classifier"].append(result["uuid"])
        elif result["is_error"]:
            events["failures"].append(result["uuid"])
            t["failures"] += 1
            failed_at.append(i)
    events["interruptions"] = list(s.interruptions)
    # A prompt with no reply before the next prompt: interrupted before the reply began (inferred)
    marked = set(s.interruptions)
    for (index, uuid), (next_index, _) in zip(s.prompts, s.prompts[1:]):
        if not any(index < a < next_index for a in s.assistant_at) and uuid not in marked:
            events["interruptions_before_reply"].append(uuid)
    return {"events": events, "tools": tools}


# ---------- a session ----------


def build_digest(session_file: Path, arms: Optional[dict] = None, previous: Optional[dict] = None) -> dict:
    """The digest of one session: the main transcript plus its subagent transcripts."""
    session_file = Path(session_file)
    skipped: dict = {"bad_lines": 0}
    main = parse_stream(iter_events(session_file, skipped))
    counted = count_stream(main)
    subagents = []
    streams = [(f, parse_stream(iter_events(f, skipped), keep_sidechain=True)) for f in subagent_files(session_file)]
    if main.sidechain_events:
        streams.append((None, parse_stream(iter(main.sidechain_events), keep_sidechain=True)))
    unknown = dict(main.unknown_types)
    missing_usage = main.missing_usage
    for f, sub in streams:
        meta = read_json(f.with_suffix(".meta.json"), {}) if f else {}
        sub_counted = count_stream(sub)
        subagents.append({
            "file": f.name if f else "(inline sidechain)",
            "agent_type": meta.get("agentType") if isinstance(meta, dict) else None,
            "tokens": _tokens(sub.messages),
            "tool_calls": len(sub.calls),
            "failures": len(sub_counted["events"]["failures"]),
            "models": sorted(sub.models),
        })
        for k, v in sub.unknown_types.items():
            unknown[k] = unknown.get(k, 0) + v
        missing_usage += sub.missing_usage
    tokens = _tokens(main.messages)
    stamps = sorted(main.timestamps)
    events = counted["events"]
    session_id = session_file.stem
    arm = (arms or {}).get(session_id, {}).get("arm", "none")
    states = [{"file": session_file.name, **transcript_state(session_file)}]
    states += [{"file": f"{session_id}/subagents/{f.name}", **transcript_state(f)} for f in subagent_files(session_file)]
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "cwd": main.cwd,
        "start": stamps[0] if stamps else None,
        "end": stamps[-1] if stamps else None,
        "claude_code_versions": sorted(main.versions),
        "models": sorted(main.models),
        "branches": sorted(main.branches),
        "tokens": tokens,
        "cache_hit_rate": _hit_rate(tokens),
        "tool_calls": len(main.calls),
        "prompts": len(main.prompts),
        "tools": counted["tools"],
        "counts": {k: len(v) for k, v in events.items()},
        # Every tool call (assistant event) and its result (user event), so findings can cite them
        "calls": [{"uuid": c["uuid"], "tool": c["tool"], "result": (main.results.get(c["id"]) or {}).get("uuid")}
                  for c in main.calls],
        "events": events,
        "labels": {k: ("inferred" if k in INFERRED else "shown") for k in COUNTERS},
        "subagents": {
            "count": len(subagents),
            "tokens": {k: sum(s["tokens"][k] for s in subagents) for k in tokens},
            "tool_calls": sum(s["tool_calls"] for s in subagents),
            # What background agents reported on completion: the real totals
            "reported_tokens": sum(main.reported_agent_tokens.values()),
            "reported_by_agent": dict(sorted(main.reported_agent_tokens.items())),
            "note": "tokens.output from subagent transcripts is a lower bound (they record streaming "
                    "placeholders); reported_tokens is each background agent's own total",
            "list": subagents,
        },
        "skipped": {"unknown_types": unknown, "missing_usage": missing_usage, "bad_lines": skipped["bad_lines"]},
        "gaps": ["interruptions of a running tool call are not counted: never captured in a real transcript"],
        "model_summary_arm": arm,
        "transcripts": states,
        "notes": (previous or {}).get("notes", ""),
        "digested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------- a project ----------


def session_files(claude_projects: Optional[Path] = None) -> Iterator[Path]:
    root = Path(claude_projects) if claude_projects else projects_dir()
    if not root.is_dir():
        return
    for folder in sorted(root.iterdir()):
        if folder.is_dir():
            yield from sorted(folder.glob("*.jsonl"))


def sessions_for_project(project_dir: Path, claude_projects: Optional[Path] = None,
                         windows: Optional[bool] = None) -> list[Path]:
    """
    The project's transcripts, found by the `cwd` in their events (never by decoding Claude
    Code's folder names, which turn both '/' and '.' into '-'). A session belongs to the deepest
    project with a `.daedalus/` at or above where it started.
    """
    target = norm_path(str(Path(project_dir).resolve()), windows)
    return [f for f in session_files(claude_projects) if owner_project(first_cwd(f) or "", windows) == target]


def digest_path(project_dir: Path, session_id: str) -> Path:
    return sessions_dir(project_dir) / f"{session_id}.json"


def load_digests(project_dir: Path) -> list[dict]:
    folder = sessions_dir(project_dir)
    digests = [read_json(p) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []
    return [d for d in digests if isinstance(d, dict) and d.get("session_id")]


def is_current(digest: Optional[dict], session_file: Path) -> bool:
    """True when the digest saw exactly the transcripts as they are now (session and subagents)."""
    if not digest or digest.get("schema_version") != SCHEMA_VERSION:
        return False
    session_id = session_file.stem
    now = [{"file": session_file.name, **transcript_state(session_file)}]
    now += [{"file": f"{session_id}/subagents/{f.name}", **transcript_state(f)} for f in subagent_files(session_file)]
    return digest.get("transcripts") == now


def digest_project(project_dir: Path, claude_projects: Optional[Path] = None,
                   only_session: Optional[str] = None, windows: Optional[bool] = None) -> dict:
    """Digest the project's sessions that are new or have grown. Returns {written, skipped}."""
    from .arms import load_arms

    project_dir = Path(project_dir)
    arms = load_arms(project_dir)
    written, unchanged = [], []
    for f in sessions_for_project(project_dir, claude_projects, windows):
        if only_session and f.stem != only_session:
            continue
        path = digest_path(project_dir, f.stem)
        previous = read_json(path)
        if is_current(previous, f) and (previous or {}).get("model_summary_arm") == arms.get(f.stem, {}).get("arm", "none"):
            unchanged.append(f.stem)
            continue
        write_json(path, build_digest(f, arms, previous))
        written.append(f.stem)
    return {"written": written, "unchanged": unchanged}


def set_notes(project_dir: Path, session_id: str, notes: str) -> Path:
    """Exhale's few lines of reflection, stored in the session's digest."""
    path = digest_path(project_dir, session_id)
    digest = read_json(path)
    if not isinstance(digest, dict):
        raise FileNotFoundError(f"No digest for session {session_id}; run `daedalus reflect digest` first")
    digest["notes"] = notes
    write_json(path, digest)
    return path
