"""Minimal in-memory rate limiter for auth endpoints. No Redis in this stack and
this runs on a single small VPS, so a per-process fixed window is enough to
blunt brute-force/username-enumeration attempts without adding an external
dependency. Not perfectly enforced across uvicorn's multiple worker processes
(each keeps its own counters), but still meaningfully raises the cost of
guessing either way.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

import config

_WINDOW_SECONDS = 60
_MAX_ATTEMPTS = 10

_lock = threading.Lock()
_attempts: dict[str, deque] = defaultdict(deque)


def enforce(request: Request, bucket: str, key: str | None = None) -> None:
    """Raises 429 if `key` has hit `bucket` too many times recently. `key`
    defaults to the connecting IP — fine for /register (rare, and Caddy's
    reverse_proxy means every real request arrives from 127.0.0.1 anyway, so
    IP-keying there just means "not too many registration attempts at once",
    which is the actual goal). /login passes the submitted username instead:
    keying that one by IP would bucket every real user together behind
    Caddy's loopback connection, so one person mistyping a password would
    lock everyone else out too."""
    if not config.RATE_LIMIT_ENABLED:
        return
    if key is None:
        key = request.client.host if request.client else "unknown"
    key = f"{bucket}:{key}"
    now = time.monotonic()
    with _lock:
        hits = _attempts[key]
        while hits and now - hits[0] > _WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many attempts — try again in a minute.")
        hits.append(now)
