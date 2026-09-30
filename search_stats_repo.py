from db import dict_cursor


def record(conn, user_id: int, session_id: int, source: str, search_query: str, location: str,
           cards_found: int, new_found: int, upstream_found: int | None = None,
           query_matched: int | None = None, date_matched: int | None = None,
           geo_matched: int | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO search_stats (user_id, session_id, source, search_query, location, cards_found, new_found,
                                     upstream_found, query_matched, date_matched, geo_matched)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (user_id, session_id, source, search_query, location, cards_found, new_found,
         upstream_found, query_matched, date_matched, geo_matched),
    )


def get_query_summary(conn, user_id: int, source: str) -> list[dict]:
    # zero_result_searches counts individual (query, location) calls that found
    # no cards, not full collector runs.
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT
               search_query,
               COUNT(*)                                        AS total_searches,
               SUM(CASE WHEN cards_found = 0 THEN 1 ELSE 0 END) AS zero_result_searches,
               SUM(new_found)                                  AS total_new_found,
               SUM(COALESCE(upstream_found, cards_found))       AS upstream_found,
               SUM(COALESCE(query_matched, cards_found))        AS query_matched,
               SUM(COALESCE(date_matched, cards_found))         AS date_matched,
               SUM(COALESCE(geo_matched, cards_found))          AS geo_matched,
               MAX(searched_at)                                AS last_searched_at
           FROM search_stats
           WHERE user_id = %s AND source = %s
           GROUP BY search_query
           ORDER BY search_query""",
        (user_id, source),
    )
    return [dict(r) for r in cur.fetchall()]


_ZERO_YIELD_LOOKBACK_DAYS = 30


def get_zero_yield_queries(conn, user_id: int, source: str, min_searches: int) -> list[str]:
    # Windowed to the trailing days, not all-time: an all-time count would let a
    # few quiet days anywhere in a query's history exclude it permanently, with
    # no way to recover once the market picks back up.
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT search_query
           FROM search_stats
           WHERE user_id = %s AND source = %s AND searched_at >= NOW() - INTERVAL '1 day' * %s
           GROUP BY search_query
           HAVING COUNT(*) >= %s AND SUM(COALESCE(geo_matched, cards_found)) = 0""",
        (user_id, source, _ZERO_YIELD_LOOKBACK_DAYS, min_searches),
    )
    return [r["search_query"] for r in cur.fetchall()]
