"""Scrub a Claude Code transcript into a test fixture: keep structure and markers, drop content.

How the fixtures in claude/projects/ were made (edict 0010: fixtures come from real transcripts).
Text becomes "[redacted]" except the markers and prefixes the parser keys on; commands and paths
become salted hashes (the salt is random per run and never saved, so a guessed command can't be
confirmed); cwd becomes /fixture/project; branch names become fixture-branch. Event structure,
UUIDs, timestamps, model IDs and token counts are kept. Run with python -I on a copy, never on a
transcript in place.

usage: scrub.py IN.jsonl OUT.jsonl [--window N] [--around PATTERN ...] [--max-events N]
"""
import hashlib
import json
import re
import secrets
import sys

SALT = secrets.token_hex(16)

KEEP_KEYS = {
    "type", "subtype", "uuid", "parentUuid", "sessionId", "session_id", "timestamp", "version",
    "id", "tool_use_id", "name", "stop_reason", "model", "gitBranch", "isSidechain", "is_error",
    "agentId", "requestId", "interrupted", "userType", "entrypoint", "role", "promptId",
    "decision", "source", "reasonType", "isSnapshotUpdate", "messageId",
}
NUMERIC_OK = True
MARKERS = [
    "[Request interrupted by user]",
    "[Request interrupted by user for tool use]",
    "User rejected tool use",
]
PREFIXES = [
    "The user doesn't want to proceed with this tool use.",
    "Permission for this action was denied by the Claude Code auto mode classifier.",
    "Command running in background with ID:",
    "<tool_use_error>",
    "<task-notification>", "<command-name>", "<local-command-stdout>", "<command-message>",
    "<system-reminder>", "Another Claude session sent a message", "[SYSTEM NOTIFICATION",
]
EXIT = re.compile(r"^Exit code \d+")


def h(s: str) -> str:
    return hashlib.sha256((SALT + s).encode()).hexdigest()[:12]


def scrub_text(s: str) -> str:
    if s in MARKERS:
        return s
    for p in PREFIXES:
        if s.startswith(p):
            return p + " [redacted]"
    m = EXIT.match(s)
    if m:
        return m.group(0) + " [redacted]"
    return "[redacted]"


def scrub(obj, key=None):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "cwd" and isinstance(v, str):
                out[k] = "/fixture/project"
            elif k == "gitBranch" and isinstance(v, str):
                out[k] = "fixture-branch"
            elif k in ("file_path", "path") and isinstance(v, str):
                out[k] = f"/fixture/project/file-{h(v)}"
            elif k == "command" and isinstance(v, str):
                out[k] = f"cmd-{h(v)}"
            elif k == "usage" and isinstance(v, dict):
                out[k] = v
            else:
                out[k] = scrub(v, k)
        return out
    if isinstance(obj, list):
        return [scrub(v, key) for v in obj]
    if isinstance(obj, str):
        if key in KEEP_KEYS:
            return obj
        return scrub_text(obj)
    return obj


def main():
    args = sys.argv[1:]
    src, dst = args[0], args[1]
    window, around, max_events = 0, [], None
    i = 2
    while i < len(args):
        if args[i] == "--window":
            window = int(args[i + 1]); i += 2
        elif args[i] == "--around":
            around.append(args[i + 1]); i += 2
        elif args[i] == "--max-events":
            max_events = int(args[i + 1]); i += 2
        else:
            raise SystemExit(f"unknown arg {args[i]}")
    lines = open(src, encoding="utf-8").read().splitlines()
    keep = set(range(len(lines)))
    if around:
        keep = set()
        for n, line in enumerate(lines):
            if any(p in line for p in around):
                keep.update(range(max(0, n - window), min(len(lines), n + window + 1)))
    out = []
    for n in sorted(keep):
        try:
            ev = json.loads(lines[n])
        except json.JSONDecodeError:
            continue
        if ev.get("type") in ("api-request-blob", "api-request", "api-request-shape", "file-history-snapshot", "bridge-session"):
            # Large blobs: keep the event type, drop the payload
            ev = {k: ev[k] for k in ("type", "sessionId", "timestamp") if k in ev}
        out.append(json.dumps(scrub(ev), ensure_ascii=False))
        if max_events and len(out) >= max_events:
            break
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"{dst}: {len(out)} events")


if __name__ == "__main__":
    main()
