import json
import re

from db import dict_cursor


TECHNOLOGY_PATTERNS = {
    "php": (r"\bphp\b", r"\bsymfony\b", r"\blaravel\b"),
    "python": (r"\bpython\b", r"\bdjango\b", r"\bfastapi\b", r"\bflask\b"),
    "nodejs": (r"\bnode(?:\.js|js)?\b", r"\bnestjs\b", r"\bexpress(?:\.js|js)?\b"),
    "react": (r"\breact(?:\.js|js)?\b", r"\bnext(?:\.js|js)?\b"),
    "angular": (r"\bangular\b",),
    "java": (r"\bjava\b", r"\bspring(?: boot)?\b"),
    "dotnet": (r"\.net\b", r"\bdotnet\b", r"\bc#(?=\W|$)", r"\basp\.net\b"),
    "go": (r"\bgolang\b", r"\bgo\b(?=.{0,30}\b(?:back[ -]?end|software|developer|engineer)\b)"),
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

ROLE_FAMILY_PATTERNS = {
    "software-engineering": (
        r"\bsoftware (?:developer|engineer)\b",
        r"\bapplication developer\b",
        r"\bproduct engineer\b",
        r"\b(?:php|python|java|golang|go|dotnet|node(?:\.js|js)?|react(?:\.js|js)?|angular) (?:developer|engineer)\b",
    ),
    "backend": (r"\bback[ -]?end (?:developer|engineer)\b",),
    "frontend": (r"\bfront[ -]?end (?:developer|engineer)\b", r"\bweb developer\b"),
    "fullstack": (r"\bfull[ -]?stack (?:developer|engineer)\b",),
    "qa": TECHNOLOGY_PATTERNS["qa"],
    "mobile": (r"\bmobile (?:developer|engineer)\b", r"\bandroid developer\b", r"\bios developer\b"),
    "devops": (r"\bdevops\b", r"\bsite reliability engineer\b", r"\bplatform engineer\b"),
    "data": (r"\bdata engineer\b",),
    "ml-ai": (r"\bmachine learning engineer\b", r"\bai engineer\b", r"\bml engineer\b"),
}

COUNTRY_NAMES = {"PL": ("poland", "polska"), "BG": ("bulgaria", "bułgaria", "bulgariya")}
REGIONAL_MARKERS = ("worldwide", "anywhere", "global", "europe", "european", "emea", "eea", "eu-only", "eu only")
# Bump this whenever the public-catalog qualification rules change.  The
# migration backfill re-runs the classifier for rows carrying an older value.
CLASSIFIER_VERSION = 4

NON_FULL_REMOTE_DESCRIPTION_PATTERNS = (
    r"\b(?:required|mandatory)\s+(?:office|onsite|on-site)\b",
    r"\boffice (?:presence|attendance)\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\b(?:required|expected)\s+to\s+(?:work|attend)[^.!?\n]{0,30}\b(?:office|onsite|on-site)\b",
    r"\b\d+\s+(?:office|onsite|on-site)\s+days?\b",
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
    for alias in alias_data:
        source_variants.append(_json_dict(alias.get("source_structured_data")))
    stacks = []
    structured_skills = structured.get("skills") or []
    if structured_skills:
        for key in ("stack_required", "stack_preferred"):
            value = structured.get(key) or []
            stacks.extend(value if isinstance(value, list) else [value])
    else:
        for key in ("stack", "stack_required", "stack_preferred"):
            value = structured.get(key) or source_data.get(key) or []
            stacks.extend(value if isinstance(value, list) else [value])
    for skill in structured_skills:
        if isinstance(skill, dict):
            if skill.get("importance") not in {"incidental", "context"}:
                stacks.extend([skill.get("canonical_name"), skill.get("original_name")])
    category_text = " ".join(str(value or "") for value in (job.get("title"), *stacks)).lower()
    if not structured and not stacks:
        category_text = f"{category_text} {job.get('description') or ''}".lower()
    text = " ".join(str(value or "") for value in (
        job.get("title"), job.get("description"), *stacks,
    )).lower()
    technologies = [
        technology for technology, patterns in TECHNOLOGY_PATTERNS.items()
        if technology != "qa"
        if any(re.search(pattern, category_text, re.IGNORECASE) for pattern in patterns)
    ]
    qa_text = " ".join(str(value or "") for value in (job.get("title"), *stacks)).lower()
    if any(re.search(pattern, qa_text, re.IGNORECASE) for pattern in TECHNOLOGY_PATTERNS["qa"]):
        technologies.append("qa")
    technologies.sort()

    title = str(job.get("title") or "").lower()
    extracted_role = str(structured.get("role_family") or "").strip().lower().replace("_", "-")
    role_aliases = {
        "software": "software-engineering", "software-engineering": "software-engineering",
        "back-end": "backend", "front-end": "frontend", "full-stack": "fullstack",
        "machine-learning": "ml-ai", "ml": "ml-ai", "ai": "ml-ai",
    }
    extracted_role = role_aliases.get(extracted_role, extracted_role)
    role_families = [
        role for role, patterns in ROLE_FAMILY_PATTERNS.items()
        if any(re.search(pattern, title, re.IGNORECASE) for pattern in patterns)
    ]
    if extracted_role in ROLE_FAMILY_PATTERNS:
        role_families.append(extracted_role)
    if role_families and "software-engineering" not in role_families and any(
        role in role_families for role in ("backend", "frontend", "fullstack")
    ):
        role_families.append("software-engineering")
    role_families = sorted(set(role_families))

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
    source_remote_available = any(variant.get("remote_available") is True for variant in source_variants)
    extracted_remote_available = structured.get("remote_available") is True
    remote_available_known = isinstance(structured.get("remote_available"), bool) or any(
        isinstance(variant.get("remote_available"), bool) for variant in source_variants
    )
    source_remote_signal = source_remote_available or any(
        variant.get("remote") is True for variant in source_variants
    )
    if isinstance(structured.get("remote_available"), bool):
        remote = structured["remote_available"]
    elif source_remote_available:
        remote = True
    elif any(isinstance(variant.get("remote_available"), bool) for variant in source_variants):
        remote = False
    else:
        remote = structured.get("remote") is True or any(
            variant.get("remote") is True for variant in source_variants
        )
    if not remote_available_known and not remote and re.search(r"\b(?:fully|100%|all)\s*[- ]?remote\b|\bremote[- ]only\b", location):
        remote = True

    description = str(job.get("description") or "").lower()
    office_presence_required = any(
        variant.get("office_presence_required") is True for variant in source_variants
    ) or structured.get("office_presence_required") is True
    office_presence_optional = (
        (source_remote_available and any(variant.get("office_presence_required") is False for variant in source_variants))
        or (extracted_remote_available and structured.get("office_presence_required") is False)
    )
    has_required_office_marker = any(
        re.search(pattern, description) for pattern in NON_FULL_REMOTE_DESCRIPTION_PATTERNS
    )
    has_location_office_marker = any(marker in location for marker in (
        "hybrid", "hybryd", "on-site", "onsite", "on site", "office-based", "office based",
    ))
    full_remote = remote and not (
        office_presence_required
        or has_required_office_marker
        or (has_location_office_marker and not office_presence_optional)
    )

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
    explicit_ineligible = {
        code for code, item in country_items.items() if item.get("eligible") is False
    }
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
    source_country_evidence = bool(source_remote_signal and exact_countries)
    confidence = (
        "high" if countries and (has_structured_evidence or source_country_evidence)
        else "medium" if countries else "unknown"
    )
    return {
        "technologies": technologies,
        "role_families": role_families,
        "work_countries": sorted(countries),
        "eligibility_confidence": confidence,
        "is_public": bool((technologies or role_families) and countries and job.get("description") and full_remote),
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
               (job_id, technologies, role_families, work_countries, eligibility_confidence, is_public, classifier_version, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (job_id) DO UPDATE SET
               technologies = EXCLUDED.technologies,
               role_families = EXCLUDED.role_families,
               work_countries = EXCLUDED.work_countries,
               eligibility_confidence = EXCLUDED.eligibility_confidence,
               is_public = EXCLUDED.is_public,
               classifier_version = EXCLUDED.classifier_version,
               updated_at = CURRENT_TIMESTAMP""",
        (job_id, metadata["technologies"], metadata["role_families"], metadata["work_countries"], metadata["eligibility_confidence"], metadata["is_public"], CLASSIFIER_VERSION),
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
