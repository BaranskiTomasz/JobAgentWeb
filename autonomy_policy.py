from dataclasses import dataclass


@dataclass
class AutonomyInputs:
    match_confidence: float
    employer_known: bool
    fields_fully_grounded: bool
    has_irreversible_negotiable_fields: bool
    source: str
    applications_sent_today: int


@dataclass
class AutonomyDecision:
    level: str
    reasons: list[str]


def evaluate_autonomy(inputs: AutonomyInputs, settings: dict) -> AutonomyDecision:
    if not inputs.fields_fully_grounded:
        return AutonomyDecision(
            level="ask_first",
            reasons=["One or more form fields could not be grounded in a candidate fact."],
        )

    reasons: list[str] = []
    if inputs.has_irreversible_negotiable_fields:
        reasons.append("The application contains irreversible negotiable fields that require review.")

    max_daily_auto_sends = settings["max_daily_auto_sends"]
    if inputs.applications_sent_today >= max_daily_auto_sends:
        reasons.append(
            f"The daily auto-send limit is {max_daily_auto_sends}, and {inputs.applications_sent_today} applications have already been sent today."
        )

    min_confidence = settings["min_confidence_auto_send"]
    if inputs.match_confidence < min_confidence:
        reasons.append(
            f"The match confidence of {inputs.match_confidence} is below the auto-send threshold of {min_confidence}."
        )

    if inputs.source not in settings["allowed_auto_send_sources"]:
        reasons.append(f"The application source '{inputs.source}' is not allowed for auto-send.")

    if reasons:
        return AutonomyDecision(level="review_then_send", reasons=reasons)
    return AutonomyDecision(
        level="auto_send",
        reasons=["All autonomy conditions are satisfied."],
    )


def filter_to_allowed_fields(
    application_plan_fields: dict,
    candidate_fact_field_names: set[str],
) -> tuple[dict, list[str]]:
    """Return allowed fields and the names of fields without a candidate-fact source."""
    allowed_fields = {
        name: value
        for name, value in application_plan_fields.items()
        if name in candidate_fact_field_names
    }
    dropped_field_names = [
        name for name in application_plan_fields if name not in candidate_fact_field_names
    ]
    return allowed_fields, dropped_field_names
