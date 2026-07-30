from db import dict_cursor


def exclude(conn, user_id: int, source: str, search_query: str, reason: str) -> None:
    """Idempotent — re-excluding an already-excluded query updates its reason
    instead of erroring, so a re-run with fresher stats keeps the log current."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO excluded_search_queries (user_id, source, search_query, reason)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (user_id, source, search_query) DO UPDATE SET reason = excluded.reason""",
        (user_id, source, search_query, reason),
    )


def get_excluded(conn, user_id: int, source: str) -> dict[str, str]:
    """search_query -> reason, for filtering a source's query list before collection."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT search_query, reason FROM excluded_search_queries WHERE user_id = %s AND source = %s",
        (user_id, source),
    )
    return {r["search_query"]: r["reason"] for r in cur.fetchall()}


def get_all(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM excluded_search_queries WHERE user_id = %s ORDER BY excluded_at DESC",
        (user_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def reinstate(conn, user_id: int, excluded_id: int) -> None:
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM excluded_search_queries WHERE user_id = %s AND id = %s",
        (user_id, excluded_id),
    )
