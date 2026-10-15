"""
A small JSON-over-HTTPS client for sources, on the standard library.

Every request goes through `_transport`, which tests replace with `set_transport()` so nothing
reaches a live service (they also disable sockets, so a missed stub fails loudly).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from .base import SourceError

# (method, url, headers, body bytes or None) -> (status, response headers, body bytes)
Transport = Callable[[str, str, dict, Optional[bytes]], tuple[int, dict, bytes]]


def _urllib_transport(method: str, url: str, headers: dict, body: Optional[bytes]) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""
    except (urllib.error.URLError, OSError) as e:
        raise SourceError(f"Couldn't reach {url.split('?')[0]}: {e}", "unreachable")


_transport: Transport = _urllib_transport


def set_transport(transport: Optional[Transport]) -> None:
    """Replace the transport (tests); None restores the real one."""
    global _transport
    _transport = transport or _urllib_transport


def request(method: str, url: str, headers: dict, payload: Any = None,
            content_type: str = "application/json") -> tuple[Any, dict]:
    """(parsed JSON body or None, response headers). Raises SourceError on 401/403 (auth-failed) and on
    other failures (unreachable)."""
    body = None
    headers = dict(headers)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = content_type
    status, resp_headers, raw = _transport(method, url, headers, body)
    if status in (401, 403):
        raise SourceError(f"{method} {url.split('?')[0]} was refused ({status}): check the token", "auth-failed")
    if status >= 400:
        snippet = raw[:200].decode("utf-8", "replace") if raw else ""
        raise SourceError(f"{method} {url.split('?')[0]} failed ({status}): {snippet}", "unreachable")
    if not raw:
        return None, resp_headers
    try:
        return json.loads(raw.decode("utf-8")), resp_headers
    except (ValueError, UnicodeDecodeError):
        raise SourceError(f"{method} {url.split('?')[0]} returned something that isn't JSON", "unreachable")


def next_link(headers: dict) -> Optional[str]:
    """The rel="next" URL from a Link header (GitHub's pagination), or None."""
    link = next((v for k, v in headers.items() if k.lower() == "link"), "")
    for part in link.split(","):
        if 'rel="next"' in part:
            return part.split(";")[0].strip().strip("<>")
    return None
