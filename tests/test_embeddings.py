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
    # get_unindexed/get_all_indexed are deliberately unscoped (embeddings are a
    # property of the shared posting, not per-user) and job_postings is never
    # truncated between tests — assert membership, not exact set equality,
    # since other tests may leave their own unrelated unembedded jobs behind.
    with_desc = _create(logged_in_client, url="https://example.com/jobs/a")
    no_desc = _create(logged_in_client, url="https://example.com/jobs/b", description=None)

    unindexed_ids = {j["id"] for j in logged_in_client.get("/api/embeddings/unindexed").json()}
    assert with_desc in unindexed_ids
    assert no_desc not in unindexed_ids  # no description

    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": with_desc, "embedding": [0.1], "model": "voyage-3-large"}],
    })
    unindexed_ids = {j["id"] for j in logged_in_client.get("/api/embeddings/unindexed").json()}
    assert with_desc not in unindexed_ids

    all_indexed_ids = {j["id"] for j in logged_in_client.get("/api/embeddings/all-indexed").json()}
    assert with_desc in all_indexed_ids
    assert no_desc not in all_indexed_ids


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


def test_decision_vectors_capped_to_most_recent(logged_in_client):
    # Regression: an unbounded, unweighted centroid means a decision from a year
    # ago counts exactly as much as yesterday's — old decisions never age out.
    # 55 applied jobs, decided in order — only the 50 most recent should come back.
    from embeddings_repo import _DECISION_VECTOR_LIMIT
    total = _DECISION_VECTOR_LIMIT + 5
    for i in range(total):
        job_id = _create(logged_in_client, url=f"https://example.com/jobs/decision-vec-{i}")
        logged_in_client.post("/api/embeddings", json={
            "items": [{"job_id": job_id, "embedding": [float(i)], "model": "voyage-3-large"}],
        })
        logged_in_client.patch(f"/api/jobs/{job_id}/status", json={"status": "applied"})

    applied = logged_in_client.get("/api/embeddings/decision-vectors").json()["applied"]
    assert len(applied) == _DECISION_VECTOR_LIMIT
    values = {v[0] for v in applied}
    # Most recent _DECISION_VECTOR_LIMIT (highest i, decided last) must be kept,
    # the oldest (lowest i) dropped.
    assert values == set(float(i) for i in range(5, total))


def test_requires_login(client):
    assert client.get("/api/embeddings/ids").status_code == 401


def test_similarity_computed_server_side(logged_in_client):
    # Regression: the old flow shipped raw vectors over HTTP for the caller to
    # score itself — a 1024-dim vector is ~22 KB of JSON, tens of MB at a
    # couple thousand jobs. /similarity returns only the reduced {job_id: score}.
    identical = _create(logged_in_client, url="https://example.com/jobs/sim-identical")
    orthogonal = _create(logged_in_client, url="https://example.com/jobs/sim-orthogonal")
    opposite = _create(logged_in_client, url="https://example.com/jobs/sim-opposite")
    logged_in_client.post("/api/embeddings", json={"items": [
        {"job_id": identical, "embedding": [1.0, 0.0], "model": "voyage-3-large"},
        {"job_id": orthogonal, "embedding": [0.0, 1.0], "model": "voyage-3-large"},
        {"job_id": opposite, "embedding": [-1.0, 0.0], "model": "voyage-3-large"},
    ]})

    resp = logged_in_client.post("/api/embeddings/similarity", json={
        "ideal": [1.0, 0.0], "job_ids": [identical, orthogonal, opposite],
    })
    assert resp.status_code == 200
    scores = resp.json()
    assert scores[identical] == 1.0
    assert scores[orthogonal] == 0.0
    assert scores[opposite] == -1.0
    # The point of the endpoint: raw vectors never come back, only scores.
    assert "embedding" not in resp.text and "1024" not in resp.text


def test_similarity_empty_job_ids_returns_empty(logged_in_client):
    resp = logged_in_client.post("/api/embeddings/similarity", json={"ideal": [1.0, 0.0], "job_ids": []})
    assert resp.json() == {}


def test_similarity_zero_vector_scores_zero_not_nan(logged_in_client):
    job_id = _create(logged_in_client, url="https://example.com/jobs/sim-zero")
    logged_in_client.post("/api/embeddings", json={
        "items": [{"job_id": job_id, "embedding": [0.0, 0.0], "model": "voyage-3-large"}],
    })
    resp = logged_in_client.post("/api/embeddings/similarity", json={"ideal": [1.0, 0.0], "job_ids": [job_id]})
    assert resp.json()[job_id] == 0.0


def test_similarity_batch_matches_each_job_to_its_own_score(logged_in_client):
    # Regression guard for the numpy rewrite: scoring is now one matrix op over
    # every vector at once instead of a per-row Python loop — confirms results
    # still line up with the right job_id after batching, not just for N=1..3.
    jobs = []
    for i in range(12):
        job_id = _create(logged_in_client, url=f"https://example.com/jobs/sim-batch-{i}")
        # Each vector's similarity to [1.0, 0.0] should be exactly i / 11 by construction.
        logged_in_client.post("/api/embeddings", json={
            "items": [{"job_id": job_id, "embedding": [i / 11, 1 - i / 11], "model": "voyage-3-large"}],
        })
        jobs.append(job_id)

    resp = logged_in_client.post("/api/embeddings/similarity", json={
        "ideal": [1.0, 0.0], "job_ids": jobs,
    })
    scores = resp.json()
    assert len(scores) == 12
    ordered = sorted(jobs, key=lambda j: scores[j])
    assert ordered == jobs  # increasing i => increasing similarity, in insertion order
