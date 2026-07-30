def _create(client, **overrides):
    body = {
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin", "description": "Build things.",
    }
    body.update(overrides)
    return client.post("/api/jobs", json=body).json()["job_id"]


def test_upsert_and_get_ids(logged_in_client):
    job_id = _create(logged_in_client)
    resp = logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.1, 0.2, 0.3], "model": "voyage-3-large"}],
    })
    assert resp.status_code == 200
    assert resp.json()["indexed"] == 1

    ids = logged_in_client.get("/api/embeddings/ids").json()["job_ids"]
    assert ids == [job_id]


def test_upsert_is_idempotent_replace(logged_in_client):
    job_id = _create(logged_in_client)
    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.1], "model": "voyage-3-large"}],
    })
    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.9], "model": "voyage-3-large"}],
    })
    vectors = logged_in_client.post("/api/embeddings/vectors", json={"job_ids": [job_id]}).json()
    assert vectors[job_id] == [0.9]


def test_unindexed_and_all_indexed(logged_in_client):
    with_desc = _create(logged_in_client, url="https://example.com/jobs/a")
    no_desc = _create(logged_in_client, url="https://example.com/jobs/b", description=None)

    unindexed = logged_in_client.get("/api/embeddings/unindexed").json()
    assert {j["id"] for j in unindexed} == {with_desc}  # no_desc excluded (no description)

    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": with_desc, "embedding": [0.1], "model": "voyage-3-large"}],
    })
    assert logged_in_client.get("/api/embeddings/unindexed").json() == []
    all_indexed = logged_in_client.get("/api/embeddings/all-indexed").json()
    assert [j["id"] for j in all_indexed] == [with_desc]


def test_embeddings_shared_across_users(logged_in_client, other_logged_in_client):
    job_id = _create(logged_in_client)
    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.5], "model": "voyage-3-large"}],
    })
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    # Second user's collector doesn't need to re-embed — the vector is already there.
    ids = other_logged_in_client.get("/api/embeddings/ids").json()["job_ids"]
    assert ids == [job_id]


def test_decision_vectors_scoped_per_user(logged_in_client, other_logged_in_client):
    job_id = _create(logged_in_client)
    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.7], "model": "voyage-3-large"}],
    })
    logged_in_client.patch(f"/api/jobs/{job_id}/status", json={"status": "applied"})

    mine = logged_in_client.get("/api/embeddings/decision-vectors").json()
    assert mine["applied"] == [[0.7]]
    assert mine["rejected"] == []

    theirs = other_logged_in_client.get("/api/embeddings/decision-vectors").json()
    assert theirs["applied"] == []


def test_requires_login(client):
    assert client.get("/api/embeddings/ids").status_code == 401
