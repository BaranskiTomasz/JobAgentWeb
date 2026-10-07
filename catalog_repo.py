from db import dict_cursor


TECHNOLOGIES = ("php", "python", "nodejs", "react", "angular", "qa")
COUNTRIES = ("PL", "BG")
PUBLIC_CATALOG_MAX_AGE_DAYS = 14


def _freshness_clause() -> str:
    # Keep the same freshness window in list, facet/count, and personalize
    # queries.  A single helper makes accidental drift (such as the former
    # 45-day window in one query) harder to reintroduce.
    return f"CURRENT_TIMESTAMP - INTERVAL '{PUBLIC_CATALOG_MAX_AGE_DAYS} days'"


def list_jobs(conn, technology: str, country: str, limit: int = 30, offset: int = 0) -> list[dict]:
    cur = dict_cursor(conn)
    freshness = _freshness_clause()
    cur.execute(
        f"""SELECT jp.id, jp.title, jp.company, jp.location,
                  COALESCE(
                      (ARRAY_AGG(jpa.url ORDER BY CASE WHEN jpa.source = 'linkedin' THEN 1 ELSE 0 END, jpa.created_at)
                       FILTER (WHERE jpa.url IS NOT NULL))[1],
                      jp.url
                  ) AS url,
                  jp.source,
                  jp.posted_at, jp.created_at, jcm.technologies, jcm.work_countries,
                  jcm.eligibility_confidence,
                  LEFT(REGEXP_REPLACE(jp.description, '\\s+', ' ', 'g'), 320) AS excerpt,
                  jp.description,
                  jfe.facts AS structured_data,
                  ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(jpa.source, jp.source)), NULL) AS sources
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           LEFT JOIN job_fact_extractions jfe ON jfe.job_id = jp.id
           LEFT JOIN job_posting_aliases jpa ON jpa.job_id = jp.id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}
           GROUP BY jp.id, jcm.job_id, jfe.facts
           ORDER BY COALESCE(jp.posted_at, jp.created_at) DESC, jp.id
           LIMIT %s OFFSET %s""",
        (technology, country, limit, offset),
    )
    return [dict(row) for row in cur.fetchall()]


def count_jobs(conn, technology: str, country: str) -> int:
    cur = conn.cursor()
    freshness = _freshness_clause()
    cur.execute(
        f"""SELECT COUNT(*)
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}""",
        (technology, country),
    )
    return cur.fetchone()[0]


def facets(conn, country: str) -> dict[str, int]:
    cur = conn.cursor()
    counts = {}
    for technology in TECHNOLOGIES:
        counts[technology] = count_jobs(conn, technology, country)
    return counts


def attach_to_user(conn, user_id: int, technology: str, country: str) -> int:
    cur = conn.cursor()
    freshness = _freshness_clause()
    cur.execute(
        f"""INSERT INTO user_job_states (user_id, job_id)
           SELECT %s, jp.id
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}
           ON CONFLICT (user_id, job_id) DO NOTHING""",
        (user_id, technology, country),
    )
    return cur.rowcount
