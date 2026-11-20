import pytest

from apply_executor import VALID_TRANSITIONS, validate_transition


def test_all_allowed_and_disallowed_transitions():
    statuses = set(VALID_TRANSITIONS)
    for current_status, allowed_statuses in VALID_TRANSITIONS.items():
        for new_status in allowed_statuses:
            validate_transition(current_status, new_status)

        disallowed_status = next(iter(statuses - allowed_statuses))
        with pytest.raises(ValueError):
            validate_transition(current_status, disallowed_status)


def test_same_status_transition_raises():
    with pytest.raises(ValueError, match="queued.*queued"):
        validate_transition("queued", "queued")


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [("bogus", "sent"), ("queued", "bogus")],
)
def test_unrecognized_status_raises_value_error(current_status, new_status):
    with pytest.raises(ValueError):
        validate_transition(current_status, new_status)
