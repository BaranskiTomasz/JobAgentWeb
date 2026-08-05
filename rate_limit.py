# In-memory fixed-window limiter, per uvicorn worker process (no shared store
# behind it), which is enough to blunt brute-force/enumeration on a small VPS.
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

import config

_WINDOW_SECONDS = 60
_MAX_ATTEMPTS = 10

# A key tried only once (e.g. one enumeration attempt) never gets pruned by
# enforce()'s own per-key check, so sweep the whole dict once it grows large.
_MAX_TRACKED_KEYS = 10_000

_lock = threading.Lock()
_attempts: dict[str, deque] = defaultdict(deque)


def enforce(request: Request, bucket: str, key: str | None = None) -> None:
    # key defaults to the connecting IP, but /login passes the submitted
    # username instead: every real request arrives from Caddy's loopback IP,
    # so IP-keying there would lock out every user whenever one mistypes a
    # password.
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
            raise HTTPException(status_code=429, detail="Too many attempts, try again in a minute.")
        hits.append(now)
        if len(_attempts) > _MAX_TRACKED_KEYS:
            _evict_stale_keys(now)


def _evict_stale_keys(now: float) -> None:
    stale = [k for k, hits in _attempts.items() if not hits or now - hits[-1] > _WINDOW_SECONDS]
    for k in stale:
        del _attempts[k]
