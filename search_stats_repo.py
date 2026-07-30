from db import dict_cursor


def record(conn, user_id: int, session_id: int, source: str, search_query: str, location: str,
           cards_found: int, new_found: int) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO search_stats (user_id, session_id, source, search_query, location, cards_found, new_found)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (user_id, session_id, source, search_query, location, cards_found, new_found),
    )


def get_query_summary(conn, user_id: int, source: str) -> list[dict]:
    """Per search_query totals across all recorded runs — zero_result_searches counts
    individual (query, location) calls that found no cards at all, not full runs."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT
               search_query,
               COUNT(*)                                        AS total_searches,
               SUM(CASE WHEN cards_found = 0 THEN 1 ELSE 0 END) AS zero_result_searches,
               SUM(new_found)                                  AS total_new_found,
               MAX(searched_at)                                AS last_searched_at
           FROM search_stats
           WHERE user_id = %s AND source = %s
           GROUP BY search_query
           ORDER BY search_query""",
        (user_id, source),
    )
    return [dict(r) for r in cur.fetchall()]


def get_zero_yield_queries(conn, user_id: int, source: str, min_searches: int) -> list[str]:
    """search_query values searched at least min_searches times for this source
    where every single search found zero *new* jobs."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT search_query
           FROM search_stats
           WHERE user_id = %s AND source = %s
           GROUP BY search_query
           HAVING COUNT(*) >= %s AND SUM(new_found) = 0""",
        (user_id, source, min_searches),
    )
    return [r["search_query"] for r in cur.fetchall()]
