from db import dict_cursor

# Arbitrary namespace for pg_advisory_xact_lock's two-arg form, so this lock
# class can never collide with an unrelated advisory lock added later.
_SESSION_LOCK_NAMESPACE = 8711


class SessionAlreadyActiveError(Exception):
    """Raised by start() when the user already has a running session. The only
    guard against two concurrent runs used to be _RunGuard, an in-process flag
    in JobAgent's Flask dashboard — it did nothing for a run launched directly
    from a terminal (collector/runner.py's run() called session_repository.start()
    unconditionally), which is exactly how two collectors ended up racing on the
    same user's data in production."""


def start(conn, user_id: int) -> int:
    cur = conn.cursor()
    # Held for this transaction only (released on commit/rollback when the
    # request ends), not for the run's duration — just enough to make the
    # check-then-insert below atomic against another concurrent start().
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (_SESSION_LOCK_NAMESPACE, user_id))
    if has_active_run(conn, user_id):
        raise SessionAlreadyActiveError()
    cur.execute("INSERT INTO sessions (user_id, status) VALUES (%s, 'running') RETURNING id", (user_id,))
    return cur.fetchone()[0]


def finish(conn, user_id: int, session_id: int, jobs_found: int, jobs_scored: int, status: str = "done") -> None:
    # finished_at must be UTC regardless of this Postgres session/server's timezone
    # setting: JobAgent's _days_since_last_run() parses it and diffs it against its
    # own datetime.utcnow() with no timezone conversion, so a naive CURRENT_TIMESTAMP
    # value (which follows the server's `timezone` GUC, not necessarily UTC) would
    # silently skew that math on any host not configured to UTC.
    cur = conn.cursor()
    cur.execute(
        """UPDATE sessions
           SET finished_at = (NOW() AT TIME ZONE 'utc'), jobs_found = %s, jobs_scored = %s, status = %s
           WHERE user_id = %s AND id = %s""",
        (jobs_found, jobs_scored, status, user_id, session_id),
    )


def cancel_active(conn, user_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE sessions SET status='cancelled', finished_at=(NOW() AT TIME ZONE 'utc')
           WHERE user_id = %s AND status='running'""",
        (user_id,),
    )


def has_active_run(conn, user_id: int) -> bool:
    """True if a session started within the last 6 hours is still running."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT id FROM sessions WHERE user_id = %s AND status = 'running' AND started_at > NOW() - INTERVAL '6 hours'",
        (user_id,),
    )
    return cur.fetchone() is not None


def get_last_finished_at(conn, user_id: int):
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT finished_at FROM sessions WHERE user_id = %s AND status = 'done' ORDER BY finished_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    return row["finished_at"] if row else None


def get_latest(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM sessions WHERE user_id = %s ORDER BY started_at DESC, id DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    return dict(row) if row else None
