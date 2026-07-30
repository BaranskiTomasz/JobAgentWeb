def _create_job(client, **overrides):
    body = {
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin", "description": "Build things.",
    }
    body.update(overrides)
    return client.post("/api/jobs", json=body).json()["job_id"]


def test_dismiss_and_get_for_job(logged_in_client):
    job_id = _create_job(logged_in_client)
    resp = logged_in_client.post(f"/api/jobs/{job_id}/dismiss-item", json={
        "item_type": "con", "item_text": "Timezone mismatch", "reason": "I work async anyway",
    })
    assert resp.status_code == 200

    items = logged_in_client.get(f"/api/jobs/{job_id}/dismissed-items").json()["items"]
    assert len(items) == 1
    assert items[0]["item_text"] == "Timezone mismatch"


def test_dismiss_unknown_job_404(logged_in_client):
    resp = logged_in_client.post("/api/jobs/doesnotexist/dismiss-item", json={
        "item_type": "con", "item_text": "x", "reason": "y",
    })
    assert resp.status_code == 404


def test_recent_and_count(logged_in_client):
    job_id = _create_job(logged_in_client)
    logged_in_client.post(f"/api/jobs/{job_id}/dismiss-item", json={
        "item_type": "pro", "item_text": "Great salary", "reason": "not a priority for me",
    })
    recent = logged_in_client.get("/api/dismissed-items/recent").json()
    assert len(recent) == 1
    assert recent[0]["title"] == "Backend Engineer"

    count = logged_in_client.get("/api/dismissed-items/count").json()["count"]
    assert count == 1


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    job_id = _create_job(logged_in_client)
    logged_in_client.post(f"/api/jobs/{job_id}/dismiss-item", json={
        "item_type": "con", "item_text": "x", "reason": "y",
    })
    assert other_logged_in_client.get("/api/dismissed-items/count").json()["count"] == 0
