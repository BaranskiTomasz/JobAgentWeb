import os

# Dedicated throwaway test DB/role on the VPS Postgres (reachable over the same
# WireGuard tunnel used for real traffic) — never the production "jobagent" DB.
# Must be set before `config`/`db` are imported anywhere below.
os.environ.setdefault("POSTGRES_HOST", "10.66.0.1")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "jobagentweb_test")
os.environ.setdefault("POSTGRES_USER", "jobagentweb_test")
os.environ.setdefault("POSTGRES_PASSWORD", "test_only_pw_923nf")

# TestClient talks to the app over a fake "http://testserver" (no real TLS) —
# a Secure-flagged session cookie would never come back on later requests,
# silently breaking every login-dependent test. Production always keeps the
# default (true), since the site is genuinely served over HTTPS there.
os.environ.setdefault("SESSION_HTTPS_ONLY", "false")
os.environ.setdefault("INVITE_CODE", "test-invite-code")

import pytest
from fastapi.testclient import TestClient

import db as db_module
import migrations
import security
from main import app


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    conn = db_module._get_pool().getconn()
    try:
        migrations.init_db(conn)
    finally:
        db_module._get_pool().putconn(conn)


@pytest.fixture(autouse=True)
def _clean_tables():
    conn = db_module._get_pool().getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            TRUNCATE users, job_postings, user_job_states, job_embeddings,
                     sessions, criteria, cv_profiles, preference_profiles,
                     usage_log, cost_summaries, excluded_search_queries,
                     candidate_preferences, dismissed_score_items, search_stats
            RESTART IDENTITY CASCADE
        """)
        conn.commit()
    finally:
        db_module._get_pool().putconn(conn)
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_conn():
    """A raw pooled connection for tests that need to set up data no API can
    produce (e.g. legacy pre-migration row shapes)."""
    conn = db_module._get_pool().getconn()
    try:
        yield conn
    finally:
        db_module._get_pool().putconn(conn)


def _insert_user(username: str, password: str, is_admin: bool = False) -> dict:
    conn = db_module._get_pool().getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, %s) RETURNING id",
            (username, security.hash_password(password), 1 if is_admin else 0),
        )
        uid = cur.fetchone()[0]
        conn.commit()
        return {"id": uid, "username": username, "password": password}
    finally:
        db_module._get_pool().putconn(conn)


@pytest.fixture
def user(_clean_tables) -> dict:
    """A fresh user row (with a known plaintext password) for tests that need
    to own data or log in. Depends on _clean_tables so the insert always
    happens after truncation, not before it."""
    return _insert_user("testuser", "testpass123")


@pytest.fixture
def other_user(_clean_tables) -> dict:
    """A second, distinct user — for tests asserting per-user isolation."""
    return _insert_user("otheruser", "otherpass123")


@pytest.fixture
def admin_user(_clean_tables) -> dict:
    return _insert_user("adminuser", "adminpass123", is_admin=True)


def _login(c: TestClient, creds: dict) -> TestClient:
    resp = c.post("/login", data={"username": creds["username"], "password": creds["password"]})
    assert resp.status_code in (200, 303), resp.text
    return c


@pytest.fixture
def logged_in_client(user) -> TestClient:
    return _login(TestClient(app), user)


@pytest.fixture
def other_logged_in_client(other_user) -> TestClient:
    return _login(TestClient(app), other_user)


@pytest.fixture
def admin_client(admin_user) -> TestClient:
    return _login(TestClient(app), admin_user)
