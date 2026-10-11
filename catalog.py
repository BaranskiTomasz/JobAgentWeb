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
# Bump this whenever the public-catalog qualification rules change.  The
# migration backfill re-runs the classifier for rows carrying an older value.
CLASSIFIER_VERSION = 6

NON_FULL_REMOTE_DESCRIPTION_PATTERNS = (
    r"\b(?:required|mandatory)\s+(?:office|onsite|on-site)\b",
    r"\boffice (?:presence|attendance)\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\b(?:required|expected)\s+to\s+(?:work|attend)[^.!?\n]{0,30}\b(?:office|onsite|on-site)\b",
    r"\b\d+\s+(?:office|onsite|on-site)\s+days?\b",
)
EXPLICIT_BROAD_COUNTRIES = {
    "EU", "EEA", "EUROPE", "EUROPEAN UNION", "EMEA", "WORLDWIDE", "GLOBAL", "ANYWHERE",
}


def _normalise_region(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _region_code(value: str) -> str | None:
    normalized = _normalise_region(value)
    if normalized in EXPLICIT_BROAD_COUNTRIES:
        return normalized
    for marker in sorted(EXPLICIT_BROAD_COUNTRIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(marker)}\b", normalized):
            return marker
    if re.search(r"\bEUROPEAN\b", normalized):
        return "EUROPE"
    return next((code for code, names in COUNTRY_NAMES.items() if any(
        re.search(rf"\b{re.escape(name.upper())}\b", normalized)
        for name in names
    )), None)


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

    # A remote flag says how the work is performed, not where it may legally
    # be performed.  Keep the two decisions separate: only explicit country
    # or broad-region evidence may populate work_countries.  In particular,
    # a bare ``Remote`` location and ``eligible=None`` are not evidence.
    region_values = [str(region) for region in regions if str(region).strip()]
    region_codes = {_region_code(region) for region in region_values}
    region_codes.discard(None)
    source_region_values = []
    for variant in source_variants:
        values = variant.get("remote_regions") or []
        source_region_values.extend(values if isinstance(values, list) else [values])
    source_region_values = [str(region) for region in source_region_values if str(region).strip()]
    source_region_codes = {_region_code(region) for region in source_region_values}
    source_region_codes.discard(None)
    source_region_present = any(
        _normalise_region(region) not in {"REMOTE", "FULLY REMOTE", "REMOTE ONLY"}
        for region in source_region_values
    )
    location_code = _region_code(location)
    location_has_remote_marker = bool(re.search(r"\bremote\b", location))
    location_remote_evidence = location_has_remote_marker or source_remote_signal or extracted_remote_available
    description_country_evidence = {
        code for code, names in COUNTRY_NAMES.items()
        if any(re.search(
            rf"\b(?:remote|work(?:ing)? from)\b[^.!?\n]{{0,60}}\b{re.escape(name)}\b",
            text,
            re.IGNORECASE,
        ) for name in names)
    }
    broad_description_evidence = bool(re.search(
        r"\b(?:remote|work(?:ing)? from)\b[^.!?\n]{0,60}\b(?:worldwide|anywhere|global|europe|european|emea|eea|eu)\b",
        text,
        re.IGNORECASE,
    ))
    broad_evidence = bool(region_codes & EXPLICIT_BROAD_COUNTRIES) or (
        location_remote_evidence and location_code in EXPLICIT_BROAD_COUNTRIES
    ) or (broad_description_evidence and not source_region_present)
    direct_region_evidence = {
        code for code in (source_region_codes if source_region_present else region_codes)
        if code in COUNTRY_NAMES
    }
    if not source_region_present and location_remote_evidence and location_code in COUNTRY_NAMES:
        direct_region_evidence.add(location_code)
    if source_region_present:
        broad_evidence = bool(source_region_codes & EXPLICIT_BROAD_COUNTRIES)
        description_country_evidence = set()

    # Structured country eligibility is stronger than inferred text.  If
    # extraction explicitly denies a country, never add it back from broad
    # geographic text; unknown (None) likewise never grants access.
    country_items = {}
    broad_eligible = False
    catalog_gate_only = structured.get("_extraction_tier") == "catalog_gate"
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
        positive_item = item.get("eligible") is True and (
            not catalog_gate_only or bool(item.get("evidence"))
        )
        if code in EXPLICIT_BROAD_COUNTRIES and positive_item and (
            not source_region_present or bool(source_region_codes & EXPLICIT_BROAD_COUNTRIES)
        ):
            broad_eligible = True
        if code in {"PL", "BG"}:
            country_items[code] = item

    explicit_eligibility = {
        code for code, item in country_items.items()
        if item.get("eligible") is True and (not catalog_gate_only or bool(item.get("evidence")))
    }
    explicit_ineligible = {
        code for code, item in country_items.items() if item.get("eligible") is False
    }
    countries = set(explicit_eligibility) | direct_region_evidence | description_country_evidence
    if broad_evidence or broad_eligible:
        countries |= {"PL", "BG"}
    countries -= explicit_ineligible
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
    source_region_evidence = bool(source_remote_signal and (direct_region_evidence or broad_evidence))
    confidence = (
        "high" if countries and (has_structured_evidence or source_region_evidence)
        else "medium" if countries else "unknown"
    )
    return {
        "technologies": technologies,
        "role_families": role_families,
        "work_countries": sorted(countries),
        "company_country": structured.get("company_country"),
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
               (job_id, technologies, role_families, work_countries, company_country, eligibility_confidence, is_public, classifier_version, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (job_id) DO UPDATE SET
               technologies = EXCLUDED.technologies,
               role_families = EXCLUDED.role_families,
               work_countries = EXCLUDED.work_countries,
               company_country = EXCLUDED.company_country,
               eligibility_confidence = EXCLUDED.eligibility_confidence,
               is_public = EXCLUDED.is_public,
               classifier_version = EXCLUDED.classifier_version,
               updated_at = CURRENT_TIMESTAMP""",
        (job_id, metadata["technologies"], metadata["role_families"], metadata["work_countries"], metadata["company_country"], metadata["eligibility_confidence"], metadata["is_public"], CLASSIFIER_VERSION),
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
