from datetime import datetime, timedelta


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


def test_finish_writes_utc_regardless_of_session_timezone(user, db_conn):
    # Regression: JobAgent's _days_since_last_run() parses finished_at and diffs it
    # against its own datetime.utcnow() with no timezone conversion. If finished_at
    # followed this Postgres session/server's `timezone` GUC instead of always being
    # UTC, that comparison would silently skew on any host not configured to UTC.
    import sessions_repo

    cur = db_conn.cursor()
    cur.execute("SET timezone = 'America/New_York'")
    cur.execute("INSERT INTO sessions (user_id, status) VALUES (%s, 'running') RETURNING id", (user["id"],))
    session_id = cur.fetchone()[0]

    sessions_repo.finish(db_conn, user["id"], session_id, jobs_found=1, jobs_scored=1)
    db_conn.commit()

    finished_at = sessions_repo.get_last_finished_at(db_conn, user["id"])
    assert abs((finished_at - datetime.utcnow()).total_seconds()) < 5
