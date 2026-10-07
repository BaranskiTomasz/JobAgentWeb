import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg2.extras import execute_values

from db import dict_cursor
from source_identity import company_alias, identity_aliases, title_alias

# Explicit aliases: both tables have an `id` column, and `jp.*, ujs.*` would let
# one clobber the other. The JSONB columns are cast back to text on the way out
# so the HTTP response stays a string, matching every existing json.loads() caller.
_JOB_COLUMNS = """
    jp.id, jp.title, jp.company, jp.location, jp.url, jp.description, jp.source,
    jp.source_id, jp.search_query, jp.structured_data::text, jp.posted_at, jp.source_structured_data::text,
    jp.created_at AS posting_created_at, jp.updated_at AS posting_updated_at,
    ujs.status, ujs.score, ujs.score_reason, ujs.score_breakdown::text, ujs.score_fingerprint, ujs.rejection_reason,
    ujs.embedding_score, ujs.rerank_score, ujs.listwise_rank, ujs.rank_reason,
    ujs.debate_flag, ujs.debate_note, ujs.ranking_fingerprint, ujs.would_apply, ujs.would_apply_reason,
    ujs.created_at, ujs.updated_at,
    comp.total_count AS company_total_count, comp.applied_count AS company_applied_count
"""
# Per-company stats (this user's own postings only), correlated via ujs.user_id/jp.company
# rather than a bound parameter, so every _JOB_FROM call site gets it for free with no
# extra param plumbing. A plain aggregate subquery always returns exactly one row even
# with zero matches (COUNT(*) = 0), so this is a plain JOIN LATERAL, not a LEFT JOIN.
_JOB_FROM = """
    FROM job_postings jp
    JOIN user_job_states ujs ON ujs.job_id = jp.id
    JOIN LATERAL (
        SELECT COUNT(*) AS total_count, COUNT(*) FILTER (WHERE ujs2.status = 'applied') AS applied_count
        FROM job_postings jp2
        JOIN user_job_states ujs2 ON ujs2.job_id = jp2.id
        WHERE ujs2.user_id = ujs.user_id AND jp2.company = jp.company
    ) comp ON TRUE
"""


def _generate_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:16]


_TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "referrer",
    "trk", "trackingid",
}

_DEDUP_WINDOW_DAYS = 21


def canonicalize_url(url: str) -> str:
    value = url.strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    original_scheme = parsed.scheme.lower()
    scheme = "https" if original_scheme in {"http", "https"} else original_scheme
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parsed.port
    netloc = hostname
    if port and not (original_scheme == "http" and port == 80) and not (original_scheme == "https" and port == 443):
        netloc = f"{hostname}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(sorted(
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ))
    return urlunsplit((scheme, netloc, path, query, ""))


def _normalize_fingerprint_text(value: str | None) -> str:
    text = (value or "").translate(str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O"}))
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return " ".join(re.findall(r"[a-z0-9+#.]+", text))


def _normalize_identity_text(value: str | None) -> str:
    return " ".join(re.findall(r"[a-z0-9+#]+", _normalize_fingerprint_text(value)))


def content_fingerprint(job: dict) -> str | None:
    title = _normalize_fingerprint_text(job.get("title"))
    company = _normalize_fingerprint_text(job.get("company"))
    location = _normalize_fingerprint_text(job.get("location"))
    description = _normalize_fingerprint_text(job.get("description"))
    if not title or not company or len(description) < 100:
        return None
    payload = "\n".join((title, company, location, description))
    return hashlib.sha256(payload.encode()).hexdigest()


def identity_fingerprint(job: dict) -> str | None:
    title = title_alias(job.get("title"))
    company = company_alias(job.get("company"))
    if not title or not company:
        return None
    return hashlib.sha256(f"{company}\n{title}".encode()).hexdigest()


def _description_similarity(left: str | None, right: str | None) -> float:
    left_tokens = set(_normalize_fingerprint_text(left).split())
    right_tokens = set(_normalize_fingerprint_text(right).split())
    if len(left_tokens) < 20 or len(right_tokens) < 20:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _locations_compatible(left: str | None, right: str | None) -> bool:
    left_value = _normalize_identity_text(left)
    right_value = _normalize_identity_text(right)
    if not left_value or not right_value:
        return False
    if left_value == right_value:
        return True
    generic = {"remote", "worldwide", "global", "anywhere"}
    left_scope = set(left_value.split()) - generic
    right_scope = set(right_value.split()) - generic
    if not left_scope or not right_scope:
        return not left_scope and not right_scope
    return bool(left_scope & right_scope)


def refresh_fingerprints(conn, job_id: str) -> bool:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, title, company, location, description
           FROM job_postings WHERE id = %s""",
        (job_id,),
    )
    row = cur.fetchone()
    if not row:
        return False
    job = dict(row)
    cur.execute(
        """UPDATE job_postings
           SET identity_fingerprint = %s,
               content_fingerprint = %s,
               updated_at = CURRENT_TIMESTAMP
           WHERE id = %s""",
        (identity_fingerprint(job), content_fingerprint(job), job_id),
    )
    return True


def _run_late_dedup(conn, job_id: str) -> dict:
    if not refresh_fingerprints(conn, job_id):
        return {"survivor_job_id": job_id, "merges": [], "candidates": []}
    from dedup_repo import deduplicate_job
    return deduplicate_job(conn, job_id, window_days=_DEDUP_WINDOW_DAYS)


def _row_to_job(row: dict) -> dict:
    row = dict(row)
    if row.get("would_apply") is not None:
        row["would_apply"] = bool(row["would_apply"])
    return row


def insert(conn, user_id: int | None, job: dict, *, attach_to_user: bool = True) -> dict:
    # job_id is None only if this user already has a state for this posting.
    # posting_created=False tells the caller the posting was already known
    # (from another user), so it can skip re-fetching/re-extracting.
    #
    # ON CONFLICT DO NOTHING instead of check-then-insert makes two collectors
    # racing on the same URL safe: job_id is deterministic from the URL, so
    # it's correct whichever of the two INSERTs actually wins.
    cur = dict_cursor(conn)
    canonical_url = canonicalize_url(job["url"])
    identity = identity_fingerprint(job)
    fingerprint = content_fingerprint(job)
    job_id = _generate_id(canonical_url)

    cur.execute(
        # No conflict target: id and url are both unique and both deterministic
        # from the same url, so targeting just one leaves the other race open.
        """INSERT INTO job_postings (id, title, company, location, url, canonical_url, identity_fingerprint, content_fingerprint, description, source, source_id, search_query, posted_at, source_structured_data)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT DO NOTHING
           RETURNING id""",
        (job_id, job["title"], job.get("company"), job.get("location"), job["url"], canonical_url, identity, fingerprint,
         job.get("description"), job.get("source", "linkedin"), job.get("source_id"),
         job.get("search_query"), job.get("posted_at"),
         json.dumps(job["source_structured_data"], ensure_ascii=False) if job.get("source_structured_data") else None),
    )
    posting_created = cur.fetchone() is not None

    if not posting_created:
        cur.execute(
            """SELECT id FROM job_postings
               WHERE url = %s OR canonical_url = %s
               ORDER BY CASE WHEN url = %s THEN 0 ELSE 1 END
               LIMIT 1""",
            (job["url"], canonical_url, job["url"]),
        )
        existing = cur.fetchone()
        if existing:
            job_id = existing["id"]

    alias_metadata = {
        "search_query": job.get("search_query"),
        "source_structured_data": job.get("source_structured_data"),
        **identity_aliases(job),
    }
    cur.execute(
        """INSERT INTO job_posting_aliases (job_id, url, canonical_url, source, source_id, metadata)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (job_id, url, source) DO UPDATE SET
               source = COALESCE(job_posting_aliases.source, EXCLUDED.source),
               source_id = COALESCE(job_posting_aliases.source_id, EXCLUDED.source_id),
               metadata = COALESCE(job_posting_aliases.metadata, '{}'::jsonb)
                          || jsonb_strip_nulls(COALESCE(EXCLUDED.metadata, '{}'::jsonb))""",
        (job_id, job["url"], canonical_url, job.get("source"), job.get("source_id"),
         json.dumps(alias_metadata, ensure_ascii=False)),
    )

    if attach_to_user:
        cur.execute(
            "INSERT INTO user_job_states (user_id, job_id) VALUES (%s, %s) ON CONFLICT (user_id, job_id) DO NOTHING RETURNING id",
            (user_id, job_id),
        )
        state_created = cur.fetchone() is not None
        if not state_created:
            return {"job_id": None, "posting_created": False}
    elif not posting_created:
        return {"job_id": None, "posting_created": False}

    if posting_created and job.get("description"):
        dedup = _run_late_dedup(conn, job_id)
        if dedup["survivor_job_id"] != job_id:
            if attach_to_user and any(user_id in merge["overlapping_user_ids"] for merge in dedup["merges"]):
                return {"job_id": None, "posting_created": False}
            job_id = dedup["survivor_job_id"]
            posting_created = False

    from catalog import refresh_job
    refresh_job(conn, job_id)

    return {"job_id": job_id, "posting_created": posting_created}


def get_aliases(conn, user_id: int, job_id: str) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT a.url, a.canonical_url, a.source, a.source_id, a.metadata::text, a.created_at
           FROM job_posting_aliases a
           JOIN user_job_states ujs ON ujs.job_id = a.job_id
           WHERE ujs.user_id = %s AND a.job_id = %s
           ORDER BY a.created_at, a.id""",
        (user_id, job_id),
    )
    return [dict(row) for row in cur.fetchall()]


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
    limit: int | None = None,
    offset: int | None = None,
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
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    if offset is not None:
        sql += " OFFSET %s"
        params.append(offset)
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


def update_score(conn, user_id: int, job_id: str, score: float | None, reason: str, breakdown: dict | None = None, fingerprint: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET score = %s, score_reason = %s, score_breakdown = %s, score_fingerprint = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (score, reason, json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None, fingerprint, user_id, job_id),
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
    fingerprint: str | None = None,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE user_job_states
           SET embedding_score = %s, rerank_score = %s, listwise_rank = %s, rank_reason = %s,
               debate_flag = %s, debate_note = %s, ranking_fingerprint = %s, updated_at = CURRENT_TIMESTAMP
           WHERE user_id = %s AND job_id = %s""",
        (embedding_score, rerank_score, listwise_rank, rank_reason, debate_flag, debate_note, fingerprint, user_id, job_id),
    )


def update_would_apply(conn, user_id: int, job_id: str, would_apply: bool, reason: str) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET would_apply = %s, would_apply_reason = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (1 if would_apply else 0, reason, user_id, job_id),
    )


def update_ranking_scores_batch(conn, user_id: int, items: list[dict]) -> int:
    # One round-trip for the whole batch instead of one UPDATE per job. Rows for
    # job_ids this user has no state for simply match nothing and are skipped,
    # rather than erroring the whole batch over one bad id.
    if not items:
        return 0
    cur = conn.cursor()
    rows = [
        (user_id, item["job_id"], item.get("embedding_score"), item.get("rerank_score"),
         item.get("listwise_rank"), item.get("rank_reason"), item.get("debate_flag"), item.get("debate_note"), item.get("fingerprint"))
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
               ranking_fingerprint = v.fingerprint::text,
               updated_at = CURRENT_TIMESTAMP
           FROM (VALUES %s) AS v(user_id, job_id, embedding_score, rerank_score, listwise_rank, rank_reason, debate_flag, debate_note, fingerprint)
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
    # Shared across every user who sees this posting, and write-once (only
    # fills a NULL) so one user can't overwrite another's already-extracted data.
    cur = conn.cursor()
    cur.execute(
        "UPDATE job_postings SET structured_data = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = %s AND structured_data IS NULL",
        (json.dumps(data, ensure_ascii=False), job_id),
    )
    from catalog import refresh_job
    refresh_job(conn, job_id)


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
    # Scoped to this user, not system-wide: collectors skip a card outright
    # when its URL is already "known", so a global set here would make a
    # second user's collector silently skip postings only the first user found.
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT jp.url FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id WHERE ujs.user_id = %s",
        (user_id,),
    )
    return {r["url"] for r in cur.fetchall()}


def get_all_shared_urls(conn) -> set[str]:
    cur = conn.cursor()
    cur.execute(
        """SELECT url FROM job_postings WHERE url IS NOT NULL
           UNION
           SELECT url FROM job_posting_aliases WHERE url IS NOT NULL"""
    )
    return {row[0] for row in cur.fetchall()}


def get_missing_descriptions(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.id, jp.url, jp.source FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND (jp.description IS NULL OR jp.description = '') AND ujs.score IS NULL
           ORDER BY jp.created_at DESC""",
        (user_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def get_missing_structured_data(conn, user_id: int) -> list[dict]:
    # status = 'new' on purpose: a decided job never re-enters scoring or
    # ranking, so extracting structured_data for one is sunk cost with no reader.
    cur = dict_cursor(conn)
    sql = f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
              WHERE ujs.user_id = %s AND jp.description IS NOT NULL AND jp.description != ''
              AND jp.structured_data IS NULL AND ujs.status = 'new'
              ORDER BY jp.created_at DESC"""
    cur.execute(sql, (user_id,))
    return [_row_to_job(r) for r in cur.fetchall()]


def get_missing_facts(
    conn, user_id: int, schema_version: int, limit: int, max_age_days: int = 14,
) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            LEFT JOIN job_fact_extractions jfe ON jfe.job_id = jp.id
            WHERE ujs.user_id = %s
              AND jp.description IS NOT NULL AND jp.description != ''
              AND (jfe.job_id IS NULL OR jfe.schema_version < %s)
              AND COALESCE(jp.posted_at, jp.created_at) >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
            ORDER BY jp.created_at DESC
            LIMIT %s""",
        (user_id, schema_version, max_age_days, limit),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_shared_missing_facts(
    conn, schema_version: int, limit: int, max_age_days: int = 14,
) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.*
             FROM job_postings jp
             LEFT JOIN job_fact_extractions jfe ON jfe.job_id = jp.id
            WHERE jp.description IS NOT NULL AND jp.description != ''
              AND (jfe.job_id IS NULL OR jfe.schema_version < %s)
              AND COALESCE(jp.posted_at, jp.created_at) >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
            ORDER BY jp.created_at DESC
            LIMIT %s""",
        (schema_version, max_age_days, limit),
    )
    result = []
    for row in cur.fetchall():
        job = dict(row)
        job.setdefault("status", "new")
        job.setdefault("score", None)
        job.setdefault("score_reason", None)
        job.setdefault("score_breakdown", None)
        job.setdefault("score_fingerprint", None)
        job.setdefault("rejection_reason", None)
        job.setdefault("embedding_score", None)
        job.setdefault("rerank_score", None)
        job.setdefault("listwise_rank", None)
        job.setdefault("rank_reason", None)
        job.setdefault("debate_flag", None)
        job.setdefault("debate_note", None)
        job.setdefault("ranking_fingerprint", None)
        job.setdefault("would_apply", None)
        job.setdefault("would_apply_reason", None)
        job.setdefault("company_total_count", 1)
        job.setdefault("company_applied_count", 0)
        result.append(_row_to_job(job))
    return result


def update_facts(
    conn, job_id: str, schema_version: int, model: str, content_hash: str,
    facts: dict, provenance: dict,
) -> str:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO job_fact_extractions
               (job_id, schema_version, model, content_hash, facts, provenance,
                role_family, seniority_min, seniority_max, remote, timezone_requirement,
                working_language, company_type, product_vs_outsourcing, extracted_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (job_id) DO UPDATE SET
               schema_version = EXCLUDED.schema_version,
               model = EXCLUDED.model,
               content_hash = EXCLUDED.content_hash,
               facts = EXCLUDED.facts,
               provenance = EXCLUDED.provenance,
               role_family = EXCLUDED.role_family,
               seniority_min = EXCLUDED.seniority_min,
               seniority_max = EXCLUDED.seniority_max,
               remote = EXCLUDED.remote,
               timezone_requirement = EXCLUDED.timezone_requirement,
               working_language = EXCLUDED.working_language,
               company_type = EXCLUDED.company_type,
               product_vs_outsourcing = EXCLUDED.product_vs_outsourcing,
               extracted_at = CURRENT_TIMESTAMP""",
        (job_id, schema_version, model, content_hash,
         json.dumps(facts, ensure_ascii=False), json.dumps(provenance, ensure_ascii=False),
         facts.get("role_family"), facts.get("seniority_min"), facts.get("seniority_max"),
         facts.get("remote"), facts.get("timezone_requirement"), facts.get("working_language"),
         facts.get("company_type"), facts.get("product_vs_outsourcing")),
    )
    cur.execute(
        "UPDATE job_postings SET structured_data = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        (json.dumps(facts, ensure_ascii=False), job_id),
    )
    cur.execute("DELETE FROM job_skills WHERE job_id = %s", (job_id,))
    skills = {}
    for skill in facts.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        name = str(skill.get("canonical_name") or "").strip().lower()
        if not name:
            continue
        skills[(name, skill.get("requirement") or "mentioned")] = (
            job_id, name, str(skill.get("original_name") or name),
            skill.get("requirement") or "mentioned", skill.get("importance") or "supporting",
            skill.get("min_years"), float(skill.get("confidence") or 0.5), skill.get("evidence"),
        )
    if skills:
        execute_values(
            cur,
            """INSERT INTO job_skills
                   (job_id, canonical_name, original_name, requirement, importance, min_years, confidence, evidence)
               VALUES %s
               ON CONFLICT (job_id, canonical_name, requirement) DO UPDATE SET
                   original_name = EXCLUDED.original_name,
                   importance = EXCLUDED.importance,
                   min_years = EXCLUDED.min_years,
                   confidence = EXCLUDED.confidence,
                   evidence = EXCLUDED.evidence""",
            list(skills.values()),
        )
    cur.execute("DELETE FROM job_compensation_bands WHERE job_id = %s", (job_id,))
    bands = [(
        job_id, band.get("amount_min"), band.get("amount_max"), band.get("currency"),
        band.get("period"), band.get("tax_basis"), band.get("compensation_type"),
        band.get("contract_type"), band.get("country_code"),
        float(band.get("confidence") or 0.5), band.get("evidence"),
    ) for band in facts.get("compensation_bands") or [] if isinstance(band, dict)]
    if bands:
        execute_values(
            cur,
            """INSERT INTO job_compensation_bands
                   (job_id, amount_min, amount_max, currency, period, tax_basis, compensation_type,
                    contract_type, country_code, confidence, evidence) VALUES %s""",
            bands,
        )
    cur.execute("DELETE FROM job_eligibility WHERE job_id = %s", (job_id,))
    eligibility = {}
    for item in facts.get("country_eligibility") or []:
        if not isinstance(item, dict) or not item.get("country_code"):
            continue
        country_code = str(item["country_code"]).upper()
        eligibility[country_code] = (
            job_id, country_code, item.get("eligible"), float(item.get("confidence") or 0.5),
            item.get("engagement_modes") or [], item.get("evidence"),
        )
    if eligibility:
        execute_values(
            cur,
            """INSERT INTO job_eligibility
                   (job_id, country_code, eligible, confidence, engagement_modes, evidence) VALUES %s
               ON CONFLICT (job_id, country_code) DO UPDATE SET
                   eligible = EXCLUDED.eligible,
                   confidence = EXCLUDED.confidence,
                   engagement_modes = EXCLUDED.engagement_modes,
                   evidence = EXCLUDED.evidence""",
            list(eligibility.values()),
        )
    dedup = _run_late_dedup(conn, job_id)
    survivor_id = dedup["survivor_job_id"]
    from catalog import refresh_job
    refresh_job(conn, survivor_id)
    return survivor_id


def update_description(conn, job_id: str, description: str) -> str:
    # Shared, not user-scoped, write-once - same reasoning as update_structured_data.
    cur = conn.cursor()
    cur.execute(
        "UPDATE job_postings SET description = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = %s AND (description IS NULL OR description = '')",
        (description, job_id),
    )
    if cur.rowcount == 0:
        return job_id
    dedup = _run_late_dedup(conn, job_id)
    survivor_id = dedup["survivor_job_id"]
    from catalog import refresh_job
    refresh_job(conn, survivor_id)
    return survivor_id


def update_score_and_status(conn, user_id: int, job_id: str, score: float | None, reason: str, status: str, breakdown: dict | None = None, fingerprint: str | None = None) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE user_job_states SET score = %s, score_reason = %s, score_breakdown = %s, score_fingerprint = %s, status = %s, updated_at = CURRENT_TIMESTAMP"
        " WHERE user_id = %s AND job_id = %s",
        (score, reason, json.dumps(breakdown, ensure_ascii=False) if breakdown is not None else None, fingerprint, status, user_id, job_id),
    )


def get_new(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        f"SELECT {_JOB_COLUMNS} {_JOB_FROM} WHERE ujs.user_id = %s AND ujs.status = 'new' ORDER BY ujs.created_at DESC",
        (user_id,),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_unscored(conn, user_id: int) -> list[dict]:
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
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.status = 'new'
              AND jp.description IS NOT NULL AND jp.description != ''
            ORDER BY ujs.created_at DESC""",
        (user_id,),
    )
    return [_row_to_job(r) for r in cur.fetchall()]


def get_dealbreaker_rejected_with_descriptions(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.status = 'auto_rejected'
              AND ujs.score_reason LIKE 'Dealbreaker:%%'
              AND jp.description IS NOT NULL AND jp.description != ''
            ORDER BY ujs.updated_at DESC""",
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


def get_all_feedback(
    conn, user_id: int, limit_applied: int | None = None, limit_rejected: int | None = None,
) -> tuple[list[dict], list[dict]]:
    # Descriptions truncated to 1500 chars server-side since the preference
    # distiller never reads further. decided_at lets it tell a recent reversal
    # apart from an old, settled decision.
    cur = dict_cursor(conn)
    sql = """SELECT jp.title, jp.company, jp.location, LEFT(jp.description, 1500) AS description,
                     ujs.score_reason, ujs.updated_at AS decided_at
             FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
             WHERE ujs.user_id = %s AND ujs.status = 'applied' ORDER BY ujs.updated_at DESC"""
    params = [user_id]
    if limit_applied is not None:
        sql += " LIMIT %s"
        params.append(limit_applied)
    cur.execute(sql, params)
    applied = [dict(r) for r in cur.fetchall()]

    sql = """SELECT jp.title, jp.company, jp.location, LEFT(jp.description, 1500) AS description,
                     ujs.rejection_reason, ujs.score_reason, ujs.updated_at AS decided_at
              FROM job_postings jp JOIN user_job_states ujs ON ujs.job_id = jp.id
              WHERE ujs.user_id = %s AND ujs.status = 'rejected' ORDER BY ujs.updated_at DESC"""
    params = [user_id]
    if limit_rejected is not None:
        sql += " LIMIT %s"
        params.append(limit_rejected)
    cur.execute(sql, params)
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
    # Removes only this user's view; job_postings (shared with every other
    # user who's found the same URL) is never touched.
    if not statuses:
        return 0
    where, params = _filter_sql(statuses, date_from, date_to)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM user_job_states ujs WHERE ujs.user_id = %s {where}", [user_id, *params])
    return cur.rowcount


def get_jobs_for_ranking(conn, user_id: int, limit: int = 2000) -> list[dict]:
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
    # Used to trigger auto-distillation once enough decisions accumulate.
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_job_states WHERE user_id = %s AND status IN ('applied', 'rejected')",
        (user_id,),
    )
    return cur.fetchone()[0]


_PRUNING_LOOKBACK_DAYS = 30


def get_query_outcome_stats(conn, user_id: int, source: str) -> list[dict]:
    # Windowed to the trailing days, not all-time, so a query that was
    # reject-heavy a year ago doesn't stay excluded forever.
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


def get_ranked(conn, user_id: int, statuses: list[str], limit: int | None = None) -> list[dict]:
    # listwise_rank freezes at decision time and only ever spans 1-20, so many
    # rows end up sharing a rank; the updated_at tiebreak surfaces recent ones first.
    cur = dict_cursor(conn)
    placeholders = ",".join(["%s"] * len(statuses))
    sql = f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
              WHERE ujs.user_id = %s AND ujs.listwise_rank IS NOT NULL AND ujs.status IN ({placeholders})
              ORDER BY ujs.listwise_rank ASC, ujs.updated_at DESC"""
    params: list = [user_id, *statuses]
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    cur.execute(sql, params)
    return [_row_to_job(r) for r in cur.fetchall()]


def get_divergence_cases(conn, user_id: int, limit: int = 50) -> list[dict]:
    # rank <=5 but rejected means the model overrated it; rank >=16 but applied
    # means it underrated it - the strongest learning signal for the distiller.
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT {_JOB_COLUMNS} {_JOB_FROM}
            WHERE ujs.user_id = %s AND ujs.listwise_rank IS NOT NULL
            AND (
                (ujs.listwise_rank <= 5 AND ujs.status = 'rejected')
                OR (ujs.listwise_rank >= 16 AND ujs.status = 'applied')
            )
            ORDER BY ujs.updated_at DESC
            LIMIT %s""",
        (user_id, limit),
    )
    cases = []
    for r in cur.fetchall():
        row = _row_to_job(r)
        row["divergence_type"] = "false_positive" if row["listwise_rank"] <= 5 else "false_negative"
        cases.append(row)
    return cases


def count_ranked(conn, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM user_job_states WHERE user_id = %s AND listwise_rank IS NOT NULL",
        (user_id,),
    )
    return cur.fetchone()[0]


def reset_auto_rejected(conn, user_id: int) -> int:
    # Used before re-running the keyword filter + evaluator with updated criteria.
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
