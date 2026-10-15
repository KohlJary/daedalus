"""`daedalus-hook <Event>`: the command every Daedalus hook registers. It always exits 0."""

import json
import sys


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    out = ""
    try:
        event = argv[0] if argv else ""
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        event = event or str(payload.get("hook_event_name", ""))
        from .core import dispatch
        out = dispatch(event, payload)
    except BaseException:  # never block a prompt or a tool call; exit 2 would erase a prompt
        out = ""
    if out:
        try:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
        except BaseException:
            pass
    return 0


def entry() -> None:
    """Console-script entry point."""
    try:
        main()
    finally:
        raise SystemExit(0)
