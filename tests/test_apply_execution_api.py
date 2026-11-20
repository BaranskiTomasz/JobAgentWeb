import pytest

import application_plan_repo
import apply_execution_repo


def _insert_job(conn, job_id: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_postings (id, title, url) VALUES (%s, 'Test Title', %s)",
        (job_id, f"https://example.com/jobs/{job_id}"),
    )
    conn.commit()


def _create_plan(conn, user_id: int, job_id: str) -> int:
    _insert_job(conn, job_id)
    return application_plan_repo.create_plan(conn, user_id, job_id)


def test_create_execution_generates_key_and_is_retrievable(db_conn, user):
    plan_id = _create_plan(db_conn, user["id"], "execution_generated_key")

    execution = apply_execution_repo.create_execution(db_conn, user["id"], plan_id)

    assert execution["idempotency_key"].startswith(f"plan:{plan_id}:")
    assert apply_execution_repo.get_execution(
        db_conn, user["id"], execution["id"]
    ) == execution


def test_create_execution_is_idempotent_for_supplied_key(db_conn, user):
    plan_id = _create_plan(db_conn, user["id"], "execution_idempotent")

    first = apply_execution_repo.create_execution(
        db_conn, user["id"], plan_id, idempotency_key="stable-key"
    )
    second = apply_execution_repo.create_execution(
        db_conn, user["id"], plan_id, idempotency_key="stable-key"
    )

    assert first["id"] == second["id"]
    assert len(
        apply_execution_repo.list_executions_for_plan(db_conn, user["id"], plan_id)
    ) == 1


def test_status_transitions_increment_attempt_count_once(db_conn, user):
    plan_id = _create_plan(db_conn, user["id"], "execution_status")
    execution = apply_execution_repo.create_execution(db_conn, user["id"], plan_id)

    in_progress = apply_execution_repo.update_status(
        db_conn, user["id"], execution["id"], "in_progress"
    )
    assert in_progress["attempt_count"] == 1

    sent = apply_execution_repo.update_status(
        db_conn,
        user["id"],
        execution["id"],
        "sent",
        external_application_id="external-123",
    )
    assert sent["attempt_count"] == 1
    assert sent["external_application_id"] == "external-123"

    with pytest.raises(ValueError):
        apply_execution_repo.update_status(
            db_conn, user["id"], execution["id"], "in_progress"
        )


def test_api_invalid_transition_returns_conflict(
    db_conn, user, logged_in_client
):
    plan_id = _create_plan(db_conn, user["id"], "execution_api_conflict")
    execution = apply_execution_repo.create_execution(db_conn, user["id"], plan_id)
    apply_execution_repo.update_status(
        db_conn, user["id"], execution["id"], "in_progress"
    )
    apply_execution_repo.update_status(db_conn, user["id"], execution["id"], "sent")
    db_conn.commit()

    response = logged_in_client.patch(
        f"/api/executions/{execution['id']}/status", json={"status": "in_progress"}
    )

    assert response.status_code == 409


def test_api_crud_and_idempotency(db_conn, user, logged_in_client):
    plan_id = _create_plan(db_conn, user["id"], "execution_api_crud")
    db_conn.commit()

    first = logged_in_client.post(
        f"/api/application-plans/{plan_id}/executions",
        json={"idempotency_key": "api-stable-key"},
    )
    second = logged_in_client.post(
        f"/api/application-plans/{plan_id}/executions",
        json={"idempotency_key": "api-stable-key"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    listed = logged_in_client.get(f"/api/application-plans/{plan_id}/executions")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = logged_in_client.get(f"/api/executions/{first.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == first.json()["id"]


def test_cross_user_isolation(
    db_conn, user, other_user, other_logged_in_client
):
    plan_id = _create_plan(db_conn, user["id"], "execution_isolation")
    execution = apply_execution_repo.create_execution(db_conn, user["id"], plan_id)
    db_conn.commit()

    with pytest.raises(ValueError, match="not found or not owned"):
        apply_execution_repo.create_execution(db_conn, other_user["id"], plan_id)
    assert (
        apply_execution_repo.get_execution(
            db_conn, other_user["id"], execution["id"]
        )
        is None
    )
    with pytest.raises(ValueError, match="not found or not owned"):
        apply_execution_repo.update_status(
            db_conn, other_user["id"], execution["id"], "in_progress"
        )

    create_response = other_logged_in_client.post(
        f"/api/application-plans/{plan_id}/executions", json={}
    )
    get_response = other_logged_in_client.get(f"/api/executions/{execution['id']}")
    update_response = other_logged_in_client.patch(
        f"/api/executions/{execution['id']}/status",
        json={"status": "in_progress"},
    )
    assert create_response.status_code == 404
    assert get_response.status_code == 404
    assert update_response.status_code == 404
