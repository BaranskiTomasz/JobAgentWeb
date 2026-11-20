import pytest

import apply_decision
import apply_execution_repo
import autonomy_repo


def _create_job(client, suffix: str, *, company: str = "Acme") -> str:
    response = client.post(
        "/api/jobs",
        json={
            "title": "Backend Engineer",
            "company": company,
            "location": "Remote",
            "url": f"https://example.com/apply-decision/{suffix}",
            "source": "linkedin",
            "description": "Build reliable systems.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["job_id"]


def _create_plan(client, job_id: str, *, with_field: bool = True) -> int:
    response = client.post("/api/application-plans", json={"job_id": job_id})
    assert response.status_code == 200, response.text
    plan_id = response.json()["id"]
    if with_field:
        field_response = client.put(
            f"/api/application-plans/{plan_id}/fields/cover_letter",
            json={"value": "I am interested in this role."},
        )
        assert field_response.status_code == 200, field_response.text
    return plan_id


def test_decide_and_queue_records_default_decision_and_manual_execution(
    db_conn, user, logged_in_client
):
    job_id = _create_job(logged_in_client, "default")
    plan_id = _create_plan(logged_in_client, job_id)

    result = apply_decision.decide_and_queue(db_conn, user["id"], plan_id)

    assert set(result) == {
        "decision_id",
        "level",
        "reasons",
        "execution_id",
        "execution_status",
    }
    assert result["execution_status"] == "pending_manual_action"
    decisions = autonomy_repo.get_recent_decisions(db_conn, user["id"])
    assert len(decisions) == 1
    assert decisions[0]["id"] == result["decision_id"]
    execution = apply_execution_repo.get_execution(
        db_conn, user["id"], result["execution_id"]
    )
    assert execution["status"] == "pending_manual_action"
    assert execution["attempt_count"] == 1


def test_employer_known_uses_company_applied_count(db_conn, user, logged_in_client):
    applied_job_id = _create_job(logged_in_client, "known-applied", company="Known Co")
    target_job_id = _create_job(logged_in_client, "known-target", company="Known Co")
    unknown_job_id = _create_job(logged_in_client, "unknown-target", company="Unknown Co")
    response = logged_in_client.patch(
        f"/api/jobs/{applied_job_id}/status", json={"status": "applied"}
    )
    assert response.status_code == 200, response.text

    known_plan_id = _create_plan(logged_in_client, target_job_id)
    unknown_plan_id = _create_plan(logged_in_client, unknown_job_id)
    known_result = apply_decision.decide_and_queue(
        db_conn, user["id"], known_plan_id
    )
    unknown_result = apply_decision.decide_and_queue(
        db_conn, user["id"], unknown_plan_id
    )

    decisions = {
        row["id"]: row for row in autonomy_repo.get_recent_decisions(db_conn, user["id"])
    }
    assert decisions[known_result["decision_id"]]["inputs"]["employer_known"] is True
    assert decisions[unknown_result["decision_id"]]["inputs"]["employer_known"] is False


def test_fieldless_plan_creates_no_decision_or_execution(
    db_conn, user, logged_in_client
):
    job_id = _create_job(logged_in_client, "fieldless")
    plan_id = _create_plan(logged_in_client, job_id, with_field=False)

    with pytest.raises(ValueError, match="Plan has no fields yet"):
        apply_decision.decide_and_queue(db_conn, user["id"], plan_id)

    cur = db_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM autonomy_decisions WHERE user_id = %s", (user["id"],))
    assert cur.fetchone()[0] == 0
    cur.execute(
        "SELECT COUNT(*) FROM application_executions WHERE user_id = %s AND plan_id = %s",
        (user["id"], plan_id),
    )
    assert cur.fetchone()[0] == 0


def test_count_executions_today_is_user_scoped(
    db_conn,
    user,
    other_user,
    logged_in_client,
    other_logged_in_client,
):
    first_plan = _create_plan(
        logged_in_client, _create_job(logged_in_client, "count-first")
    )
    second_plan = _create_plan(
        logged_in_client, _create_job(logged_in_client, "count-second")
    )
    other_plan = _create_plan(
        other_logged_in_client,
        _create_job(other_logged_in_client, "count-other", company="Other Co"),
    )

    apply_decision.decide_and_queue(db_conn, user["id"], first_plan)
    apply_decision.decide_and_queue(db_conn, user["id"], second_plan)
    apply_decision.decide_and_queue(db_conn, other_user["id"], other_plan)

    assert apply_execution_repo.count_executions_today(db_conn, user["id"]) == 2
    assert apply_execution_repo.count_executions_today(db_conn, other_user["id"]) == 1


def test_decide_endpoint_handles_ownership_fields_and_success(
    logged_in_client, other_logged_in_client
):
    other_plan = _create_plan(
        other_logged_in_client,
        _create_job(other_logged_in_client, "api-other", company="Other Co"),
    )
    response = logged_in_client.post(f"/api/application-plans/{other_plan}/decide")
    assert response.status_code == 404

    fieldless_plan = _create_plan(
        logged_in_client,
        _create_job(logged_in_client, "api-fieldless"),
        with_field=False,
    )
    response = logged_in_client.post(f"/api/application-plans/{fieldless_plan}/decide")
    assert response.status_code == 400
    assert response.json()["detail"] == "Plan has no fields yet"

    built_plan = _create_plan(
        logged_in_client, _create_job(logged_in_client, "api-built")
    )
    response = logged_in_client.post(f"/api/application-plans/{built_plan}/decide")
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "decision_id",
        "level",
        "reasons",
        "execution_id",
        "execution_status",
    }
    assert body["execution_status"] == "pending_manual_action"
