import threading
from datetime import datetime, timedelta

import db as db_module
import sessions_repo


def test_start_and_finish(logged_in_client):
    session_id = logged_in_client.post("/api/sessions").json()["id"]
    assert logged_in_client.get("/api/sessions/has-active").json()["active"] is True

    logged_in_client.patch(f"/api/sessions/{session_id}/finish", json={"jobs_found": 12, "jobs_scored": 10})
    assert logged_in_client.get("/api/sessions/has-active").json()["active"] is False

    latest = logged_in_client.get("/api/sessions/latest").json()["session"]
    assert latest["jobs_found"] == 12
    assert latest["status"] == "done"

    assert logged_in_client.get("/api/sessions/last-finished").json()["finished_at"] is not None


def test_cancel_active(logged_in_client):
    logged_in_client.post("/api/sessions")
    logged_in_client.post("/api/sessions/cancel-active")
    assert logged_in_client.get("/api/sessions/has-active").json()["active"] is False
    latest = logged_in_client.get("/api/sessions/latest").json()["session"]
    assert latest["status"] == "cancelled"


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/sessions")
    assert other_logged_in_client.get("/api/sessions/has-active").json()["active"] is False
    assert other_logged_in_client.get("/api/sessions/latest").json()["session"] is None


def test_last_finished_uses_most_recent_done_session(user, logged_in_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s)",
        (user["id"], datetime.utcnow() - timedelta(hours=100)),
    )
    cur.execute(
        "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s)",
        (user["id"], datetime.utcnow() - timedelta(hours=10)),
    )
    db_conn.commit()

    finished_at = logged_in_client.get("/api/sessions/last-finished").json()["finished_at"]
    finished_dt = datetime.fromisoformat(finished_at)
    assert abs((finished_dt - (datetime.utcnow() - timedelta(hours=10))).total_seconds()) < 5


def test_last_finished_ignores_cancelled_sessions(user, logged_in_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'cancelled', %s)",
        (user["id"], datetime.utcnow() - timedelta(hours=1)),
    )
    db_conn.commit()

    assert logged_in_client.get("/api/sessions/last-finished").json()["finished_at"] is None


def test_last_collected_is_null_until_marked(logged_in_client):
    session_id = logged_in_client.post("/api/sessions").json()["id"]
    logged_in_client.patch(f"/api/sessions/{session_id}/finish", json={"jobs_found": 0, "jobs_scored": 0})
    assert logged_in_client.get("/api/sessions/last-collected").json()["collected_at"] is None


def test_mark_collected_sets_last_collected(logged_in_client):
    session_id = logged_in_client.post("/api/sessions").json()["id"]
    logged_in_client.post(f"/api/sessions/{session_id}/mark-collected")
    assert logged_in_client.get("/api/sessions/last-collected").json()["collected_at"] is not None


def test_last_collected_ignores_sessions_that_never_collected(user, logged_in_client, db_conn):
    # Regression: a ranking/rescoring/re-evaluating session finishes 'done' just
    # like a real collection does — only collected_at (set by mark-collected, not
    # by finish()) should move the "since last collection" window forward.
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s)",
        (user["id"], datetime.utcnow()),
    )
    db_conn.commit()
    assert logged_in_client.get("/api/sessions/last-collected").json()["collected_at"] is None


def test_last_collected_uses_most_recent_mark(user, logged_in_client, db_conn):
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO sessions (user_id, status, collected_at) VALUES (%s, 'done', %s)",
        (user["id"], datetime.utcnow() - timedelta(hours=100)),
    )
    cur.execute(
        "INSERT INTO sessions (user_id, status, collected_at) VALUES (%s, 'done', %s)",
        (user["id"], datetime.utcnow() - timedelta(hours=10)),
    )
    db_conn.commit()

    collected_at = logged_in_client.get("/api/sessions/last-collected").json()["collected_at"]
    collected_dt = datetime.fromisoformat(collected_at)
    assert abs((collected_dt - (datetime.utcnow() - timedelta(hours=10))).total_seconds()) < 5


def test_mark_collected_is_scoped_to_the_caller(logged_in_client, other_logged_in_client):
    session_id = logged_in_client.post("/api/sessions").json()["id"]
    # Another user's session id doesn't exist for this caller — mark-collected is a
    # no-op UPDATE (0 rows), not a cross-tenant leak.
    other_logged_in_client.post(f"/api/sessions/{session_id}/mark-collected")
    assert other_logged_in_client.get("/api/sessions/last-collected").json()["collected_at"] is None


def test_finish_writes_utc_regardless_of_session_timezone(user, db_conn):
    # Regression: JobAgent's _days_since_last_run() parses finished_at and diffs it
    # against its own datetime.utcnow() with no timezone conversion. If finished_at
    # followed this Postgres session/server's `timezone` GUC instead of always being
    # UTC, that comparison would silently skew on any host not configured to UTC.
    cur = db_conn.cursor()
    cur.execute("SET timezone = 'America/New_York'")
    cur.execute("INSERT INTO sessions (user_id, status) VALUES (%s, 'running') RETURNING id", (user["id"],))
    session_id = cur.fetchone()[0]

    sessions_repo.finish(db_conn, user["id"], session_id, jobs_found=1, jobs_scored=1)
    db_conn.commit()

    finished_at = sessions_repo.get_last_finished_at(db_conn, user["id"])
    assert abs((finished_at - datetime.utcnow()).total_seconds()) < 5


def test_second_concurrent_start_is_rejected(user):
    # Regression: the only guard against two concurrent runs used to be
    # _RunGuard, an in-process flag in JobAgent's Flask dashboard — it did
    # nothing for a run launched directly from a terminal, since
    # collector/runner.py's run() called session_repository.start()
    # unconditionally with no check first. That's exactly how two collectors
    # ended up racing on the same user's data in production. start() now
    # atomically checks-and-inserts under a pg_advisory_xact_lock, so this
    # must hold even under a genuine simultaneous race, not just sequentially.
    results = {}
    errors = {}
    barrier = threading.Barrier(2)

    def _start(key):
        conn = db_module._get_pool().getconn()
        try:
            barrier.wait(timeout=5)
            results[key] = sessions_repo.start(conn, user["id"])
            conn.commit()
        except sessions_repo.SessionAlreadyActiveError as e:
            conn.rollback()
            errors[key] = e
        finally:
            db_module._get_pool().putconn(conn)

    t1 = threading.Thread(target=_start, args=("a",))
    t2 = threading.Thread(target=_start, args=("b",))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert len(results) == 1
    assert len(errors) == 1


def test_start_rejected_while_run_active(logged_in_client):
    logged_in_client.post("/api/sessions")
    resp = logged_in_client.post("/api/sessions")
    assert resp.status_code == 409
    assert "cancel-active" in resp.json()["detail"]


def test_start_allowed_again_after_cancel_active(logged_in_client):
    logged_in_client.post("/api/sessions")
    logged_in_client.post("/api/sessions/cancel-active")
    resp = logged_in_client.post("/api/sessions")
    assert resp.status_code == 200
