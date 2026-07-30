from db import dict_cursor


def start(conn, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO sessions (user_id, status) VALUES (%s, 'running') RETURNING id", (user_id,))
    return cur.fetchone()[0]


def finish(conn, user_id: int, session_id: int, jobs_found: int, jobs_scored: int, status: str = "done") -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE sessions
           SET finished_at = CURRENT_TIMESTAMP, jobs_found = %s, jobs_scored = %s, status = %s
           WHERE user_id = %s AND id = %s""",
        (jobs_found, jobs_scored, status, user_id, session_id),
    )


def cancel_active(conn, user_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE sessions SET status='cancelled', finished_at=CURRENT_TIMESTAMP
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
