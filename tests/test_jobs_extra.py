def _create(client, **overrides):
    body = {
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin", "description": "Build things.",
        "search_query": "backend engineer",
    }
    body.update(overrides)
    return client.post("/api/jobs", json=body).json()


def test_get_all_urls_is_scoped_to_the_caller(logged_in_client, other_logged_in_client):
    # Regression: this used to be system-wide, which meant most collector
    # sources (skip-if-known-url) silently never even tried to insert a
    # posting another user had already found — the shared pool never got
    # shared. Each user's known-urls set must reflect only their own state.
    _create(logged_in_client, url="https://example.com/jobs/a")
    _create(other_logged_in_client, url="https://example.com/jobs/b")

    assert logged_in_client.get("/api/jobs/urls").json()["urls"] == ["https://example.com/jobs/a"]
    assert other_logged_in_client.get("/api/jobs/urls").json()["urls"] == ["https://example.com/jobs/b"]


def test_get_all_urls_includes_a_shared_posting_once_this_user_links_it(logged_in_client, other_logged_in_client):
    _create(logged_in_client, url="https://example.com/jobs/shared")
    assert other_logged_in_client.get("/api/jobs/urls").json()["urls"] == []

    # Second user reuses the same posting — insert() links it to their own state.
    _create(other_logged_in_client, url="https://example.com/jobs/shared")
    assert other_logged_in_client.get("/api/jobs/urls").json()["urls"] == ["https://example.com/jobs/shared"]


def test_missing_descriptions(logged_in_client):
    job_id = _create(logged_in_client, description=None)["job_id"]
    missing = logged_in_client.get("/api/jobs/missing-descriptions").json()
    assert len(missing) == 1
    assert missing[0]["id"] == job_id

    logged_in_client.patch(f"/api/jobs/{job_id}/description", json={"description": "Now has one."})
    assert logged_in_client.get("/api/jobs/missing-descriptions").json() == []
    assert logged_in_client.get(f"/api/jobs/{job_id}").json()["description"] == "Now has one."


def test_update_description_is_shared(logged_in_client, other_logged_in_client):
    job_id = _create(logged_in_client, description=None)["job_id"]
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    logged_in_client.patch(f"/api/jobs/{job_id}/description", json={"description": "Shared text."})
    theirs = other_logged_in_client.get(f"/api/jobs/{job_id}").json()
    assert theirs["description"] == "Shared text."


def test_update_description_is_write_once(logged_in_client, other_logged_in_client):
    # Regression: any user who links to a shared posting could otherwise
    # overwrite its description at will, corrupting it for every other user
    # who's found the same URL — with no ownership check at all.
    job_id = _create(logged_in_client, description="Original text.")["job_id"]
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    other_logged_in_client.patch(f"/api/jobs/{job_id}/description", json={"description": "Malicious overwrite."})
    mine = logged_in_client.get(f"/api/jobs/{job_id}").json()
    assert mine["description"] == "Original text."


def test_update_structured_data_is_write_once(logged_in_client, other_logged_in_client):
    job_id = _create(logged_in_client)["job_id"]
    logged_in_client.patch(f"/api/jobs/{job_id}/structured-data", json={"data": {"remote": True}})
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    other_logged_in_client.patch(f"/api/jobs/{job_id}/structured-data", json={"data": {"remote": False}})
    mine = logged_in_client.get(f"/api/jobs/{job_id}").json()
    assert '"remote": true' in mine["structured_data"]


def test_update_score_and_status(logged_in_client):
    job_id = _create(logged_in_client)["job_id"]
    resp = logged_in_client.patch(f"/api/jobs/{job_id}/score-and-status", json={
        "score": 0.0, "reason": "listing gone", "status": "auto_rejected",
    })
    body = resp.json()
    assert body["score"] == 0.0
    assert body["status"] == "auto_rejected"


def test_get_new_unscored_new_with_descriptions(logged_in_client):
    with_desc = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    no_desc = _create(logged_in_client, url="https://example.com/jobs/b", description=None)["job_id"]

    new_ids = {j["id"] for j in logged_in_client.get("/api/jobs/new").json()}
    assert new_ids == {with_desc, no_desc}

    unscored_ids = {j["id"] for j in logged_in_client.get("/api/jobs/unscored").json()}
    assert unscored_ids == {with_desc}

    with_desc_ids = {j["id"] for j in logged_in_client.get("/api/jobs/new-with-descriptions").json()}
    assert with_desc_ids == {with_desc}


def test_for_ranking(logged_in_client):
    job_id = _create(logged_in_client)["job_id"]
    rows = logged_in_client.get("/api/jobs/for-ranking").json()
    assert [r["id"] for r in rows] == [job_id]


def test_examples_and_feedback(logged_in_client):
    applied_id = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    rejected_id = _create(logged_in_client, url="https://example.com/jobs/b")["job_id"]
    logged_in_client.patch(f"/api/jobs/{applied_id}/status", json={"status": "applied"})
    logged_in_client.patch(f"/api/jobs/{rejected_id}/status", json={"status": "rejected", "rejection_reason": "nope"})

    examples = logged_in_client.get("/api/jobs/examples").json()
    assert [j["id"] for j in examples["positive"]] == [applied_id]
    assert [j["id"] for j in examples["negative"]] == [rejected_id]

    feedback = logged_in_client.get("/api/jobs/feedback").json()
    assert len(feedback["applied"]) == 1
    assert len(feedback["rejected"]) == 1

    assert logged_in_client.get("/api/jobs/applied-ids").json()["ids"] == [applied_id]
    assert logged_in_client.get("/api/jobs/rejected-ids").json()["ids"] == [rejected_id]
    assert logged_in_client.get("/api/jobs/decisions-count").json()["count"] == 2


def test_feedback_respects_limit_params(logged_in_client):
    # Regression: get_all_feedback() shipped every applied/rejected job's full
    # description unconditionally — preference_agent/runner.py only ever used
    # the 50 most recent rejected (and, before this fix, an unbounded number of
    # applied). Most-recent-first ordering means the limit keeps the newest.
    ids = []
    for i in range(3):
        jid = _create(logged_in_client, url=f"https://example.com/jobs/fb-applied-{i}")["job_id"]
        logged_in_client.patch(f"/api/jobs/{jid}/status", json={"status": "applied"})
        ids.append(jid)

    feedback = logged_in_client.get("/api/jobs/feedback", params={"limit_applied": 2}).json()
    assert len(feedback["applied"]) == 2
    assert len(feedback["rejected"]) == 0


def test_feedback_includes_decided_at(logged_in_client):
    # Regression: applied/rejected examples had no timestamp at all, so
    # preference_agent/runner.py's distiller couldn't tell a 6-month-old
    # decision from yesterday's — no way to express a reversed preference.
    applied_id = _create(logged_in_client, url="https://example.com/jobs/decided-a")["job_id"]
    rejected_id = _create(logged_in_client, url="https://example.com/jobs/decided-b")["job_id"]
    logged_in_client.patch(f"/api/jobs/{applied_id}/status", json={"status": "applied"})
    logged_in_client.patch(f"/api/jobs/{rejected_id}/status", json={"status": "rejected", "rejection_reason": "nope"})

    feedback = logged_in_client.get("/api/jobs/feedback").json()
    assert feedback["applied"][0]["decided_at"]
    assert feedback["rejected"][0]["decided_at"]


def test_feedback_truncates_description_server_side(logged_in_client):
    job_id = _create(
        logged_in_client, url="https://example.com/jobs/fb-long-desc", description="x" * 3000,
    )["job_id"]
    logged_in_client.patch(f"/api/jobs/{job_id}/status", json={"status": "applied"})

    feedback = logged_in_client.get("/api/jobs/feedback").json()
    assert len(feedback["applied"][0]["description"]) == 1500


def test_query_outcome_stats(logged_in_client):
    job_id = _create(logged_in_client, search_query="python dev")["job_id"]
    logged_in_client.patch(f"/api/jobs/{job_id}/status", json={"status": "applied"})
    stats = logged_in_client.get("/api/jobs/query-outcome-stats", params={"source": "linkedin"}).json()
    assert len(stats) == 1
    assert stats[0]["search_query"] == "python dev"
    assert stats[0]["applied_total"] == 1


def test_count_and_delete_by_filter_only_affects_this_user(logged_in_client, other_logged_in_client):
    mine = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    logged_in_client.patch(f"/api/jobs/{mine}/status", json={"status": "auto_rejected"})
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/a", "source": "linkedin",
    })

    count = logged_in_client.get("/api/jobs/count", params={"status": ["auto_rejected"]}).json()["count"]
    assert count == 1

    deleted = logged_in_client.delete("/api/jobs", params={"status": ["auto_rejected"]}).json()["deleted"]
    assert deleted == 1

    # Removed from my view...
    assert logged_in_client.get("/api/jobs").json() == []
    # ...but the shared posting (and the other user's link to it) survives.
    theirs = other_logged_in_client.get(f"/api/jobs/{mine}").json()
    assert theirs["status"] == "new"


def test_requires_login(client):
    assert client.get("/api/jobs/new").status_code == 401
    assert client.get("/api/jobs/urls").status_code == 401


def test_ranked_and_ranked_count(logged_in_client):
    top = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    other = _create(logged_in_client, url="https://example.com/jobs/b")["job_id"]
    logged_in_client.patch(f"/api/jobs/{top}/ranking", json={"listwise_rank": 1})
    logged_in_client.patch(f"/api/jobs/{other}/ranking", json={"listwise_rank": 5})
    logged_in_client.patch(f"/api/jobs/{top}/status", json={"status": "applied"})
    logged_in_client.patch(f"/api/jobs/{other}/status", json={"status": "rejected"})

    ranked = logged_in_client.get("/api/jobs/ranked", params={"status": ["applied", "rejected"]}).json()
    assert [j["id"] for j in ranked] == [top, other]
    assert logged_in_client.get("/api/jobs/ranked-count").json()["count"] == 2


def test_reset_auto_rejected(logged_in_client, other_logged_in_client):
    with_desc = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    no_desc = _create(logged_in_client, url="https://example.com/jobs/b", description=None)["job_id"]
    for jid in (with_desc, no_desc):
        logged_in_client.patch(f"/api/jobs/{jid}/score-and-status", json={
            "score": 0.0, "reason": "bad", "status": "auto_rejected",
        })

    resp = logged_in_client.post("/api/jobs/reset-auto-rejected")
    assert resp.json()["reset"] == 1  # only the one with a description

    assert logged_in_client.get(f"/api/jobs/{with_desc}").json()["status"] == "new"
    assert logged_in_client.get(f"/api/jobs/{no_desc}").json()["status"] == "auto_rejected"
