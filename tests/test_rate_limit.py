from collections import defaultdict, deque
from unittest.mock import MagicMock

import pytest

import config
import rate_limit


@pytest.fixture(autouse=True)
def _isolated_rate_limit_state(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(rate_limit, "_attempts", defaultdict(deque))
    yield


def _request():
    req = MagicMock()
    req.client.host = "203.0.113.1"
    return req


def test_stale_keys_are_evicted_once_the_tracked_count_crosses_the_threshold(monkeypatch):
    # Regression guard: a key whose window has fully expired has no request
    # left to prune it via its own enforce() call — this is the only other
    # place stale entries get cleaned up, and it only engages once the dict
    # has actually grown large (checked below via the low threshold).
    monkeypatch.setattr(rate_limit, "_MAX_TRACKED_KEYS", 2)
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: 1_000_000.0)
    rate_limit.enforce(_request(), "login", key="ghost-1")

    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: 1_000_000.0 + rate_limit._WINDOW_SECONDS + 1)
    rate_limit.enforce(_request(), "login", key="ghost-2")
    # Crossing _MAX_TRACKED_KEYS on this third call triggers the sweep — "ghost-1"'s
    # window has long since expired and should be gone.
    rate_limit.enforce(_request(), "login", key="ghost-3")

    assert "login:ghost-1" not in rate_limit._attempts
    assert "login:ghost-3" in rate_limit._attempts


def test_recent_keys_survive_the_sweep(monkeypatch):
    monkeypatch.setattr(rate_limit, "_MAX_TRACKED_KEYS", 2)
    rate_limit.enforce(_request(), "login", key="active-user")
    rate_limit.enforce(_request(), "login", key="ghost-2")
    rate_limit.enforce(_request(), "login", key="ghost-3")

    assert "login:active-user" in rate_limit._attempts


def test_sweep_does_not_run_below_the_threshold():
    rate_limit.enforce(_request(), "login", key="solo")
    assert len(rate_limit._attempts) == 1
