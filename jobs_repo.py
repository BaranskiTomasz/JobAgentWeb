import hashlib
import json

from psycopg2.extras import execute_values

from db import dict_cursor

# Explicit aliases: both tables have an `id` column, and `jp.*, ujs.*` would let one clobber the other.
_JOB_COLUMNS = """
    jp.id, jp.title, jp.company, jp.location, jp.url, jp.description, jp.source,
    jp.source_id, jp.search_query, jp.structured_data,
    jp.created_at AS posting_created_at, jp.updated_at AS posting_updated_at,
    ujs.status, ujs.score, ujs.score_reason, ujs.score_breakdown, ujs.rejection_reason,
    ujs.embedding_score, ujs.rerank_score, ujs.listwise_rank, ujs.rank_reason,
    ujs.debate_flag, ujs.debate_note, ujs.would_apply, ujs.would_apply_reason,
    ujs.created_at, ujs.updated_at
"""
_JOB_FROM = "FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id"


def _generate_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


def _row_to_job(row: dict) -> dict:
    row = dict(row)
    if row.get("would_apply") is not None:
        row["would_apply"] = bool(row["would_apply"])
    return row


def insert(conn, user_id: int, job: dict) -> dict:
    """job_id is None only if this user already has a state for this posting.
    posting_created=False (posting known from another user) tells the caller to
    skip re-fetching/re-extracting.

    Atomic (ON CONFLICT DO NOTHING), not check-then-insert: two collectors
    racing on the same URL — e.g. two runs started within a second of each
    other, which is exactly what happened in production once — used to hit a
    duplicate-key error on the second insert, which the collector's generic
    except-and-skip swallowed, leaving that run's caller with no state row and
    no error either. job_id is deterministic from the URL (_generate_id), so
    it's correct whether or not this call's own INSERT is the one that wins."""
    cur = dict_cursor(conn)
    job_id = _generate_id(job["url"])

    cur.execute(
        # No conflict target: id and url are both unique constraints on this
        # table and both are deterministic from the same url, so a genuine
        # concurrent race can trip either one depending on timing — targeting
        # just one (e.g. "ON CONFLICT (url)") leaves the other race window open.
        """INSERT INTO job_postings (id, title, company, location, url, description, source, source_id, search_query)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        (job_id, job["title"], job.get("company"), job.get("location"), job["url"],
         job.get("description"), job.get("source", "linkedin"), job.get("source_id"),
         job.get("search_query")),
    )
    posting_created = cur.fetchone() is not None

    cur.execute(
        "INSERT INTO user_job_states (user_id, job_id) VALUES (%s, %s) ON CONFLICT (user_id, job_id) DO NOTHING RETURNING id",
        (user_id, job_id),
    )
    if cur.fetchone() is None:
        return {"job_id": None, "posting_created": False}

    return {"job_id": job_id, "posting_created": posting_created}


def get_by_id(conn, user_id: int, job_id: str) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s AND jp.id = %s",
        (user_id, job_id),
    )
    row = cur.fetchone()
    return _row_to_job(row) if row else None


def search(
    conn,
    user_id: int,
    status: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    source: str | None = None,
) -> list[dict]:
    cur = dict_cursor(conn)
    sql = f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s"
    params: list = [user_id]

    if status and status != "all":
        sql += " AND ujs.status = %s"
        params.append(status)
    if min_score is not None:
        sql += " AND ujs.score >= %s"
        params.append(min_score)
    if query:
        sql += (" AND (jp.title ILIKE %s OR jp.company ILIKE %s OR jp.location ILIKE %s"
                 " OR jp.description ILIKE %s OR ujs.score_reason ILIKE %s OR ujs.rank_reason ILIKE %s)")
        params += [f"%{query}%"] * 6
    if source:
        sql += " AND jp.source = %s"
        params.append(source)

    sql += (" ORDER BY ujs.score DESC NULLS LAST, ujs.rerank_score DESC NULLS LAST,"
            " ujs.embedding_score DESC NULLS LAST, ujs.created_at DESC")
    cur.execute(sql, params)
    return [_row_to_job(r) for r in cur.fetchall()]


def update_status(conn, user_id: int, job_id: str, status: str, rejection_reason: str | None = None) -> None:
    cur = conn.cursor()
    if status == "rejected" and rejection_reason is not None:
        cur.execute(
            "UPDATE user_job_states SET status = %s, rejection_reason = %s, updated_at = CURRENT_TIMESTAMP"
            " WHERE user_id = %s AND job_id = %s",
            (status, rejection_reason, user_id, job_id),
        )
    else:
        cur.execute(
            "UPDATE user_job_states SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s AND job_id = %s",
            (status, user_id, job_id),
        )


def update_score(conn, user_id: int, job_id: str, score: float | None, reason: str, breakdown: dict | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET score = %s, score_reason = %s, score_breakdown = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (score, reason, json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None, user_id, job_id),
    )


def update_ranking_scores(
    conn,
    user_id: int,
    job_id: str,
    embedding_score: float | None,
    rerank_score: float | None,
    listwise_rank: int | None,
    rank_reason: str | None = None,
    debate_flag: str | None = None,
    debate_note: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE user_job_states
           SET embedding_score = %s, rerank_score = %s, listwise_rank = %s, rank_reason = %s,
               debate_flag = %s, debate_note = %s, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = %s AND job_id = %s""",
        (embedding_score, rerank_score, listwise_rank, rank_reason, debate_flag, debate_note, user_id, job_id),
    )


def update_would_apply(conn, user_id: int, job_id: str, would_apply: bool, reason: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET would_apply = %s, would_apply_reason = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (1 if would_apply else 0, reason, user_id, job_id),
    )


def update_ranking_scores_batch(conn, user_id: int, items: list[dict]) -> int:
    """One round-trip for the whole batch instead of one PATCH per job — rank_jobs.py
    writes back a score for every job in the active pool on every run (hundreds of
    rows), which used to mean that many separate SELECT+UPDATE+SELECT round-trips.
    Rows for job_ids this user has no state for simply match nothing (same
    authorization shape as the single-job endpoint's per-row user_id scoping, just
    without a 404 for a mismatch — a batch silently skipping an unknown id is the
    right behavior here, not an error for the whole batch)."""
    if not items:
        return 0
    cur = conn.cursor()
    rows = [
        (user_id, item["job_id"], item.get("embedding_score"), item.get("rerank_score"),
         item.get("listwise_rank"), item.get("rank_reason"), item.get("debate_flag"), item.get("debate_note"))
        for item in items
    ]
    execute_values(
        cur,
        """UPDATE user_job_states AS ujs
           SET embedding_score = v.embedding_score::real,
               rerank_score = v.rerank_score::real,
               listwise_rank = v.listwise_rank::integer,
               rank_reason = v.rank_reason::text,
               debate_flag = v.debate_flag::text,
               debate_note = v.debate_note::text,
               updated_at = CURRENT_TIMESTAMP
           FROM (VALUES %s) AS v(user_id, job_id, embedding_score, rerank_score, listwise_rank, rank_reason, debate_flag, debate_note)
           WHERE ujs.user_id = v.user_id::integer AND ujs.job_id = v.job_id::text""",
        rows,
    )
    return cur.rowcount


def update_would_apply_batch(conn, user_id: int, items: list[dict]) -> int:
    if not items:
        return 0
    cur = conn.cursor()
    rows = [(user_id, item["job_id"], 1 if item["would_apply"] else 0, item["reason"]) for item in items]
    execute_values(
        cur,
        """UPDATE user_job_states AS ujs
           SET would_apply = v.would_apply::integer, would_apply_reason = v.reason::text, updated_at = CURRENT_TIMESTAMP
           FROM (VALUES %s) AS v(user_id, job_id, would_apply, reason)
           WHERE ujs.user_id = v.user_id::integer AND ujs.job_id = v.job_id::text""",
        rows,
    )
    return cur.rowcount


def update_structured_data(conn, job_id: str, data: dict) -> None:
    """Shared, not user-scoped — structured_data is an LLM extraction of the
    posting itself (stack/seniority/remote/etc.), true for every user who sees
    this posting, so whoever extracts it first benefits everyone else too.
    Write-once (only fills a NULL value): any authenticated user who has ever
    linked to this posting can call this endpoint, so without this guard one
    user could silently overwrite another user's already-extracted data."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE job_postings SET structured_data = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = %s AND structured_data IS NULL",
        (json.dumps(data, ensure_ascii=False), job_id),
    )


def get_stats(conn, user_id: int) -> dict:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT
            COUNT(*)                                                    AS total,
            COUNT(CASE WHEN status = 'new'           THEN 1 END)        AS new,
            COUNT(CASE WHEN status = 'reviewed'      THEN 1 END)        AS reviewed,
            COUNT(CASE WHEN status = 'applied'       THEN 1 END)        AS applied,
            COUNT(CASE WHEN status = 'rejected'      THEN 1 END)        AS rejected,
            COUNT(CASE WHEN status = 'auto_rejected' THEN 1 END)        AS auto_rejected,
            ROUND(AVG(CASE WHEN score IS NOT NULL THEN score END)::numeric, 2) AS avg_score,
            ROUND(AVG(CASE WHEN status = 'new' AND score IS NOT NULL THEN score END)::numeric, 2) AS avg_score_new
        FROM user_job_states
        WHERE user_id = %s
    """, (user_id,))
    row = dict(cur.fetchone())

    cur.execute(
        "SELECT finished_at FROM sessions WHERE user_id = %s AND status = 'done' ORDER BY finished_at DESC LIMIT 1",
        (user_id,),
    )
    last = cur.fetchone()
    row["last_run"] = last["finished_at"] if last else None

    cur.execute(
        "SELECT COUNT(*) FROM user_job_states WHERE user_id = %s AND listwise_rank IS NOT NULL AND status = 'new'",
        (user_id,),
    )
    row["ranked"] = cur.fetchone()[0]
    return row


def get_all_urls(conn, user_id: int) -> set[str]:
    """URLs of postings *this user* already has a state row for. Scoped by
    user, not system-wide: most collector sources skip a card outright when
    its URL is already "known" (never calling insert() at all), so a global
    set here meant a second user's collector silently skipped every posting
    the first user had already found — the shared pool never actually got
    shared. A URL unknown to this user still resolves correctly in insert()
    (reuses the existing job_postings row, just adds this user's state row)."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT jp.url FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id WHERE ujs.user_id = %s",
        (user_id,),
    )
    return {r["url"] for r in cur.fetchall()}


def get_missing_descriptions(conn, user_id: int) -> list[dict]:
    """This user's jobs (any source) without a description that are not yet
    scored — candidates for backfill."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.id, jp.url, jp.source FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND (jp.description IS NULL OR jp.description = '') AND ujs.score IS NULL
           ORDER BY jp.created_at DESC""",
        (user_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def update_description(conn, job_id: str, description: str) -> None:
    """Shared, not user-scoped, write-once — same reasoning as update_structured_data."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE job_postings SET description = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = %s AND (description IS NULL OR description = '')",
        (description, job_id),
    )


def update_score_and_status(conn, user_id: int, job_id: str, score: float | None, reason: str, status: str, breakdown: dict | None = None) -> None:
    """Atomic combined update — mirrors the old single-table version."""
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET score = %s, score_reason = %s, score_breakdown = %s, status = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (score, reason, json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None, status, user_id, job_id),
    )


def get_new(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s AND ujs.status = 'new' ORDER BY ujs.created_at DESC",
        (user_id,),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_unscored(conn, user_id: int) -> list[dict]:
    """This user's jobs that are new and have not been scored yet."""
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.status = 'new' AND ujs.score IS NULL
              AND jp.description IS NOT NULL AND jp.description != ''
            ORDER BY ujs.created_at DESC""",
        (user_id,),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_new_with_descriptions(conn, user_id: int) -> list[dict]:
    """All this user's 'new' jobs that have descriptions — used for force-rescore."""
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.status = 'new'
              AND jp.description IS NOT NULL AND jp.description != ''
            ORDER BY ujs.created_at DESC""",
        (user_id,),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_examples(conn, user_id: int, limit_positive: int = 25, limit_negative: int = 25) -> tuple[list[dict], list[dict]]:
    cur = dict_cursor(conn)
    cur.execute(
        f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s AND ujs.status = 'applied' "
        "ORDER BY ujs.updated_at DESC LIMIT %s",
        (user_id, limit_positive),
    )
    positive = [_row_to_job(r) for r in cur.fetchall()]
    cur.execute(
        f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s AND ujs.status = 'rejected' "
        "ORDER BY (ujs.rejection_reason IS NOT NULL) DESC, ujs.updated_at DESC LIMIT %s",
        (user_id, limit_negative),
    )
    negative = [_row_to_job(r) for r in cur.fetchall()]
    return positive, negative


def get_all_feedback(conn, user_id: int) -> tuple[list[dict], list[dict]]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.title, jp.company, jp.location, jp.description, ujs.score_reason
           FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND ujs.status = 'applied' ORDER BY ujs.updated_at DESC""",
        (user_id,),
    )
    applied = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """SELECT jp.title, jp.company, jp.location, jp.description, ujs.rejection_reason, ujs.score_reason
           FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND ujs.status = 'rejected' ORDER BY ujs.updated_at DESC""",
        (user_id,),
    )
    rejected = [dict(r) for r in cur.fetchall()]
    return applied, rejected


def get_feedback_since(conn, user_id: int, since_timestamp: str) -> tuple[list[dict], list[dict]]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.title, jp.company, jp.location, jp.description, ujs.score_reason
           FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND ujs.status = 'applied' AND ujs.updated_at > %s ORDER BY ujs.updated_at DESC""",
        (user_id, since_timestamp),
    )
    applied = [dict(r) for r in cur.fetchall()]
    cur.execute(
        """SELECT jp.title, jp.company, jp.location, jp.description, ujs.rejection_reason, ujs.score_reason
           FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND ujs.status = 'rejected' AND ujs.updated_at > %s ORDER BY ujs.updated_at DESC""",
        (user_id, since_timestamp),
    )
    rejected = [dict(r) for r in cur.fetchall()]
    return applied, rejected


def _filter_sql(statuses: list[str], date_from: str | None, date_to: str | None) -> tuple[str, list]:
    placeholders = ",".join(["%s"] * len(statuses))
    sql = f"AND ujs.status IN ({placeholders})"
    params: list = list(statuses)
    if date_from:
        sql += " AND ujs.created_at >= %s"
        params.append(date_from)
    if date_to:
        sql += " AND ujs.created_at <= %s"
        params.append(date_to + " 23:59:59")
    return sql, params


def count_by_filter(conn, user_id: int, statuses: list[str], date_from: str | None = None, date_to: str | None = None) -> int:
    if not statuses:
        return 0
    where, params = _filter_sql(statuses, date_from, date_to)
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM user_job_states ujs WHERE ujs.user_id = %s {where}", [user_id, *params])
    return cur.fetchone()[0]


def delete_by_filter(conn, user_id: int, statuses: list[str], date_from: str | None = None, date_to: str | None = None) -> int:
    """'Delete' means remove from this user's view only — job_postings (shared
    with every other user who's found the same URL) is never touched."""
    if not statuses:
        return 0
    where, params = _filter_sql(statuses, date_from, date_to)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM user_job_states ujs WHERE ujs.user_id = %s {where}", [user_id, *params])
    return cur.rowcount


def get_jobs_for_ranking(conn, user_id: int, limit: int = 2000) -> list[dict]:
    """All this user's 'new' jobs with descriptions."""
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.status = 'new'
              AND jp.description IS NOT NULL AND jp.description != ''
            ORDER BY ujs.created_at DESC LIMIT %s""",
        (user_id, limit),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_applied_job_ids(conn, user_id: int) -> list[str]:
    cur = dict_cursor(conn)
    cur.execute("SELECT job_id FROM user_job_states WHERE user_id = %s AND status = 'applied'", (user_id,))
    return [r["job_id"] for r in cur.fetchall()]


def get_rejected_job_ids(conn, user_id: int) -> list[str]:
    cur = dict_cursor(conn)
    cur.execute("SELECT job_id FROM user_job_states WHERE user_id = %s AND status = 'rejected'", (user_id,))
    return [r["job_id"] for r in cur.fetchall()]


def count_decisions(conn, user_id: int) -> int:
    """Total number of applied + rejected decisions for this user. Used for the
    auto-distillation trigger."""
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_job_states WHERE user_id = %s AND status IN ('applied', 'rejected')",
        (user_id,),
    )
    return cur.fetchone()[0]


_PRUNING_LOOKBACK_DAYS = 30


def get_query_outcome_stats(conn, user_id: int, source: str) -> list[dict]:
    """Per search_query outcome totals for one source, for this user, over the
    trailing _PRUNING_LOOKBACK_DAYS. Windowed rather than all-time: a query that
    was reject-heavy a year ago but has been fine since shouldn't stay excluded
    forever on the strength of decisions the user has long moved past."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT
               jp.search_query,
               COUNT(*)                                                              AS terminal_total,
               SUM(CASE WHEN ujs.status IN ('rejected','auto_rejected') THEN 1 ELSE 0 END) AS reject_total,
               SUM(CASE WHEN ujs.status = 'applied'  THEN 1 ELSE 0 END)              AS applied_total,
               SUM(CASE WHEN ujs.status = 'reviewed' THEN 1 ELSE 0 END)              AS reviewed_total
           FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND jp.source = %s AND jp.search_query IS NOT NULL AND ujs.status != 'new'
             AND ujs.updated_at >= NOW() - INTERVAL '1 day' * %s
           GROUP BY jp.search_query""",
        (user_id, source, _PRUNING_LOOKBACK_DAYS),
    )
    return [dict(r) for r in cur.fetchall()]


def get_ranked(conn, user_id: int, statuses: list[str]) -> list[dict]:
    """Ranked jobs (any of the given statuses) ordered by listwise_rank — the
    calibration report's source of truth for precision@K / divergence cases.
    listwise_rank is only ever 1-20 and freezes the moment a job is decided
    (re-ranking only touches the live 'new' pool), so after enough decisions many
    rows share the same rank; the updated_at tiebreak surfaces the most recent
    ones first instead of an arbitrary (effectively oldest-first) tie order."""
    cur = dict_cursor(conn)
    placeholders = ",".join(["%s"] * len(statuses))
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.listwise_rank IS NOT NULL AND ujs.status IN ({placeholders})
            ORDER BY ujs.listwise_rank ASC, ujs.updated_at DESC""",
        [user_id, *statuses],
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def count_ranked(conn, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_job_states WHERE user_id = %s AND listwise_rank IS NOT NULL",
        (user_id,),
    )
    return cur.fetchone()[0]


def reset_auto_rejected(conn, user_id: int) -> int:
    """Reset this user's auto-rejected-with-a-description jobs back to 'new',
    clearing their score — used before re-running the keyword filter + evaluator
    with updated criteria."""
    cur = conn.cursor()
    cur.execute(
        """UPDATE user_job_states ujs SET status = 'new', score = NULL, score_reason = NULL
           FROM job_postings jp
           WHERE ujs.job_id = jp.id AND ujs.user_id = %s AND ujs.status = 'auto_rejected'
             AND jp.description IS NOT NULL AND jp.description != ''""",
        (user_id,),
    )
    return cur.rowcount


def get_would_apply_stats(conn, user_id: int) -> dict:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT
            COUNT(*)                                             AS flagged_total,
            SUM(CASE WHEN status = 'applied'  THEN 1 ELSE 0 END) AS applied,
            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected
        FROM user_job_states
        WHERE user_id = %s AND would_apply = 1
    """, (user_id,))
    row = cur.fetchone()
    decided = (row["applied"] or 0) + (row["rejected"] or 0)
    precision = round(row["applied"] / decided, 3) if decided else None
    return {
        "flagged_total": row["flagged_total"] or 0,
        "applied": row["applied"] or 0,
        "rejected": row["rejected"] or 0,
        "decided": decided,
        "precision": precision,
    }
