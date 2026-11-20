from datetime import datetime

from db import dict_cursor


def record_event(
    conn,
    user_id: int,
    job_id: str,
    event_type: str,
    occurred_at: datetime | None = None,
    note: str | None = None,
) -> dict:
    """Record and return a recruitment funnel event."""
    cur = dict_cursor(conn)
    cur.execute(
        """INSERT INTO job_application_events (user_id, job_id, event_type, occurred_at, note)
           VALUES (%s, %s, %s, COALESCE(%s, CURRENT_TIMESTAMP), %s)
           RETURNING *""",
        (user_id, job_id, event_type, occurred_at, note),
    )
    # No conn.commit() here: db.get_db() commits once per request after the
    # handler returns (and rolls back on any exception) -- no repo function
    # in this codebase commits for itself, since a handler combining this
    # with other writes must stay one all-or-nothing transaction.
    return dict(cur.fetchone())


def list_events_for_job(conn, user_id: int, job_id: str) -> list[dict]:
    """Return recruitment funnel events for a user's job, newest first."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT * FROM job_application_events
           WHERE user_id = %s AND job_id = %s
           ORDER BY occurred_at DESC""",
        (user_id, job_id),
    )
    return [dict(row) for row in cur.fetchall()]
