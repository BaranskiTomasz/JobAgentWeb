import autonomy_repo
from autonomy_policy import AutonomyDecision, AutonomyInputs


def test_get_settings_returns_defaults_when_unset(logged_in_client):
    response = logged_in_client.get("/api/autonomy/settings")

    assert response.status_code == 200
    assert response.json() == {
        "max_daily_auto_sends": 0,
        "min_confidence_auto_send": 0.9,
        "allowed_auto_send_sources": [],
    }


def test_patch_one_field_preserves_other_settings(logged_in_client):
    initial = logged_in_client.patch(
        "/api/autonomy/settings",
        json={
            "max_daily_auto_sends": 7,
            "min_confidence_auto_send": 0.82,
            "allowed_auto_send_sources": ["greenhouse", "lever"],
        },
    )
    assert initial.status_code == 200, initial.text

    response = logged_in_client.patch(
        "/api/autonomy/settings",
        json={"max_daily_auto_sends": 3},
    )

    assert response.status_code == 200, response.text
    settings = response.json()
    assert settings["max_daily_auto_sends"] == 3
    assert settings["min_confidence_auto_send"] == 0.82
    assert settings["allowed_auto_send_sources"] == ["greenhouse", "lever"]


def test_record_and_get_recent_decisions_round_trip(db_conn, user):
    inputs = AutonomyInputs(
        match_confidence=0.94,
        employer_known=True,
        fields_fully_grounded=True,
        has_irreversible_negotiable_fields=False,
        source="greenhouse",
        applications_sent_today=1,
    )
    decision = AutonomyDecision(
        level="auto_send",
        reasons=["All autonomy conditions are satisfied."],
    )

    decision_id = autonomy_repo.record_decision(
        db_conn, user["id"], None, decision, inputs
    )
    rows = autonomy_repo.get_recent_decisions(db_conn, user["id"])

    assert len(rows) == 1
    assert rows[0]["id"] == decision_id
    assert rows[0]["job_id"] is None
    assert rows[0]["level"] == "auto_send"
    assert rows[0]["reasons"] == decision.reasons
    assert rows[0]["inputs"] == {
        "match_confidence": 0.94,
        "employer_known": True,
        "fields_fully_grounded": True,
        "has_irreversible_negotiable_fields": False,
        "source": "greenhouse",
        "applications_sent_today": 1,
    }
    assert rows[0]["decided_at"] is not None


def test_cross_user_settings_and_decisions_are_isolated(
    db_conn,
    user,
    other_user,
    logged_in_client,
    other_logged_in_client,
):
    first_patch = logged_in_client.patch(
        "/api/autonomy/settings",
        json={"max_daily_auto_sends": 8, "allowed_auto_send_sources": ["lever"]},
    )
    second_patch = other_logged_in_client.patch(
        "/api/autonomy/settings",
        json={"min_confidence_auto_send": 0.75},
    )
    assert first_patch.status_code == 200
    assert second_patch.status_code == 200

    first_inputs = AutonomyInputs(0.95, True, True, False, "lever", 0)
    second_inputs = AutonomyInputs(0.8, True, True, False, "other", 0)
    first_id = autonomy_repo.record_decision(
        db_conn,
        user["id"],
        None,
        AutonomyDecision("auto_send", ["First user's decision."]),
        first_inputs,
    )
    second_id = autonomy_repo.record_decision(
        db_conn,
        other_user["id"],
        None,
        AutonomyDecision("review_then_send", ["Second user's decision."]),
        second_inputs,
    )
    db_conn.commit()

    first_settings = logged_in_client.get("/api/autonomy/settings").json()
    second_settings = other_logged_in_client.get("/api/autonomy/settings").json()
    assert first_settings["max_daily_auto_sends"] == 8
    assert first_settings["min_confidence_auto_send"] == 0.9
    assert first_settings["allowed_auto_send_sources"] == ["lever"]
    assert second_settings["max_daily_auto_sends"] == 0
    assert second_settings["min_confidence_auto_send"] == 0.75
    assert second_settings["allowed_auto_send_sources"] == []

    first_decisions = logged_in_client.get("/api/autonomy/decisions").json()
    second_decisions = other_logged_in_client.get("/api/autonomy/decisions").json()
    assert [row["id"] for row in first_decisions] == [first_id]
    assert [row["id"] for row in second_decisions] == [second_id]


def test_decision_limit_is_capped_at_200(logged_in_client):
    response = logged_in_client.get("/api/autonomy/decisions", params={"limit": 500})

    assert response.status_code == 200
    assert response.json() == []
