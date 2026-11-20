import pytest

import application_plan_repo
import candidate_facts_repo
from autonomy_policy import autonomy_inputs_from_plan


def _insert_job(conn, job_id: str):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO job_postings (id, title, url) VALUES (%s, 'Test Title', %s) ON CONFLICT (id) DO NOTHING",
        (job_id, f"https://example.com/jobs/{job_id}"),
    )
    conn.commit()


def test_create_plan_and_upsert_fields_and_get_plan(db_conn, user):
    user_id = user["id"]
    _insert_job(db_conn, "job_123")

    fact_id1 = candidate_facts_repo.insert(
        db_conn, user_id, "skill", "Python", source="manual"
    )
    fact_id2 = candidate_facts_repo.insert(
        db_conn, user_id, "education", "CS Degree", source="manual"
    )

    plan_id = application_plan_repo.create_plan(db_conn, user_id, "job_123")
    assert plan_id > 0

    fid1 = application_plan_repo.upsert_field(
        db_conn,
        user_id,
        plan_id,
        "skills",
        "Python expert",
        fact_ids=[fact_id1, fact_id2],
        confidence=0.95,
        is_negotiable_or_irreversible=False,
    )
    assert fid1 > 0

    fid2 = application_plan_repo.upsert_field(
        db_conn,
        user_id,
        plan_id,
        "cover_letter_intro",
        "Hello team",
        fact_ids=[],
        confidence=0.5,
        is_negotiable_or_irreversible=True,
    )
    assert fid2 > 0

    plan = application_plan_repo.get_plan(db_conn, user_id, plan_id)
    assert plan is not None
    assert plan["id"] == plan_id
    assert plan["job_id"] == "job_123"
    assert plan["status"] == "draft"
    assert len(plan["fields"]) == 2

    fields_by_name = {f["field_name"]: f for f in plan["fields"]}
    f1 = fields_by_name["skills"]
    assert f1["id"] == fid1
    assert f1["value"] == "Python expert"
    assert f1["is_grounded"] is True
    assert f1["confidence"] == pytest.approx(0.95)
    assert f1["is_negotiable_or_irreversible"] is False
    assert set(f1["fact_ids"]) == {fact_id1, fact_id2}

    f2 = fields_by_name["cover_letter_intro"]
    assert f2["id"] == fid2
    assert f2["value"] == "Hello team"
    assert f2["is_grounded"] is False
    assert f2["confidence"] == pytest.approx(0.5)
    assert f2["is_negotiable_or_irreversible"] is True
    assert f2["fact_ids"] == []


def test_re_upsert_field_replaces_facts_without_stale_links(db_conn, user):
    user_id = user["id"]
    _insert_job(db_conn, "job_test_replace")

    fact1 = candidate_facts_repo.insert(db_conn, user_id, "skill", "Go", source="manual")
    fact2 = candidate_facts_repo.insert(db_conn, user_id, "skill", "Rust", source="manual")
    fact3 = candidate_facts_repo.insert(db_conn, user_id, "skill", "Python", source="manual")

    plan_id = application_plan_repo.create_plan(db_conn, user_id, "job_test_replace")

    field_id_1 = application_plan_repo.upsert_field(
        db_conn,
        user_id,
        plan_id,
        "target_skill",
        "Go and Rust",
        fact_ids=[fact1, fact2],
    )

    plan = application_plan_repo.get_plan(db_conn, user_id, plan_id)
    assert len(plan["fields"]) == 1
    assert set(plan["fields"][0]["fact_ids"]) == {fact1, fact2}
    assert plan["fields"][0]["is_grounded"] is True

    # Re-upsert with different facts (only fact3)
    field_id_2 = application_plan_repo.upsert_field(
        db_conn,
        user_id,
        plan_id,
        "target_skill",
        "Python only",
        fact_ids=[fact3],
    )
    assert field_id_1 == field_id_2

    plan_after = application_plan_repo.get_plan(db_conn, user_id, plan_id)
    assert len(plan_after["fields"]) == 1
    f = plan_after["fields"][0]
    assert f["value"] == "Python only"
    assert f["fact_ids"] == [fact3]
    assert f["is_grounded"] is True

    # Re-upsert with empty facts -> is_grounded becomes False, no fact_ids left
    application_plan_repo.upsert_field(
        db_conn,
        user_id,
        plan_id,
        "target_skill",
        "No facts",
        fact_ids=[],
    )
    plan_empty = application_plan_repo.get_plan(db_conn, user_id, plan_id)
    assert plan_empty["fields"][0]["fact_ids"] == []
    assert plan_empty["fields"][0]["is_grounded"] is False


def test_mark_ready_transitions(db_conn, user):
    user_id = user["id"]
    _insert_job(db_conn, "job_ready")
    plan_id = application_plan_repo.create_plan(db_conn, user_id, "job_ready")

    # First mark_ready succeeds
    assert application_plan_repo.mark_ready(db_conn, user_id, plan_id) is True

    plan = application_plan_repo.get_plan(db_conn, user_id, plan_id)
    assert plan["status"] == "ready"

    # Second mark_ready returns False (cannot mark non-draft as ready)
    assert application_plan_repo.mark_ready(db_conn, user_id, plan_id) is False


def test_supersede_plan(db_conn, user):
    user_id = user["id"]
    _insert_job(db_conn, "job_s1")
    _insert_job(db_conn, "job_s2")

    # Supersede a draft plan
    p1 = application_plan_repo.create_plan(db_conn, user_id, "job_s1")
    assert application_plan_repo.supersede_plan(db_conn, user_id, p1) is True
    assert application_plan_repo.get_plan(db_conn, user_id, p1)["status"] == "superseded"

    # Supersede a ready plan
    p2 = application_plan_repo.create_plan(db_conn, user_id, "job_s2")
    assert application_plan_repo.mark_ready(db_conn, user_id, p2) is True
    assert application_plan_repo.supersede_plan(db_conn, user_id, p2) is True
    assert application_plan_repo.get_plan(db_conn, user_id, p2)["status"] == "superseded"


def test_list_plans_for_job(db_conn, user):
    user_id = user["id"]
    _insert_job(db_conn, "job_list")
    p1 = application_plan_repo.create_plan(db_conn, user_id, "job_list")
    p2 = application_plan_repo.create_plan(db_conn, user_id, "job_list")

    plans = application_plan_repo.list_plans_for_job(db_conn, user_id, "job_list")
    assert len(plans) == 2
    assert [p["id"] for p in plans] == [p2, p1]
    assert "fields" not in plans[0]


def test_autonomy_inputs_from_plan():
    base_kwargs = dict(
        match_confidence=0.88,
        employer_known=True,
        source="catalog",
        applications_sent_today=2,
    )

    # Empty fields list -> fields_fully_grounded True, has_irreversible_negotiable_fields False
    inputs_empty = autonomy_inputs_from_plan([], **base_kwargs)
    assert inputs_empty.fields_fully_grounded is True
    assert inputs_empty.has_irreversible_negotiable_fields is False

    # All fields grounded
    fields_all_grounded = [
        {"is_grounded": True, "is_negotiable_or_irreversible": False},
        {"is_grounded": True, "is_negotiable_or_irreversible": False},
    ]
    inputs_all = autonomy_inputs_from_plan(fields_all_grounded, **base_kwargs)
    assert inputs_all.fields_fully_grounded is True
    assert inputs_all.has_irreversible_negotiable_fields is False

    # One field not grounded
    fields_one_ungrounded = [
        {"is_grounded": True, "is_negotiable_or_irreversible": False},
        {"is_grounded": False, "is_negotiable_or_irreversible": False},
    ]
    inputs_ungrounded = autonomy_inputs_from_plan(fields_one_ungrounded, **base_kwargs)
    assert inputs_ungrounded.fields_fully_grounded is False

    # Any field irreversible/negotiable
    fields_with_irreversible = [
        {"is_grounded": True, "is_negotiable_or_irreversible": False},
        {"is_grounded": True, "is_negotiable_or_irreversible": True},
    ]
    inputs_irr = autonomy_inputs_from_plan(fields_with_irreversible, **base_kwargs)
    assert inputs_irr.has_irreversible_negotiable_fields is True

    # Missing overrides raises TypeError
    with pytest.raises(TypeError):
        autonomy_inputs_from_plan(fields_all_grounded)


def test_upsert_field_rejects_another_users_fact_id(db_conn, user, other_user):
    user_id = user["id"]
    other_id = other_user["id"]
    _insert_job(db_conn, "job_fact_isolation")

    other_fact_id = candidate_facts_repo.insert(
        db_conn, other_id, "skill", "Rust", source="manual"
    )
    plan_id = application_plan_repo.create_plan(db_conn, user_id, "job_fact_isolation")

    with pytest.raises(ValueError, match="not found or not owned"):
        application_plan_repo.upsert_field(
            db_conn, user_id, plan_id, "skills", "Rust expert", fact_ids=[other_fact_id]
        )


def test_cross_user_isolation_repo(db_conn, user, other_user):
    user_id = user["id"]
    other_id = other_user["id"]
    _insert_job(db_conn, "job_iso")

    plan_id = application_plan_repo.create_plan(db_conn, user_id, "job_iso")

    # other_user get_plan returns None
    assert application_plan_repo.get_plan(db_conn, other_id, plan_id) is None

    # other_user upsert_field raises ValueError
    with pytest.raises(ValueError, match="not found or not owned"):
        application_plan_repo.upsert_field(
            db_conn, other_id, plan_id, "field1", "val1"
        )

    # other_user mark_ready returns False
    assert application_plan_repo.mark_ready(db_conn, other_id, plan_id) is False

    # other_user supersede_plan returns False
    assert application_plan_repo.supersede_plan(db_conn, other_id, plan_id) is False

    # other_user list_plans_for_job returns empty list
    assert application_plan_repo.list_plans_for_job(db_conn, other_id, "job_iso") == []


def test_api_application_plans_crud_and_status(db_conn, logged_in_client, other_logged_in_client):
    _insert_job(db_conn, "job_api_1")

    # 1. Create plan
    resp = logged_in_client.post("/api/application-plans", json={"job_id": "job_api_1"})
    assert resp.status_code == 200, resp.text
    plan_data = resp.json()
    plan_id = plan_data["id"]
    assert plan_data["job_id"] == "job_api_1"
    assert plan_data["status"] == "draft"

    # 2. Get plan
    resp = logged_in_client.get(f"/api/application-plans/{plan_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == plan_id
    assert resp.json()["fields"] == []

    # 3. List plans for job
    resp = logged_in_client.get("/api/application-plans?job_id=job_api_1")
    assert resp.status_code == 200
    assert len(resp.json()) == 1

    # Missing job_id query param -> 400
    resp = logged_in_client.get("/api/application-plans")
    assert resp.status_code == 400

    # 4. Upsert field
    resp = logged_in_client.put(
        f"/api/application-plans/{plan_id}/fields/notice_period",
        json={"value": "1 month", "is_negotiable_or_irreversible": True},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    resp = logged_in_client.get(f"/api/application-plans/{plan_id}")
    assert len(resp.json()["fields"]) == 1
    assert resp.json()["fields"][0]["field_name"] == "notice_period"
    assert resp.json()["fields"][0]["is_negotiable_or_irreversible"] is True

    # 5. Mark ready
    resp = logged_in_client.patch(f"/api/application-plans/{plan_id}/ready")
    assert resp.status_code == 200

    # Mark ready again -> 409 Conflict
    resp = logged_in_client.patch(f"/api/application-plans/{plan_id}/ready")
    assert resp.status_code == 409

    # 6. Supersede
    resp = logged_in_client.patch(f"/api/application-plans/{plan_id}/supersede")
    assert resp.status_code == 200

    resp = logged_in_client.get(f"/api/application-plans/{plan_id}")
    assert resp.json()["status"] == "superseded"


def test_api_cross_user_isolation(db_conn, logged_in_client, other_logged_in_client):
    _insert_job(db_conn, "job_cross_user")

    resp = logged_in_client.post("/api/application-plans", json={"job_id": "job_cross_user"})
    plan_id = resp.json()["id"]

    # other user get_plan -> 404
    resp = other_logged_in_client.get(f"/api/application-plans/{plan_id}")
    assert resp.status_code == 404

    # other user upsert_field -> 404
    resp = other_logged_in_client.put(
        f"/api/application-plans/{plan_id}/fields/f1",
        json={"value": "v1"},
    )
    assert resp.status_code == 404

    # other user mark_ready -> 404
    resp = other_logged_in_client.patch(f"/api/application-plans/{plan_id}/ready")
    assert resp.status_code == 404

    # other user supersede -> 404
    resp = other_logged_in_client.patch(f"/api/application-plans/{plan_id}/supersede")
    assert resp.status_code == 404
