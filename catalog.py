import json
import re

from db import dict_cursor


TECHNOLOGY_PATTERNS = {
    "php": (r"\bphp\b", r"\bsymfony\b", r"\blaravel\b"),
    "python": (r"\bpython\b", r"\bdjango\b", r"\bfastapi\b", r"\bflask\b"),
    "nodejs": (r"\bnode(?:\.js|js)?\b", r"\bnestjs\b", r"\bexpress(?:\.js|js)?\b"),
    "react": (r"\breact(?:\.js|js)?\b", r"\bnext(?:\.js|js)?\b"),
    "angular": (r"\bangular\b",),
    "qa": (
        r"\bqa\b",
        r"\bquality assurance\b",
        r"\bsdet\b",
        r"\btest automation\b",
        r"\bautomation tester\b",
        r"\bsoftware tester\b",
    ),
}

COUNTRY_NAMES = {"PL": ("poland", "polska"), "BG": ("bulgaria", "bułgaria", "bulgariya")}
REGIONAL_MARKERS = ("worldwide", "anywhere", "global", "europe", "european", "emea", "eea", "eu-only", "eu only")
REMOTE_MARKERS = ("remote", "zdaln", "work from home")
CLASSIFIER_VERSION = 1


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def classify_catalog_job(job: dict) -> dict:
    source_data = _json_dict(job.get("source_structured_data"))
    structured = _json_dict(job.get("structured_data"))
    alias_data = [_json_dict(value) for value in job.get("alias_metadata") or []]
    source_variants = [source_data]
    search_queries = [job.get("search_query")]
    for alias in alias_data:
        source_variants.append(_json_dict(alias.get("source_structured_data")))
        search_queries.append(alias.get("search_query"))
    stacks = []
    for key in ("stack", "stack_required", "stack_preferred"):
        value = structured.get(key) or source_data.get(key) or []
        stacks.extend(value if isinstance(value, list) else [value])
    text = " ".join(str(value or "") for value in (
        job.get("title"), job.get("description"), *search_queries, *stacks,
    )).lower()
    technologies = sorted(
        technology for technology, patterns in TECHNOLOGY_PATTERNS.items()
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
    )

    location = str(job.get("location") or "").lower()
    regions = []
    for variant in source_variants:
        value = variant.get("remote_regions") or []
        regions.extend(value if isinstance(value, list) else [value])
    structured_regions = structured.get("remote_regions") or []
    regions.extend(structured_regions if isinstance(structured_regions, list) else [structured_regions])
    eligibility_text = " ".join([location, *[str(region).lower() for region in regions]])
    remote = any(variant.get("remote") is True for variant in source_variants)
    remote = remote or structured.get("remote") is True or any(marker in location for marker in REMOTE_MARKERS)

    countries = []
    exact_countries = [
        code for code, names in COUNTRY_NAMES.items()
        if any(name in eligibility_text for name in names)
    ]
    regional = any(marker in eligibility_text for marker in REGIONAL_MARKERS)
    if not regional and not exact_countries:
        regional = bool(re.search(
            r"(?:remote|work(?:ing)? from)[^.!?\n]{0,50}\b(?:worldwide|anywhere|global|europe|emea|eea|eu)\b",
            text,
            re.IGNORECASE,
        ))
    if remote and regional:
        countries = ["BG", "PL"]
    elif remote:
        countries = exact_countries or [
            code for code, names in COUNTRY_NAMES.items()
            if any(re.search(rf"(?:remote|work(?:ing)? from)[^.!?\n]{{0,50}}\b{re.escape(name)}\b", text, re.IGNORECASE) for name in names)
        ]

    confidence = "high" if any(variant.get("remote") is True for variant in source_variants) and countries else "medium" if countries else "unknown"
    return {
        "technologies": technologies,
        "work_countries": sorted(countries),
        "eligibility_confidence": confidence,
        "is_public": bool(technologies and countries and job.get("description")),
    }


def refresh_job(conn, job_id: str) -> None:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT jp.id, jp.title, jp.description, jp.location, jp.search_query,
                  jp.structured_data, jp.source_structured_data,
                  ARRAY(SELECT metadata::text FROM job_posting_aliases WHERE job_id = jp.id) AS alias_metadata
           FROM job_postings jp WHERE jp.id = %s""",
        (job_id,),
    )
    row = cur.fetchone()
    if not row:
        return
    metadata = classify_catalog_job(dict(row))
    cur.execute(
        """INSERT INTO job_catalog_metadata
               (job_id, technologies, work_countries, eligibility_confidence, is_public, classifier_version, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (job_id) DO UPDATE SET
               technologies = EXCLUDED.technologies,
               work_countries = EXCLUDED.work_countries,
               eligibility_confidence = EXCLUDED.eligibility_confidence,
               is_public = EXCLUDED.is_public,
               classifier_version = EXCLUDED.classifier_version,
               updated_at = CURRENT_TIMESTAMP""",
        (job_id, metadata["technologies"], metadata["work_countries"], metadata["eligibility_confidence"], metadata["is_public"], CLASSIFIER_VERSION),
    )


def backfill(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """SELECT jp.id FROM job_postings jp
           LEFT JOIN job_catalog_metadata jcm ON jcm.job_id = jp.id
           WHERE jcm.job_id IS NULL OR jcm.classifier_version != %s""",
        (CLASSIFIER_VERSION,),
    )
    for row in cur.fetchall():
        refresh_job(conn, row[0])
