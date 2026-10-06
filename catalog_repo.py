from db import dict_cursor


TECHNOLOGIES = ("php", "python", "nodejs", "react", "angular", "qa")
COUNTRIES = ("PL", "BG")


def list_jobs(conn, technology: str, country: str, limit: int = 30, offset: int = 0) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.id, jp.title, jp.company, jp.location,
                  COALESCE(
                      (ARRAY_AGG(jpa.url ORDER BY CASE WHEN jpa.source = 'linkedin' THEN 1 ELSE 0 END, jpa.created_at)
                       FILTER (WHERE jpa.url IS NOT NULL))[1],
                      jp.url
                  ) AS url,
                  jp.source,
                  jp.posted_at, jp.created_at, jcm.technologies, jcm.work_countries,
                  jcm.eligibility_confidence,
                  LEFT(REGEXP_REPLACE(jp.description, '\\s+', ' ', 'g'), 320) AS excerpt,
                  ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(jpa.source, jp.source)), NULL) AS sources
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           LEFT JOIN job_posting_aliases jpa ON jpa.job_id = jp.id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= CURRENT_TIMESTAMP - INTERVAL '45 days'
           GROUP BY jp.id, jcm.job_id
           ORDER BY COALESCE(jp.posted_at, jp.created_at) DESC, jp.id
           LIMIT %s OFFSET %s""",
        (technology, country, limit, offset),
    )
    return [dict(row) for row in cur.fetchall()]


def count_jobs(conn, technology: str, country: str) -> int:
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*)
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= CURRENT_TIMESTAMP - INTERVAL '45 days'""",
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
    cur.execute(
        """INSERT INTO user_job_states (user_id, job_id)
           SELECT %s, jp.id
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           WHERE jcm.is_public = TRUE
             AND %s = ANY(jcm.technologies)
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= CURRENT_TIMESTAMP - INTERVAL '45 days'
           ON CONFLICT (user_id, job_id) DO NOTHING""",
        (user_id, technology, country),
    )
    return cur.rowcount
