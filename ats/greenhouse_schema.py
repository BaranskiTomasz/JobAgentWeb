from dataclasses import dataclass, field

import httpx

_STANDARD_FIELD_NAMES = {
    "first_name",
    "last_name",
    "email",
    "phone",
    "resume",
    "resume_text",
    "cover_letter",
    "cover_letter_text",
}


@dataclass
class GreenhouseFormField:
    field_id: str
    label: str
    field_type: str
    required: bool
    options: list[str] = field(default_factory=list)
    is_standard: bool = False


def fetch_job_schema(slug: str, job_id: str, *, http_client=None) -> list[GreenhouseFormField]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}?questions=true"
    if http_client is not None:
        response = http_client.get(url)
    else:
        with httpx.Client() as client:
            response = client.get(url)
    response.raise_for_status()

    payload = response.json()
    questions = payload.get("questions") or []

    fields: list[GreenhouseFormField] = []
    for question in questions:
        group_label = question.get("label") or ""
        group_required = bool(question.get("required", False))
        for item in question.get("fields") or []:
            name = item.get("name") or ""
            fields.append(
                GreenhouseFormField(
                    field_id=name,
                    label=group_label,
                    field_type=item.get("type") or "",
                    required=group_required,
                    options=[v["label"] for v in item.get("values") or [] if "label" in v],
                    is_standard=name in _STANDARD_FIELD_NAMES,
                )
            )

    return fields


@dataclass
class FieldMappingResult:
    field_id: str
    label: str
    required: bool
    mapped_value: str | None
    plan_field_name: str | None


def map_plan_to_schema(plan_fields: list[dict], schema: list[GreenhouseFormField]) -> list[FieldMappingResult]:
    # Exact field_id index
    exact_by_id = {}
    # Case-folded label index
    by_label = {}
    for pf in plan_fields:
        fn = pf.get("field_name")
        if fn is not None:
            if fn not in exact_by_id:
                exact_by_id[fn] = pf
            fn_folded = fn.casefold()
            if fn_folded not in by_label:
                by_label[fn_folded] = pf

    results: list[FieldMappingResult] = []
    for sf in schema:
        matched_plan = exact_by_id.get(sf.field_id)
        if matched_plan is None:
            matched_plan = by_label.get(sf.label.casefold())

        if matched_plan is not None:
            results.append(
                FieldMappingResult(
                    field_id=sf.field_id,
                    label=sf.label,
                    required=sf.required,
                    mapped_value=matched_plan.get("value"),
                    plan_field_name=matched_plan.get("field_name"),
                )
            )
        else:
            results.append(
                FieldMappingResult(
                    field_id=sf.field_id,
                    label=sf.label,
                    required=sf.required,
                    mapped_value=None,
                    plan_field_name=None,
                )
            )

    return results


def missing_required_fields(mapping: list[FieldMappingResult]) -> list[str]:
    return [
        res.field_id
        for res in mapping
        if res.required is True and res.mapped_value is None
    ]
