import pytest

import cv_fact_extractor


@pytest.fixture(autouse=True)
def _mock_cv_fact_extraction(monkeypatch):
    monkeypatch.setattr(cv_fact_extractor, "extract_facts_from_cv", lambda text: [])


def test_create_and_get_active(logged_in_client):
    resp = logged_in_client.post("/api/cv-profiles", json={
        "filename": "cv.pdf", "raw_text": "Experienced engineer.", "parsed": {"skills": ["Python"]},
    })
    assert resp.status_code == 200
    profile_id = resp.json()["id"]

    active = logged_in_client.get("/api/cv-profiles/active")
    assert active.status_code == 200
    assert active.json()["id"] == profile_id
    assert active.json()["parsed"] == {"skills": ["Python"]}


def test_new_upload_deactivates_previous(logged_in_client):
    first = logged_in_client.post("/api/cv-profiles", json={
        "filename": "a.pdf", "raw_text": "A", "parsed": {},
    }).json()["id"]
    second = logged_in_client.post("/api/cv-profiles", json={
        "filename": "b.pdf", "raw_text": "B", "parsed": {},
    }).json()["id"]

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == second

    all_profiles = logged_in_client.get("/api/cv-profiles").json()
    assert len(all_profiles) == 2

    logged_in_client.post(f"/api/cv-profiles/{first}/activate")
    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == first


def test_no_active_profile_404(logged_in_client):
    resp = logged_in_client.get("/api/cv-profiles/active")
    assert resp.status_code == 404


def test_activate_nonexistent_profile_404s_and_leaves_active_untouched(logged_in_client):
    # Regression: set_active() used to deactivate the current row before
    # checking whether the target id existed, leaving zero active profiles.
    profile_id = logged_in_client.post("/api/cv-profiles", json={
        "filename": "a.pdf", "raw_text": "A", "parsed": {},
    }).json()["id"]

    resp = logged_in_client.post("/api/cv-profiles/999999/activate")
    assert resp.status_code == 404

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == profile_id


def test_activate_another_users_profile_404s_and_leaves_active_untouched(logged_in_client, other_logged_in_client):
    mine = logged_in_client.post("/api/cv-profiles", json={
        "filename": "mine.pdf", "raw_text": "Mine", "parsed": {},
    }).json()["id"]
    theirs = other_logged_in_client.post("/api/cv-profiles", json={
        "filename": "theirs.pdf", "raw_text": "Theirs", "parsed": {},
    }).json()["id"]

    resp = logged_in_client.post(f"/api/cv-profiles/{theirs}/activate")
    assert resp.status_code == 404

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == mine


def test_cv_profiles_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/cv-profiles", json={"filename": "a.pdf", "raw_text": "A", "parsed": {}})
    assert other_logged_in_client.get("/api/cv-profiles").json() == []
    assert other_logged_in_client.get("/api/cv-profiles/active").status_code == 404


def test_requires_login(client):
    assert client.get("/api/cv-profiles").status_code == 401


def test_upload_extracts_and_stores_candidate_facts(logged_in_client, monkeypatch):
    mocked_facts = [
        {
            "fact_type": "work_experience",
            "value": "Backend Engineer at Globex, 2021-2024.",
            "source_quote": "Globex - Backend Engineer (2021-2024)",
        },
        {
            "fact_type": "skill",
            "value": "Proficient in Python.",
            "source_quote": "Python",
        },
    ]
    monkeypatch.setattr("cv_fact_extractor.extract_facts_from_cv", lambda text: mocked_facts)

    resp = logged_in_client.post("/api/cv-profiles", json={
        "filename": "cv1.pdf",
        "raw_text": "Globex - Backend Engineer (2021-2024). Python.",
        "parsed": {},
    })
    assert resp.status_code == 200
    profile_id = resp.json()["id"]

    facts_resp = logged_in_client.get("/api/candidate-facts?active_only=false")
    assert facts_resp.status_code == 200
    facts = facts_resp.json()
    assert len(facts) == 2
    for fact in facts:
        assert fact["source"] == "cv_upload"
        assert fact["source_ref"] == profile_id
        assert fact["is_active"] == 1


def test_second_cv_upload_deactivates_first_cv_facts(logged_in_client, monkeypatch):
    first_facts = [
        {
            "fact_type": "work_experience",
            "value": "Engineer at Alpha, 2018-2020.",
            "source_quote": "Alpha Engineer",
        },
    ]
    second_facts = [
        {
            "fact_type": "work_experience",
            "value": "Senior Engineer at Beta, 2020-2023.",
            "source_quote": "Beta Senior Engineer",
        },
        {
            "fact_type": "skill",
            "value": "Expert in Go.",
            "source_quote": "Go",
        },
    ]

    extraction_results = [first_facts, second_facts]
    monkeypatch.setattr(
        "cv_fact_extractor.extract_facts_from_cv",
        lambda text: extraction_results.pop(0),
    )

    resp1 = logged_in_client.post("/api/cv-profiles", json={
        "filename": "first.pdf", "raw_text": "Alpha Engineer", "parsed": {},
    })
    assert resp1.status_code == 200
    profile1_id = resp1.json()["id"]

    resp2 = logged_in_client.post("/api/cv-profiles", json={
        "filename": "second.pdf", "raw_text": "Beta Senior Engineer Go", "parsed": {},
    })
    assert resp2.status_code == 200
    profile2_id = resp2.json()["id"]

    all_facts_resp = logged_in_client.get("/api/candidate-facts?active_only=false")
    assert all_facts_resp.status_code == 200
    all_facts = all_facts_resp.json()

    p1_facts = [f for f in all_facts if f["source_ref"] == profile1_id]
    p2_facts = [f for f in all_facts if f["source_ref"] == profile2_id]

    assert len(p1_facts) == 1
    assert p1_facts[0]["is_active"] == 0
    assert p1_facts[0]["value"] == "Engineer at Alpha, 2018-2020."

    assert len(p2_facts) == 2
    for f in p2_facts:
        assert f["is_active"] == 1

    active_facts_resp = logged_in_client.get("/api/candidate-facts?active_only=true")
    assert active_facts_resp.status_code == 200
    active_facts = active_facts_resp.json()
    assert len(active_facts) == 2
    assert all(f["source_ref"] == profile2_id for f in active_facts)


def test_fact_extraction_failure_does_not_fail_cv_upload(logged_in_client, monkeypatch):
    def _failing_extract(text):
        raise RuntimeError("Claude extraction service unavailable")

    monkeypatch.setattr("cv_fact_extractor.extract_facts_from_cv", _failing_extract)

    resp = logged_in_client.post("/api/cv-profiles", json={
        "filename": "fail.pdf",
        "raw_text": "Some text",
        "parsed": {},
    })
    assert resp.status_code == 200
    assert "id" in resp.json()
