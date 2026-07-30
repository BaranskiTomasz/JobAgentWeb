from db import dict_cursor


def insert(conn, user_id: int, job_id: str, item_type: str, item_text: str, reason: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO dismissed_score_items (user_id, job_id, item_type, item_text, reason) VALUES (%s, %s, %s, %s, %s)",
        (user_id, job_id, item_type, item_text, reason),
    )


def get_for_job(conn, user_id: int, job_id: str) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT item_type, item_text, reason, created_at FROM dismissed_score_items "
        "WHERE user_id = %s AND job_id = %s ORDER BY id",
        (user_id, job_id),
    )
    return [dict(r) for r in cur.fetchall()]


def get_recent(conn, user_id: int, limit: int = 50) -> list[dict]:
    """Most recent dismissals across all of this user's jobs, for the distillation prompt."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT d.item_type, d.item_text, d.reason, d.created_at, jp.title, jp.company
           FROM dismissed_score_items d JOIN job_postings jp ON jp.id = d.job_id
           WHERE d.user_id = %s
           ORDER BY d.id DESC LIMIT %s""",
        (user_id, limit),
    )
    return [dict(r) for r in cur.fetchall()]


def count_all(conn, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dismissed_score_items WHERE user_id = %s", (user_id,))
    return cur.fetchone()[0]
