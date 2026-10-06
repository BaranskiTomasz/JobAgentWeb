from catalog import classify_catalog_job


def _create_catalog_job(client, **overrides):
    body = {
        "title": "Senior Python Developer",
        "company": "Acme",
        "location": "Poland (Remote)",
        "url": "https://example.com/catalog/python-1",
        "source": "linkedin",
        "description": "Build a remote Python and FastAPI product for customers across Europe.",
        "source_structured_data": {"remote": True, "remote_regions": ["Poland"]},
    }
    body.update(overrides)
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200
    return response.json()["job_id"]


def test_classifier_maps_european_remote_job_to_both_countries():
    result = classify_catalog_job({
        "title": "React Developer",
        "description": "Remote anywhere in EMEA",
        "location": "EMEA (Remote)",
        "source_structured_data": {"remote": True, "remote_regions": ["EMEA"]},
    })
    assert result["technologies"] == ["react"]
    assert result["work_countries"] == ["BG", "PL"]
    assert result["is_public"] is True


def test_classifier_maps_quality_assurance_roles_to_qa():
    result = classify_catalog_job({
        "title": "Senior QA Automation Engineer",
        "description": "Quality assurance with Playwright for a worldwide remote team.",
        "location": "Worldwide (Remote)",
        "source_structured_data": {"remote": True, "remote_regions": ["Worldwide"]},
    })
    assert result["technologies"] == ["qa"]
    assert result["work_countries"] == ["BG", "PL"]
    assert result["is_public"] is True


def test_classifier_does_not_map_engineering_role_from_incidental_qa_mention():
    result = classify_catalog_job({
        "title": "Senior Python Developer",
        "description": "Work with QA teams and improve automated quality checks.",
        "location": "Poland (Remote)",
        "source_structured_data": {"remote": True, "remote_regions": ["Poland"]},
    })
    assert result["technologies"] == ["python"]


def test_classifier_does_not_publish_us_only_job():
    result = classify_catalog_job({
        "title": "Python Developer",
        "description": "Remote role for US residents only",
        "location": "United States (Remote)",
        "source_structured_data": {"remote": True, "remote_regions": ["United States"]},
    })
    assert result["work_countries"] == []
    assert result["is_public"] is False


def test_classifier_uses_cross_source_alias_eligibility():
    result = classify_catalog_job({
        "title": "Node.js Developer",
        "description": "Build backend services with Node.js.",
        "location": "Remote",
        "alias_metadata": [{
            "search_query": "Node.js Developer",
            "source_structured_data": {"remote": True, "remote_regions": ["Bulgaria"]},
        }],
    })
    assert result["work_countries"] == ["BG"]
    assert result["eligibility_confidence"] == "high"
    assert result["is_public"] is True


def test_public_catalog_is_available_without_account(client, logged_in_client):
    job_id = _create_catalog_job(logged_in_client)
    response = client.get("/api/public/jobs", params={"technology": "python", "country": "PL"})
    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == [job_id]
    assert "description" not in response.json()[0]
    assert "score" not in response.json()[0]


def test_country_filter_keeps_poland_only_job_out_of_bulgaria(client, logged_in_client):
    _create_catalog_job(logged_in_client)
    response = client.get("/api/public/jobs", params={"technology": "python", "country": "BG"})
    assert response.json() == []


def test_personalize_attaches_shared_posting_to_second_user(logged_in_client, other_logged_in_client):
    job_id = _create_catalog_job(logged_in_client)
    before = other_logged_in_client.get("/api/jobs").json()
    assert before == []

    first = other_logged_in_client.post(
        "/api/public/jobs/personalize", json={"technology": "python", "country": "PL"},
    )
    second = other_logged_in_client.post(
        "/api/public/jobs/personalize", json={"technology": "python", "country": "PL"},
    )

    assert first.status_code == 200
    assert first.json() == {"attached": 1}
    assert second.json() == {"attached": 0}
    jobs = other_logged_in_client.get("/api/jobs").json()
    assert [job["id"] for job in jobs] == [job_id]
    assert jobs[0]["score"] is None


def test_personalize_requires_account(client):
    response = client.post(
        "/api/public/jobs/personalize", json={"technology": "python", "country": "PL"},
    )
    assert response.status_code == 401


def test_public_catalog_page_is_available_without_account(client):
    response = client.get("/jobs/react")
    assert response.status_code == 200
    assert "Oferty React" in response.text


def test_qa_catalog_page_is_available_without_account(client):
    response = client.get("/jobs/qa")
    assert response.status_code == 200
    assert "Oferty QA" in response.text
