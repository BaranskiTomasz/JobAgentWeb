import uuid

import pytest

import application_plan_builder
import application_plan_repo
import cv_profiles_repo
from ats.greenhouse_schema import GreenhouseFormField


def _create(client, **overrides):
    token = uuid.uuid4().hex
    body = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": f"https://example.com/jobs/application-plan/{token}",
        "source": "greenhouse",
        "source_id": "acme:12345",
        "description": "Build things.",
        "search_query": "backend engineer",
    }
    body.update(overrides)
    response = client.post("/api/jobs", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _schema_with_resume():
    return [
        GreenhouseFormField(
            field_id="resume_text",
            label="Resume/CV",
            field_type="textarea",
            required=False,
            is_standard=True,
        ),
        GreenhouseFormField(
            field_id="question_123",
            label="Why this role?",
            field_type="textarea",
            required=True,
        ),
    ]


def test_build_plan_populates_resume_and_reports_missing_required_field(
    db_conn, user, logged_in_client, monkeypatch,
):
    job_id = _create(logged_in_client)["job_id"]
    raw_text = "Exact CV text\nwith original formatting."
    cv_profiles_repo.insert(db_conn, user["id"], "resume.txt", raw_text, {})
    db_conn.commit()
    monkeypatch.setattr(
        "ats.greenhouse_schema.fetch_job_schema",
        lambda slug, gh_job_id: _schema_with_resume(),
    )

    result = application_plan_builder.build_plan_for_job(db_conn, user["id"], job_id)

    plan = application_plan_repo.get_plan(db_conn, user["id"], result["plan_id"])
    assert plan["status"] == "draft"
    assert plan["fields"][0]["field_name"] == "resume_text"
    assert plan["fields"][0]["value"] == raw_text
    assert plan["fields"][0]["fact_ids"] == []
    assert plan["fields"][0]["is_grounded"] is False
    assert result == {
        "plan_id": result["plan_id"],
        "missing_required_fields": ["question_123"],
        "field_count": 2,
        "filled_count": 1,
    }


def test_non_greenhouse_job_creates_no_plan(db_conn, user, logged_in_client):
    job_id = _create(
        logged_in_client,
        source="linkedin",
        source_id="linkedin:12345",
    )["job_id"]

    with pytest.raises(ValueError, match="No ATS adapter for source 'linkedin'"):
        application_plan_builder.build_plan_for_job(db_conn, user["id"], job_id)

    assert application_plan_repo.list_plans_for_job(db_conn, user["id"], job_id) == []


def test_resume_schema_without_active_cv_creates_no_plan(
    db_conn, user, logged_in_client, monkeypatch,
):
    job_id = _create(logged_in_client)["job_id"]
    monkeypatch.setattr(
        "ats.greenhouse_schema.fetch_job_schema",
        lambda slug, gh_job_id: _schema_with_resume(),
    )

    with pytest.raises(
        ValueError, match="No active CV profile to populate resume_text from"
    ):
        application_plan_builder.build_plan_for_job(db_conn, user["id"], job_id)

    assert application_plan_repo.list_plans_for_job(db_conn, user["id"], job_id) == []


def test_schema_without_resume_succeeds_without_active_cv(
    db_conn, user, logged_in_client, monkeypatch,
):
    job_id = _create(logged_in_client)["job_id"]
    schema = [
        GreenhouseFormField(
            field_id="first_name",
            label="First Name",
            field_type="input_text",
            required=True,
            is_standard=True,
        )
    ]
    monkeypatch.setattr(
        "ats.greenhouse_schema.fetch_job_schema",
        lambda slug, gh_job_id: schema,
    )

    result = application_plan_builder.build_plan_for_job(db_conn, user["id"], job_id)

    assert result["missing_required_fields"] == ["first_name"]
    assert result["field_count"] == 1
    assert result["filled_count"] == 0
    assert application_plan_repo.get_plan(
        db_conn, user["id"], result["plan_id"]
    )["fields"] == []


def test_build_application_plan_api(
    db_conn,
    user,
    logged_in_client,
    other_logged_in_client,
    monkeypatch,
):
    greenhouse_job_id = _create(logged_in_client)["job_id"]
    cv_profiles_repo.insert(db_conn, user["id"], "resume.txt", "API CV", {})
    db_conn.commit()
    monkeypatch.setattr(
        "ats.greenhouse_schema.fetch_job_schema",
        lambda slug, gh_job_id: _schema_with_resume(),
    )

    not_owned = other_logged_in_client.post(
        f"/api/jobs/{greenhouse_job_id}/application-plan"
    )
    assert not_owned.status_code == 404

    success = logged_in_client.post(
        f"/api/jobs/{greenhouse_job_id}/application-plan"
    )
    assert success.status_code == 200, success.text
    assert set(success.json()) == {
        "plan_id",
        "missing_required_fields",
        "field_count",
        "filled_count",
    }
    assert success.json()["missing_required_fields"] == ["question_123"]
    assert success.json()["field_count"] == 2
    assert success.json()["filled_count"] == 1

    linkedin_job_id = _create(
        logged_in_client,
        source="linkedin",
        source_id="linkedin:67890",
    )["job_id"]
    unsupported = logged_in_client.post(
        f"/api/jobs/{linkedin_job_id}/application-plan"
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "No ATS adapter for source 'linkedin'"
