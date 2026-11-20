import pytest

from autonomy_policy import AutonomyInputs, evaluate_autonomy, filter_to_allowed_fields


DEFAULT_SETTINGS = {
    "max_daily_auto_sends": 5,
    "min_confidence_auto_send": 0.9,
    "allowed_auto_send_sources": ["trusted_board"],
}


def make_inputs(**overrides) -> AutonomyInputs:
    values = {
        "match_confidence": 0.95,
        "employer_known": True,
        "fields_fully_grounded": True,
        "has_irreversible_negotiable_fields": False,
        "source": "trusted_board",
        "applications_sent_today": 0,
    }
    values.update(overrides)
    return AutonomyInputs(**values)


@pytest.mark.parametrize(
    ("overrides", "expected_level", "reason_fragment"),
    [
        ({"fields_fully_grounded": False}, "ask_first", "could not be grounded"),
        (
            {"has_irreversible_negotiable_fields": True},
            "review_then_send",
            "irreversible negotiable fields",
        ),
        ({"applications_sent_today": 5}, "review_then_send", "daily auto-send limit is 5"),
        ({"match_confidence": 0.89}, "review_then_send", "below the auto-send threshold"),
        ({"source": "unknown_board"}, "review_then_send", "'unknown_board'"),
        ({}, "auto_send", "conditions are satisfied"),
    ],
    ids=["rule_1", "rule_2", "rule_3", "rule_4", "rule_5", "rule_6"],
)
def test_policy_rules(overrides, expected_level, reason_fragment):
    decision = evaluate_autonomy(make_inputs(**overrides), DEFAULT_SETTINGS)

    assert decision.level == expected_level
    assert decision.reasons
    assert any(reason_fragment in reason for reason in decision.reasons)


def test_grounding_gap_wins_when_every_other_rule_also_blocks():
    inputs = make_inputs(
        fields_fully_grounded=False,
        has_irreversible_negotiable_fields=True,
        applications_sent_today=5,
        match_confidence=0.1,
        source="unknown_board",
    )

    decision = evaluate_autonomy(inputs, DEFAULT_SETTINGS)

    assert decision.level == "ask_first"
    assert decision.reasons == [
        "One or more form fields could not be grounded in a candidate fact."
    ]


def test_irreversible_negotiable_fields_cap_result_when_other_checks_pass():
    decision = evaluate_autonomy(
        make_inputs(has_irreversible_negotiable_fields=True),
        DEFAULT_SETTINGS,
    )

    assert decision.level == "review_then_send"
    assert len(decision.reasons) == 1
    assert "irreversible negotiable fields" in decision.reasons[0]


@pytest.mark.parametrize(
    ("applications_sent_today", "expected_level"),
    [(5, "review_then_send"), (4, "auto_send")],
)
def test_daily_limit_boundary(applications_sent_today, expected_level):
    decision = evaluate_autonomy(
        make_inputs(applications_sent_today=applications_sent_today),
        DEFAULT_SETTINGS,
    )

    assert decision.level == expected_level


@pytest.mark.parametrize(
    ("match_confidence", "expected_level"),
    [(0.9, "auto_send"), (0.9 - float.fromhex("0x1p-52"), "review_then_send")],
)
def test_confidence_boundary(match_confidence, expected_level):
    decision = evaluate_autonomy(
        make_inputs(match_confidence=match_confidence),
        DEFAULT_SETTINGS,
    )

    assert decision.level == expected_level


def test_filter_to_allowed_fields_keeps_known_and_drops_unknown():
    allowed, dropped = filter_to_allowed_fields(
        {"email": "candidate@example.com", "invented_salary": "100000"},
        {"email"},
    )

    assert allowed == {"email": "candidate@example.com"}
    assert dropped == ["invented_salary"]
