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


def test_classifier_uses_explicit_v2_country_eligibility():
    result = classify_catalog_job({
        "title": "QA Engineer",
        "description": "Build automated browser tests.",
        "location": "Remote",
        "structured_data": {
            "remote": True,
            "skills": [{"canonical_name": "playwright", "original_name": "Playwright"}],
            "country_eligibility": [{"country_code": "PL", "eligible": True}],
        },
    })
    assert result["technologies"] == ["qa"]
    assert result["work_countries"] == ["PL"]
    assert result["is_public"] is True


def test_classifier_excludes_hybrid_even_when_source_also_marks_remote():
    result = classify_catalog_job({
        "title": "Python Developer",
        "description": "Work remotely with two required office days per month.",
        "location": "Warsaw, Poland (Hybrid)",
        "source_structured_data": {
            "remote": True,
            "remote_regions": ["Poland"],
        },
        "structured_data": {"remote": True, "hybrid": True},
    })
    assert result["work_countries"] == []
    assert result["is_public"] is False


def test_classifier_does_not_confuse_hybrid_cloud_with_hybrid_work():
    result = classify_catalog_job({
        "title": "Python Developer",
        "description": "Build Python services on a hybrid cloud platform for an EMEA team.",
        "location": "EMEA (Remote)",
        "source_structured_data": {"remote": True, "remote_regions": ["EMEA"]},
    })
    assert result["work_countries"] == ["BG", "PL"]
    assert result["is_public"] is True


def test_classifier_does_not_infer_country_when_structured_eligibility_denies_it():
    result = classify_catalog_job({
        "title": "Python Developer",
        "description": "Remote role for a distributed engineering team.",
        "location": "Remote",
        "source_structured_data": {"remote": True, "remote_regions": ["Europe"]},
        "structured_data": {
            "remote": True,
            "country_eligibility": [{"country_code": "PL", "eligible": False}],
        },
    })
    assert result["work_countries"] == ["BG"]
    assert result["is_public"] is True


def test_classifier_requires_explicit_full_remote_signal():
    result = classify_catalog_job({
        "title": "Python Developer",
        "description": "Remote-friendly role based in Poland.",
        "location": "Poland",
    })
    assert result["work_countries"] == []
    assert result["is_public"] is False


def test_public_catalog_is_available_without_account(client, logged_in_client):
    job_id = _create_catalog_job(logged_in_client)
    response = client.get("/api/public/jobs", params={"technology": "python", "country": "PL"})
    assert response.status_code == 200
    assert [job["id"] for job in response.json()] == [job_id]
    assert response.json()[0]["description"].startswith("Build a remote Python")
    assert "structured_data" in response.json()[0]
    assert "score" not in response.json()[0]


def test_public_search_filters_extracted_facts(client, logged_in_client, db_conn):
    job_id = _create_catalog_job(logged_in_client)
    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO job_fact_extractions
               (job_id, schema_version, model, content_hash, facts)
           VALUES (%s, 4, 'test', 'hash', %s::jsonb)""",
        (job_id, """{
            "summary": "Build payment services with Python.",
            "seniority": "senior", "role_family": "backend",
            "company_type": "scaleup", "industry": "fintech",
            "working_language": "english", "timezone_requirement": "CET",
            "contract_types": ["b2b"], "on_call": false,
            "skills": [{"canonical_name": "python", "original_name": "Python",
                "requirement": "required", "importance": "core", "min_years": 3,
                "confidence": 0.9, "evidence": "Python required"}],
            "compensation_bands": [{"amount_min": 100, "amount_max": 140,
                "currency": "PLN", "period": "hourly", "tax_basis": "net",
                "compensation_type": "base", "contract_type": "b2b",
                "country_code": "PL", "confidence": 0.9, "evidence": "100-140 PLN/h"}]
        }"""),
    )
    cur.execute(
        """INSERT INTO job_skills
               (job_id, canonical_name, original_name, requirement, importance, min_years, confidence, evidence)
           VALUES (%s, 'python', 'Python', 'required', 'core', 3, .9, 'Python required')""",
        (job_id,),
    )
    cur.execute(
        """INSERT INTO job_compensation_bands
               (job_id, amount_min, amount_max, currency, period, tax_basis,
                compensation_type, contract_type, country_code, confidence, evidence)
           VALUES (%s, 100, 140, 'PLN', 'hourly', 'net', 'base', 'b2b', 'PL', .9, '100-140 PLN/h')""",
        (job_id,),
    )
    cur.execute(
        """INSERT INTO job_eligibility
               (job_id, country_code, eligible, confidence, engagement_modes, evidence)
           VALUES (%s, 'PL', TRUE, .9, ARRAY['b2b'], 'Remote from Poland')""",
        (job_id,),
    )
    db_conn.commit()

    response = client.get("/api/public/jobs/search", params={
        "technology": "python", "country": "PL", "skill": "python",
        "company": "Acme", "seniority": "senior", "role_family": "backend",
        "contract_type": "b2b", "currency": "PLN", "salary_min": 120,
        "salary_period": "hourly",
        "working_language": "english", "timezone": "CET",
        "company_type": "scaleup", "industry": "fintech", "on_call": False,
    })

    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert result["items"][0]["id"] == job_id
    assert result["items"][0]["eligibility_evidence"] == "Remote from Poland"
    assert result["items"][0]["engagement_modes"] == ["b2b"]

    no_match = client.get("/api/public/jobs/search", params={
        "technology": "python", "country": "PL", "salary_min": 200,
    })
    assert no_match.json()["total"] == 0


def test_public_filter_options_are_scoped_to_category(client, logged_in_client, db_conn):
    job_id = _create_catalog_job(logged_in_client, source="jobicy")
    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO job_fact_extractions
               (job_id, schema_version, model, content_hash, facts)
           VALUES (%s, 4, 'test', 'hash', '{"industry":"fintech"}'::jsonb)""",
        (job_id,),
    )
    cur.execute(
        """INSERT INTO job_skills
               (job_id, canonical_name, original_name, requirement, importance, confidence)
           VALUES (%s, 'python', 'Python', 'required', 'core', .9)""",
        (job_id,),
    )
    db_conn.commit()

    response = client.get("/api/public/jobs/filter-options", params={"technology": "python", "country": "PL"})

    assert response.status_code == 200
    assert "Acme" in response.json()["companies"]
    assert "jobicy" in response.json()["sources"]
    assert "python" in response.json()["skills"]
    assert "fintech" in response.json()["industries"]


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
    assert "React jobs" in response.text
    assert "More filters" in response.text
    assert "Minimum listed compensation" in response.text


def test_qa_catalog_page_is_available_without_account(client):
    response = client.get("/jobs/qa")
    assert response.status_code == 200
    assert "QA jobs" in response.text
