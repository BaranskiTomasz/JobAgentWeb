import uuid

import dedup_repo


def _create(client, **overrides):
    body = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": "https://example.com/jobs/application-events",
        "source": "linkedin",
        "description": "Build things.",
        "search_query": "backend engineer",
    }
    body.update(overrides)
    return client.post("/api/jobs", json=body).json()


def test_create_and_list_application_event(logged_in_client):
    job_id = _create(logged_in_client)["job_id"]

    response = logged_in_client.post(
        f"/api/jobs/{job_id}/events",
        json={"event_type": "screening", "note": "Recruiter call"},
    )

    assert response.status_code in (200, 201)
    event = response.json()
    assert event["event_type"] == "screening"
    assert event["job_id"] == job_id
    assert logged_in_client.get(f"/api/jobs/{job_id}/events").json() == [event]


def test_create_application_event_rejects_invalid_type(logged_in_client):
    job_id = _create(logged_in_client, url="https://example.com/jobs/invalid-event")["job_id"]

    response = logged_in_client.post(
        f"/api/jobs/{job_id}/events",
        json={"event_type": "hired"},
    )

    assert response.status_code == 422


def test_create_application_event_returns_404_for_unknown_job(logged_in_client):
    response = logged_in_client.post(
        "/api/jobs/missing-job/events",
        json={"event_type": "response"},
    )

    assert response.status_code == 404


def test_application_events_are_isolated_per_user(logged_in_client, other_logged_in_client):
    url = "https://example.com/jobs/shared-application-events"
    job_id = _create(logged_in_client, url=url)["job_id"]
    _create(other_logged_in_client, url=url)
    response = logged_in_client.post(
        f"/api/jobs/{job_id}/events",
        json={"event_type": "offer"},
    )
    assert response.status_code in (200, 201)

    assert other_logged_in_client.get(f"/api/jobs/{job_id}/events").json() == []


def test_application_event_respects_explicit_occurred_at(logged_in_client):
    job_id = _create(logged_in_client, url="https://example.com/jobs/explicit-event-time")["job_id"]
    occurred_at = "2026-01-02T03:04:05"

    response = logged_in_client.post(
        f"/api/jobs/{job_id}/events",
        json={"event_type": "interview_scheduled", "occurred_at": occurred_at},
    )

    assert response.status_code in (200, 201)
    assert response.json()["occurred_at"] == occurred_at


def test_application_event_defaults_occurred_at(logged_in_client):
    job_id = _create(logged_in_client, url="https://example.com/jobs/default-event-time")["job_id"]

    response = logged_in_client.post(
        f"/api/jobs/{job_id}/events",
        json={"event_type": "response"},
    )

    assert response.status_code in (200, 201)
    assert response.json()["occurred_at"] is not None


def test_application_event_survives_dedup_merge(logged_in_client, db_conn):
    # Regression: job_application_events used to FK against user_job_states
    # (whose job_id column dedup_repo.merge_jobs mutates/deletes in place),
    # which either aborted the merge transaction or silently cascade-deleted
    # the user's recorded funnel history for the merged-away posting.
    token = uuid.uuid4().hex
    survivor = _create(
        logged_in_client, source="jobicy", url=f"https://jobicy.example/{token}",
        company=f"Acme {token}", description="Role one.",
    )
    loser = _create(
        logged_in_client, source="remotive", url=f"https://remotive.example/{token}",
        company=f"Globex {token}", description="Role two.",
    )
    assert survivor["job_id"] != loser["job_id"]

    response = logged_in_client.post(
        f"/api/jobs/{loser['job_id']}/events",
        json={"event_type": "interview_scheduled", "note": "Recorded before the merge"},
    )
    assert response.status_code in (200, 201)

    result = dedup_repo.merge_jobs(
        db_conn, survivor["job_id"], loser["job_id"],
        survivor_job_id=survivor["job_id"], match_method="manual_merge", confidence=1.0,
    )
    db_conn.commit()
    assert result["survivor_job_id"] == survivor["job_id"]

    events = logged_in_client.get(f"/api/jobs/{survivor['job_id']}/events").json()
    assert [event["event_type"] for event in events] == ["interview_scheduled"]
