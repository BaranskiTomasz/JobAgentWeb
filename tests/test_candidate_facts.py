import pytest

import candidate_facts_repo


def test_insert_and_get_all_and_active(db_conn, user):
    user_id = user["id"]

    id1 = candidate_facts_repo.insert(
        db_conn,
        user_id,
        "skill",
        "Python",
        source="manual",
    )
    id2 = candidate_facts_repo.insert(
        db_conn,
        user_id,
        "education",
        "BSc Computer Science",
        source="cv_upload",
        source_quote="Graduated in 2020",
        source_ref=42,
    )
    id3 = candidate_facts_repo.insert(
        db_conn,
        user_id,
        "skill",
        "PostgreSQL",
        source="questionnaire_free_text",
    )
    assert id1 > 0 and id2 > 0 and id3 > 0

    all_facts = candidate_facts_repo.get_all(db_conn, user_id)
    assert len(all_facts) == 3
    # Ordered by fact_type, created_at -> education comes before skill
    assert [f["id"] for f in all_facts] == [id2, id1, id3]

    # get_active with fact_type=None returns all active facts
    active_all = candidate_facts_repo.get_active(db_conn, user_id)
    assert [f["id"] for f in active_all] == [id2, id1, id3]

    # get_active with fact_type filter
    active_skills = candidate_facts_repo.get_active(db_conn, user_id, fact_type="skill")
    assert [f["id"] for f in active_skills] == [id1, id3]

    active_edu = candidate_facts_repo.get_active(db_conn, user_id, fact_type="education")
    assert [f["id"] for f in active_edu] == [id2]

    active_cert = candidate_facts_repo.get_active(db_conn, user_id, fact_type="certification")
    assert active_cert == []


def test_bulk_insert_atomic_and_ordered(db_conn, user):
    user_id = user["id"]
    facts = [
        {"fact_type": "work_experience", "value": "Senior Backend Dev at Acme", "source": "cv_upload", "source_quote": "2020-2024", "source_ref": 10},
        {"fact_type": "language", "value": "English C1", "source": "manual"},
        {"fact_type": "achievement", "value": "Reduced latency by 40%", "source": "questionnaire_free_text"},
    ]

    ids = candidate_facts_repo.bulk_insert(db_conn, user_id, facts)
    assert len(ids) == 3
    assert ids[0] < ids[1] < ids[2]

    rows = candidate_facts_repo.get_all(db_conn, user_id)
    assert len(rows) == 3

    # Test atomic failure: if any item is invalid, nothing is inserted
    invalid_batch = [
        {"fact_type": "certification", "value": "AWS Solutions Architect", "source": "manual"},
        {"fact_type": "invalid_type", "value": "Bogus", "source": "manual"},
    ]
    with pytest.raises(ValueError):
        candidate_facts_repo.bulk_insert(db_conn, user_id, invalid_batch)

    # Count of rows remains 3
    assert len(candidate_facts_repo.get_all(db_conn, user_id)) == 3


def test_repo_validates_fact_type_and_source(db_conn, user):
    user_id = user["id"]

    with pytest.raises(ValueError, match="Invalid fact_type"):
        candidate_facts_repo.insert(db_conn, user_id, "unknown_fact", "value", source="manual")

    with pytest.raises(ValueError, match="Invalid source"):
        candidate_facts_repo.insert(db_conn, user_id, "skill", "value", source="unknown_source")

    with pytest.raises(ValueError, match="Invalid fact_type"):
        candidate_facts_repo.bulk_insert(db_conn, user_id, [{"fact_type": "wrong", "value": "x", "source": "manual"}])

    with pytest.raises(ValueError, match="Invalid source"):
        candidate_facts_repo.bulk_insert(db_conn, user_id, [{"fact_type": "skill", "value": "x", "source": "wrong"}])


def test_deactivate_and_delete_differences(db_conn, user):
    user_id = user["id"]
    fact_id = candidate_facts_repo.insert(db_conn, user_id, "project", "Open source CLI", source="manual")

    assert len(candidate_facts_repo.get_active(db_conn, user_id)) == 1
    assert len(candidate_facts_repo.get_all(db_conn, user_id)) == 1

    # Soft deactivate
    ok = candidate_facts_repo.deactivate(db_conn, user_id, fact_id)
    assert ok is True

    # After deactivate: row still exists in get_all with is_active=0, but absent from get_active
    active = candidate_facts_repo.get_active(db_conn, user_id)
    assert len(active) == 0
    all_facts = candidate_facts_repo.get_all(db_conn, user_id)
    assert len(all_facts) == 1
    assert all_facts[0]["id"] == fact_id
    assert all_facts[0]["is_active"] == 0

    # Hard delete
    deleted = candidate_facts_repo.delete(db_conn, user_id, fact_id)
    assert deleted is True

    # After delete: completely gone from both get_active and get_all
    assert len(candidate_facts_repo.get_active(db_conn, user_id)) == 0
    assert len(candidate_facts_repo.get_all(db_conn, user_id)) == 0

    # Repeating delete returns False (rowcount == 0)
    assert candidate_facts_repo.delete(db_conn, user_id, fact_id) is False
    assert candidate_facts_repo.deactivate(db_conn, user_id, fact_id) is False


def test_deactivate_by_source(db_conn, user):
    user_id = user["id"]
    id1 = candidate_facts_repo.insert(db_conn, user_id, "skill", "Python", source="cv_upload", source_ref=10)
    id2 = candidate_facts_repo.insert(db_conn, user_id, "skill", "FastAPI", source="cv_upload", source_ref=10)
    id3 = candidate_facts_repo.insert(db_conn, user_id, "skill", "Docker", source="cv_upload", source_ref=20)
    id4 = candidate_facts_repo.insert(db_conn, user_id, "skill", "SQL", source="manual")

    # Deactivate cv_upload with source_ref=10
    count = candidate_facts_repo.deactivate_by_source(db_conn, user_id, "cv_upload", 10)
    assert count == 2

    active = candidate_facts_repo.get_active(db_conn, user_id)
    active_ids = {f["id"] for f in active}
    assert active_ids == {id3, id4}

    # Deactivate manual where source_ref is None
    count_manual = candidate_facts_repo.deactivate_by_source(db_conn, user_id, "manual", None)
    assert count_manual == 1

    active = candidate_facts_repo.get_active(db_conn, user_id)
    assert [f["id"] for f in active] == [id3]


def test_cross_user_isolation(db_conn, user, other_user):
    user_id = user["id"]
    other_id = other_user["id"]

    f1 = candidate_facts_repo.insert(db_conn, user_id, "skill", "User1 Skill", source="manual")
    f2 = candidate_facts_repo.insert(db_conn, other_id, "skill", "User2 Skill", source="manual")

    # User 1 facts list
    u1_facts = candidate_facts_repo.get_all(db_conn, user_id)
    assert [f["id"] for f in u1_facts] == [f1]

    # User 2 facts list
    u2_facts = candidate_facts_repo.get_all(db_conn, other_id)
    assert [f["id"] for f in u2_facts] == [f2]

    # User 2 cannot deactivate User 1's fact
    assert candidate_facts_repo.deactivate(db_conn, other_id, f1) is False
    assert len(candidate_facts_repo.get_active(db_conn, user_id)) == 1

    # User 2 cannot deactivate by source on User 1's records
    affected = candidate_facts_repo.deactivate_by_source(db_conn, other_id, "manual", None)
    assert affected == 1  # only deactivates User 2's own row (f2)
    assert len(candidate_facts_repo.get_active(db_conn, user_id)) == 1

    # User 2 cannot delete User 1's fact
    assert candidate_facts_repo.delete(db_conn, other_id, f1) is False
    assert len(candidate_facts_repo.get_all(db_conn, user_id)) == 1


def test_api_list_and_post_and_force_manual_source(logged_in_client):
    # POST forces source='manual' even if client sends source or source_quote/ref
    payload = {
        "fact_type": "work_experience",
        "value": "Led migration of monolith to microservices",
        "source": "cv_upload",
        "source_quote": "Led project from scratch",
        "source_ref": 999,
    }
    res = logged_in_client.post("/api/candidate-facts", json=payload)
    assert res.status_code == 200, res.text
    created = res.json()
    assert created["id"] > 0
    assert created["fact_type"] == "work_experience"
    assert created["value"] == "Led migration of monolith to microservices"
    assert created["source"] == "manual"
    assert created["source_quote"] is None
    assert created["source_ref"] is None
    assert created["is_active"] == 1
    assert created["created_at"] is not None

    # GET /api/candidate-facts default active_only=true
    res = logged_in_client.get("/api/candidate-facts")
    assert res.status_code == 200
    facts = res.json()
    assert len(facts) == 1
    assert facts[0]["id"] == created["id"]

    # Filter with fact_type
    res_filt = logged_in_client.get("/api/candidate-facts", params={"fact_type": "work_experience"})
    assert res_filt.status_code == 200
    assert len(res_filt.json()) == 1

    res_filt_none = logged_in_client.get("/api/candidate-facts", params={"fact_type": "skill"})
    assert res_filt_none.status_code == 200
    assert len(res_filt_none.json()) == 0


def test_api_post_rejects_invalid_fact_type(logged_in_client):
    res = logged_in_client.post(
        "/api/candidate-facts",
        json={"fact_type": "superpower", "value": "Telepathy"},
    )
    assert res.status_code == 422


def test_api_deactivate_and_delete_endpoints(logged_in_client):
    res = logged_in_client.post(
        "/api/candidate-facts",
        json={"fact_type": "skill", "value": "Rust"},
    )
    assert res.status_code == 200
    fact_id = res.json()["id"]

    # Soft deactivate
    res = logged_in_client.patch(f"/api/candidate-facts/{fact_id}/deactivate")
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # active_only=true (default) returns empty list
    res = logged_in_client.get("/api/candidate-facts")
    assert res.json() == []

    # active_only=false returns the deactivated fact
    res = logged_in_client.get("/api/candidate-facts", params={"active_only": False})
    facts = res.json()
    assert len(facts) == 1
    assert facts[0]["id"] == fact_id
    assert facts[0]["is_active"] == 0

    # Hard delete
    res = logged_in_client.delete(f"/api/candidate-facts/{fact_id}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    # get with active_only=false now returns empty list
    res = logged_in_client.get("/api/candidate-facts", params={"active_only": False})
    assert res.json() == []

    # Repeating delete returns 404
    res = logged_in_client.delete(f"/api/candidate-facts/{fact_id}")
    assert res.status_code == 404

    # Repeating deactivate returns 404
    res = logged_in_client.patch(f"/api/candidate-facts/{fact_id}/deactivate")
    assert res.status_code == 404


def test_api_cross_user_isolation_returns_404(logged_in_client, other_logged_in_client):
    res = logged_in_client.post(
        "/api/candidate-facts",
        json={"fact_type": "certification", "value": "CKA"},
    )
    assert res.status_code == 200
    fact_id = res.json()["id"]

    # Other user does not see it
    res = other_logged_in_client.get("/api/candidate-facts", params={"active_only": False})
    assert res.json() == []

    # Other user attempting PATCH deactivate returns 404
    res = other_logged_in_client.patch(f"/api/candidate-facts/{fact_id}/deactivate")
    assert res.status_code == 404

    # Other user attempting DELETE returns 404
    res = other_logged_in_client.delete(f"/api/candidate-facts/{fact_id}")
    assert res.status_code == 404
