from db import dict_cursor


TECHNOLOGIES = ("php", "python", "nodejs", "react", "angular", "qa", "java", "dotnet", "go")
ROLE_FAMILIES = ("software-engineering", "backend", "frontend", "fullstack", "mobile", "devops", "data", "ml-ai")
CATEGORIES = TECHNOLOGIES + ROLE_FAMILIES
CATEGORY_LABELS = {
    "php": "PHP", "python": "Python", "nodejs": "Node.js", "react": "React",
    "angular": "Angular", "qa": "QA", "java": "Java", "dotnet": ".NET", "go": "Go",
    "software-engineering": "Software Engineering", "backend": "Backend",
    "frontend": "Frontend", "fullstack": "Full Stack", "mobile": "Mobile",
    "devops": "DevOps / Platform", "data": "Data Engineering", "ml-ai": "ML / AI",
}
COUNTRIES = ("PL", "BG")
PUBLIC_CATALOG_MAX_AGE_DAYS = 14

_PUBLIC_JOB_SELECT = """SELECT jp.id, jp.title, jp.company, jp.location,
              COALESCE(
                  (ARRAY_AGG(jpa.url ORDER BY CASE WHEN jpa.source = 'linkedin' THEN 1 ELSE 0 END, jpa.created_at)
                   FILTER (WHERE jpa.url IS NOT NULL))[1],
                  jp.url
              ) AS url,
              jp.source, jp.posted_at, jp.created_at, jcm.technologies, jcm.role_families, jcm.work_countries,
              jcm.eligibility_confidence,
              LEFT(REGEXP_REPLACE(jp.description, '\\s+', ' ', 'g'), 320) AS excerpt,
              jp.description, jfe.facts AS structured_data, jfe.extracted_at,
              je.evidence AS eligibility_evidence,
              COALESCE(je.engagement_modes, '{}') AS engagement_modes,
              ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(jpa.source, jp.source)), NULL) AS sources
       FROM job_catalog_metadata jcm
       JOIN job_postings jp ON jp.id = jcm.job_id
       LEFT JOIN job_fact_extractions jfe ON jfe.job_id = jp.id
       LEFT JOIN job_eligibility je ON je.job_id = jp.id AND je.country_code = %s
       LEFT JOIN job_posting_aliases jpa ON jpa.job_id = jp.id"""

_PUBLIC_JOB_GROUP = """GROUP BY jp.id, jcm.job_id, jfe.facts, jfe.extracted_at,
          je.evidence, je.engagement_modes"""


def _freshness_clause() -> str:
    # Keep the same freshness window in list, facet/count, and personalize
    # queries.  A single helper makes accidental drift (such as the former
    # 45-day window in one query) harder to reintroduce.
    return f"CURRENT_TIMESTAMP - INTERVAL '{PUBLIC_CATALOG_MAX_AGE_DAYS} days'"


def list_jobs(conn, technology: str, country: str, limit: int = 30, offset: int = 0) -> list[dict]:
    cur = dict_cursor(conn)
    freshness = _freshness_clause()
    cur.execute(
        f"""{_PUBLIC_JOB_SELECT}
           WHERE jcm.is_public = TRUE
             AND (%s = ANY(jcm.technologies) OR %s = ANY(jcm.role_families))
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}
           {_PUBLIC_JOB_GROUP}
           ORDER BY COALESCE(jp.posted_at, jp.created_at) DESC, jp.id
           LIMIT %s OFFSET %s""",
        (country, technology, technology, country, limit, offset),
    )
    return [dict(row) for row in cur.fetchall()]


def search_jobs(
    conn, technology: str, country: str, limit: int, offset: int,
    *,
    query: str | None = None, source: str | None = None, company: str | None = None,
    seniority: str | None = None, skill: str | None = None, role_family: str | None = None,
    contract_type: str | None = None, currency: str | None = None,
    salary_min: float | None = None, salary_period: str | None = None,
    working_language: str | None = None,
    timezone: str | None = None, company_type: str | None = None,
    company_stage: str | None = None, team_size: str | None = None,
    industry: str | None = None, on_call: bool | None = None,
    travel: str | None = None, office_visits: str | None = None, sort: str = "date",
) -> dict:
    freshness = _freshness_clause()
    conditions = [
        "jcm.is_public = TRUE",
        "(%s = ANY(jcm.technologies) OR %s = ANY(jcm.role_families))",
        "%s = ANY(jcm.work_countries)",
        f"COALESCE(jp.posted_at, jp.created_at) >= {freshness}",
    ]
    params: list = [technology, technology, country]

    if query:
        conditions.append("(jp.title ILIKE %s OR jp.company ILIKE %s OR jp.description ILIKE %s OR jfe.facts->>'summary' ILIKE %s)")
        needle = f"%{query}%"
        params.extend([needle] * 4)
    if company:
        conditions.append("jp.company = %s")
        params.append(company)
    if seniority:
        conditions.append("%s IN (jfe.facts->>'seniority', jfe.facts->>'seniority_min', jfe.facts->>'seniority_max')")
        params.append(seniority)
    if role_family:
        conditions.append("jfe.facts->>'role_family' = %s")
        params.append(role_family)
    if working_language:
        conditions.append("(jfe.facts->>'working_language' = %s OR jfe.facts->>'working_language' = 'both' OR EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(jfe.facts->'languages', '[]'::jsonb)) lang WHERE LOWER(lang->>'language') = LOWER(%s)))")
        params.extend([working_language, working_language])
    if timezone:
        conditions.append("(jfe.facts->>'timezone_requirement' ILIKE %s OR jfe.facts->>'core_hours' ILIKE %s)")
        params.extend([f"%{timezone}%", f"%{timezone}%"])
    if company_type:
        conditions.append("jfe.facts->>'company_type' = %s")
        params.append(company_type)
    if company_stage:
        conditions.append("jfe.facts->>'company_stage' ILIKE %s")
        params.append(f"%{company_stage}%")
    if team_size:
        conditions.append("jfe.facts->>'team_size' ILIKE %s")
        params.append(f"%{team_size}%")
    if industry:
        conditions.append("jfe.facts->>'industry' = %s")
        params.append(industry)
    if on_call is not None:
        conditions.append("jfe.facts->>'on_call' = %s")
        params.append("true" if on_call else "false")
    if travel:
        conditions.append("jfe.facts->>'travel_requirement' ILIKE %s")
        params.append(f"%{travel}%")
    if office_visits:
        conditions.append("jfe.facts->>'office_visit_requirement' ILIKE %s")
        params.append(f"%{office_visits}%")
    if source:
        conditions.append("(jp.source = %s OR EXISTS (SELECT 1 FROM job_posting_aliases source_alias WHERE source_alias.job_id = jp.id AND source_alias.source = %s))")
        params.extend([source, source])
    if skill:
        conditions.append("EXISTS (SELECT 1 FROM job_skills js WHERE js.job_id = jp.id AND LOWER(js.canonical_name) = LOWER(%s))")
        params.append(skill)
    if contract_type:
        conditions.append("(%s = ANY(COALESCE(je.engagement_modes, '{}')) OR COALESCE(jfe.facts->'contract_types', '[]'::jsonb) ? %s)")
        params.extend([contract_type, contract_type])
    compensation_conditions = []
    compensation_params = []
    if currency:
        compensation_conditions.append("UPPER(jcb.currency) = %s")
        compensation_params.append(currency.upper())
    if salary_min is not None:
        compensation_conditions.append("COALESCE(jcb.amount_max, jcb.amount_min) >= %s")
        compensation_params.append(salary_min)
    if salary_period:
        compensation_conditions.append("jcb.period = %s")
        compensation_params.append(salary_period)
    if compensation_conditions:
        conditions.append(
            "EXISTS (SELECT 1 FROM job_compensation_bands jcb WHERE jcb.job_id = jp.id AND "
            + " AND ".join(compensation_conditions) + ")"
        )
        params.extend(compensation_params)

    where = " AND ".join(f"({condition})" for condition in conditions)
    order_by = {
        "date": "COALESCE(jp.posted_at, jp.created_at) DESC, jp.id",
        "company": "LOWER(COALESCE(jp.company, '')), COALESCE(jp.posted_at, jp.created_at) DESC",
        "title": "LOWER(jp.title), COALESCE(jp.posted_at, jp.created_at) DESC",
        "salary": "(SELECT MAX(COALESCE(jcb.amount_max, jcb.amount_min)) FROM job_compensation_bands jcb WHERE jcb.job_id = jp.id) DESC NULLS LAST, COALESCE(jp.posted_at, jp.created_at) DESC",
    }[sort]
    cur = dict_cursor(conn)
    cur.execute(
        f"""{_PUBLIC_JOB_SELECT}
            WHERE {where}
            {_PUBLIC_JOB_GROUP}
            ORDER BY {order_by}
            LIMIT %s OFFSET %s""",
        [country, *params, limit, offset],
    )
    items = [dict(row) for row in cur.fetchall()]
    count_cur = conn.cursor()
    count_cur.execute(
        f"""SELECT COUNT(*)
            FROM job_catalog_metadata jcm
            JOIN job_postings jp ON jp.id = jcm.job_id
            LEFT JOIN job_fact_extractions jfe ON jfe.job_id = jp.id
            LEFT JOIN job_eligibility je ON je.job_id = jp.id AND je.country_code = %s
            WHERE {where}""",
        [country, *params],
    )
    return {"items": items, "total": count_cur.fetchone()[0], "limit": limit, "offset": offset}


def filter_options(conn, technology: str, country: str) -> dict:
    freshness = _freshness_clause()
    cur = dict_cursor(conn)
    cur.execute(
        f"""SELECT
            ARRAY(SELECT DISTINCT COALESCE(a.source, p.source) FROM job_catalog_metadata m JOIN job_postings p ON p.id = m.job_id LEFT JOIN job_posting_aliases a ON a.job_id = p.id WHERE m.is_public AND (%s = ANY(m.technologies) OR %s = ANY(m.role_families)) AND %s = ANY(m.work_countries) AND COALESCE(p.posted_at, p.created_at) >= {freshness} AND COALESCE(a.source, p.source) IS NOT NULL ORDER BY 1) AS sources,
            ARRAY(SELECT DISTINCT p.company FROM job_catalog_metadata m JOIN job_postings p ON p.id = m.job_id WHERE m.is_public AND (%s = ANY(m.technologies) OR %s = ANY(m.role_families)) AND %s = ANY(m.work_countries) AND COALESCE(p.posted_at, p.created_at) >= {freshness} AND p.company IS NOT NULL ORDER BY 1) AS companies,
            ARRAY(SELECT DISTINCT s.canonical_name FROM job_catalog_metadata m JOIN job_postings p ON p.id = m.job_id JOIN job_skills s ON s.job_id = p.id WHERE m.is_public AND (%s = ANY(m.technologies) OR %s = ANY(m.role_families)) AND %s = ANY(m.work_countries) AND COALESCE(p.posted_at, p.created_at) >= {freshness} ORDER BY 1) AS skills,
            ARRAY(SELECT DISTINCT f.facts->>'industry' FROM job_catalog_metadata m JOIN job_postings p ON p.id = m.job_id JOIN job_fact_extractions f ON f.job_id = p.id WHERE m.is_public AND (%s = ANY(m.technologies) OR %s = ANY(m.role_families)) AND %s = ANY(m.work_countries) AND COALESCE(p.posted_at, p.created_at) >= {freshness} AND NULLIF(f.facts->>'industry', '') IS NOT NULL ORDER BY 1) AS industries""",
        [value for _ in range(4) for value in (technology, technology, country)],
    )
    row = dict(cur.fetchone())
    return {key: value or [] for key, value in row.items()}


def count_jobs(conn, technology: str, country: str) -> int:
    cur = conn.cursor()
    freshness = _freshness_clause()
    cur.execute(
        f"""SELECT COUNT(*)
           FROM job_catalog_metadata jcm
           JOIN job_postings jp ON jp.id = jcm.job_id
           WHERE jcm.is_public = TRUE
             AND (%s = ANY(jcm.technologies) OR %s = ANY(jcm.role_families))
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}""",
        (technology, technology, country),
    )
    return cur.fetchone()[0]


def facets(conn, country: str) -> dict[str, int]:
    cur = conn.cursor()
    counts = {}
    for technology in CATEGORIES:
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
             AND (%s = ANY(jcm.technologies) OR %s = ANY(jcm.role_families))
             AND %s = ANY(jcm.work_countries)
             AND COALESCE(jp.posted_at, jp.created_at) >= {freshness}
           ON CONFLICT (user_id, job_id) DO NOTHING""",
        (user_id, technology, technology, country),
    )
    return cur.rowcount
