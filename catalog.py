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
        r"\b(?:software |automation )?test(?:er| engineer)\b",
        r"\bautomation tester\b",
        r"\bsoftware tester\b",
    ),
}

COUNTRY_NAMES = {"PL": ("poland", "polska"), "BG": ("bulgaria", "bułgaria", "bulgariya")}
REGIONAL_MARKERS = ("worldwide", "anywhere", "global", "europe", "european", "emea", "eea", "eu-only", "eu only")
# Bump this whenever the public-catalog qualification rules change.  The
# migration backfill re-runs the classifier for rows carrying an older value.
CLASSIFIER_VERSION = 3

# A public catalog item must be unambiguously full-remote.  In particular, a
# source may advertise both remote and hybrid work; that is useful to a
# personal search, but it is not a full-remote catalog result.
NON_FULL_REMOTE_LOCATION_MARKERS = (
    "hybrid", "hybryd", "on-site", "onsite", "on site", "office-based", "office based",
)
NON_FULL_REMOTE_DESCRIPTION_PATTERNS = (
    r"\bhybrid\s+(?:work|working|role|model|position|schedule)\b",
    r"\b(?:work|working)\s+(?:in|from)\s+(?:the\s+)?office\b",
    r"\b(?:required|mandatory)\s+(?:office|onsite|on-site)\b",
    r"\b\d+\s+(?:office|onsite|on-site)\s+days?\b",
    r"\boffice\s+days?\b",
)
EXPLICIT_BROAD_COUNTRIES = {
    "EU", "EEA", "EUROPE", "EUROPEAN UNION", "EMEA", "WORLDWIDE", "GLOBAL", "ANYWHERE",
}


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
    for skill in structured.get("skills") or []:
        if isinstance(skill, dict):
            stacks.extend([skill.get("canonical_name"), skill.get("original_name")])
    text = " ".join(str(value or "") for value in (
        job.get("title"), job.get("description"), *search_queries, *stacks,
    )).lower()
    technologies = [
        technology for technology, patterns in TECHNOLOGY_PATTERNS.items()
        if technology != "qa"
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
    ]
    qa_text = " ".join(str(value or "") for value in (job.get("title"), *stacks)).lower()
    if any(re.search(pattern, qa_text, re.IGNORECASE) for pattern in TECHNOLOGY_PATTERNS["qa"]):
        technologies.append("qa")
    technologies.sort()

    location = str(job.get("location") or "").lower()
    regions = []
    for variant in source_variants:
        value = variant.get("remote_regions") or []
        regions.extend(value if isinstance(value, list) else [value])
    structured_regions = structured.get("remote_regions") or []
    regions.extend(structured_regions if isinstance(structured_regions, list) else [structured_regions])
    eligibility_text = " ".join([location, *[str(region).lower() for region in regions]])

    # Only an explicit remote flag (from the source or extraction) qualifies
    # for the public catalog.  Inferring remote from a word in a location such
    # as ``Berlin``/``Remote-friendly`` was the source of hybrid and onsite
    # rows leaking into the catalog.  A clearly labelled "fully remote"
    # location remains a safe fallback for legacy rows without structured
    # data.
    source_remote = any(variant.get("remote") is True for variant in source_variants)
    extracted_remote = structured.get("remote") is True
    remote = source_remote or extracted_remote
    if not remote and re.search(r"\b(?:fully|100%|all)\s*[- ]?remote\b|\bremote[- ]only\b", location):
        remote = True

    source_hybrid = any(variant.get("hybrid") is True for variant in source_variants)
    extracted_hybrid = structured.get("hybrid") is True
    # The location is source-native for many boards (for example
    # ``Warsaw, Poland (Hybrid)``), so treat it as a hard exclusion.  The
    # description check is intentionally conservative: an ambiguous posting
    # mentioning hybrid/onsite work should not become a public full-remote
    # result until extraction supplies a clean remote-only fact.
    description = str(job.get("description") or "").lower()
    has_non_full_remote_marker = (
        any(marker in location for marker in NON_FULL_REMOTE_LOCATION_MARKERS)
        or any(re.search(pattern, description) for pattern in NON_FULL_REMOTE_DESCRIPTION_PATTERNS)
    )
    full_remote = remote and not (source_hybrid or extracted_hybrid or has_non_full_remote_marker)

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
    # Structured country eligibility is stronger than an inferred match from
    # a location/region.  If extraction explicitly says a country is not (or
    # is not known to be) eligible, never add it back from broad geographic
    # text.  This prevents e.g. "Remote" + an employer's country from being
    # presented as candidate eligibility.
    country_items = {}
    broad_eligible = False
    # Source-native eligibility is stronger than free text, while extracted
    # facts take precedence when both layers provide the same country.
    for item in [
        item
        for variant in source_variants
        for item in variant.get("country_eligibility") or []
    ] + list(structured.get("country_eligibility") or []):
        if not isinstance(item, dict):
            continue
        code = str(item.get("country_code") or "").strip().upper()
        if code in EXPLICIT_BROAD_COUNTRIES and item.get("eligible") is True:
            broad_eligible = True
        if code in {"PL", "BG"}:
            country_items[code] = item

    explicit_eligibility = {
        code for code, item in country_items.items() if item.get("eligible") is True
    }
    explicit_ineligible = set(country_items) - explicit_eligibility
    countries = (set(countries) | explicit_eligibility | ({"PL", "BG"} if broad_eligible else set())) - explicit_ineligible
    if not full_remote:
        countries = set()
    countries = sorted(countries)

    # Direct country eligibility evidence should be reflected in the catalog
    # metadata confidence.  Preserve the old high-confidence behavior for
    # source-native remote regions, while broad/inferred wording stays medium.
    has_structured_evidence = any(
        item.get("eligible") is True and (item.get("evidence") or item.get("confidence") is not None)
        for item in country_items.values()
    ) or broad_eligible
    source_country_evidence = bool(source_remote and exact_countries)
    confidence = (
        "high" if countries and (has_structured_evidence or source_country_evidence)
        else "medium" if countries else "unknown"
    )
    return {
        "technologies": technologies,
        "work_countries": sorted(countries),
        "eligibility_confidence": confidence,
        "is_public": bool(technologies and countries and job.get("description") and full_remote),
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
