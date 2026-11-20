VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"in_progress", "cancelled"},
    "in_progress": {"pending_manual_action", "sent", "send_failed", "cancelled"},
    "pending_manual_action": {"in_progress", "sent", "send_failed", "cancelled"},
    "send_failed": {"queued", "cancelled"},
    "sent": {"withdrawn"},
    "withdrawn": set(),
    "cancelled": set(),
}


def validate_transition(current_status: str, new_status: str) -> None:
    if (
        current_status not in VALID_TRANSITIONS
        or new_status not in VALID_TRANSITIONS
        or new_status not in VALID_TRANSITIONS.get(current_status, set())
    ):
        raise ValueError(
            f"Invalid application execution transition from {current_status} to {new_status}"
        )
