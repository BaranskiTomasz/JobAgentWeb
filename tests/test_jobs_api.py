import json
import threading

import db as db_module
import jobs_repo


def test_concurrent_insert_of_the_same_new_url_does_not_raise(user, other_user):
    # Regression: this used to be check-then-insert (SELECT, then INSERT if not
    # found) — two collectors racing on a brand-new URL both saw "not found" and
    # both tried to INSERT the same deterministic id, so the loser hit a
    # duplicate-key error. In production this was silently swallowed by the
    # collector's generic except-and-skip, leaving that run's user with no state
    # row at all. ON CONFLICT DO NOTHING makes this genuinely atomic instead.
    job = {
        "title": "Race Condition Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/race-1", "source": "linkedin", "description": "Build things.",
    }
    results = {}
    errors = []
    barrier = threading.Barrier(2)

    def _insert(key, user_id):
        conn = db_module._get_pool().getconn()
        try:
            barrier.wait(timeout=5)  # maximize the chance both hit INSERT together
            results[key] = jobs_repo.insert(conn, user_id, job)
            conn.commit()
        except Exception as e:  # pragma: no cover - only hit if the race isn't fixed
            conn.rollback()
            errors.append(e)
        finally:
            db_module._get_pool().putconn(conn)

    t1 = threading.Thread(target=_insert, args=("a", user["id"]))
    t2 = threading.Thread(target=_insert, args=("b", other_user["id"]))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []
    assert results["a"]["job_id"] == results["b"]["job_id"]
    # Exactly one of the two racing inserts created the shared posting.
    assert sorted([results["a"]["posting_created"], results["b"]["posting_created"]]) == [False, True]


def _create(client, **overrides):
    body = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote",
        "url": "https://example.com/jobs/1",
        "source": "linkedin",
        "description": "Build things.",
    }
    body.update(overrides)
    resp = client.post("/api/jobs", json=body)
    assert resp.status_code == 200
    return resp.json()


def test_create_job(logged_in_client):
    result = _create(logged_in_client)
    assert result["job_id"] is not None
    assert result["posting_created"] is True

    resp = logged_in_client.get(f"/api/jobs/{result['job_id']}")
    assert resp.status_code == 200
    job = resp.json()
    assert job["title"] == "Backend Engineer"
    assert job["status"] == "new"
    assert job["would_apply"] is None
    assert job["posted_at"] is None


def test_create_job_stores_posted_at(logged_in_client):
    result = _create(logged_in_client, posted_at="2026-07-01T00:00:00")
    resp = logged_in_client.get(f"/api/jobs/{result['job_id']}")
    assert resp.json()["posted_at"].startswith("2026-07-01")


def test_create_job_stores_source_structured_data(logged_in_client):
    result = _create(logged_in_client, source_structured_data={"salary_min": 15000, "salary_currency": "PLN"})
    resp = logged_in_client.get(f"/api/jobs/{result['job_id']}")
    assert json.loads(resp.json()["source_structured_data"]) == {"salary_min": 15000, "salary_currency": "PLN"}


def test_create_job_without_source_structured_data_is_null(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.get(f"/api/jobs/{result['job_id']}")
    assert resp.json()["source_structured_data"] is None


def test_create_job_duplicate_for_same_user_is_ignored(logged_in_client):
    result = _create(logged_in_client)
    dup = logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    assert dup.status_code == 200
    assert dup.json()["job_id"] is None

    resp = logged_in_client.get("/api/jobs", params={"query": "Backend"})
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == result["job_id"]


def test_create_job_different_title_company_not_deduped(logged_in_client):
    """The old title+company dedup heuristic is gone — only url identifies a
    posting now. A genuinely different posting that happens to share a
    title+company with an existing one must NOT be silently dropped."""
    _create(logged_in_client, url="https://example.com/jobs/1")
    second = logged_in_client.post("/api/jobs", json={
        "title": "backend engineer", "company": "acme", "location": "Warsaw",
        "url": "https://example.com/jobs/2", "source": "linkedin",
    })
    assert second.json()["job_id"] is not None
    assert second.json()["posting_created"] is True


def test_shared_posting_reused_across_users(logged_in_client, other_logged_in_client):
    """The core point of the shared pool: when a second user's collector finds
    a URL already known from a first user, the posting is reused (posting_created
    False) and the new user gets their own fresh, independent state for it."""
    first = _create(logged_in_client)

    second = other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    assert second.status_code == 200
    body = second.json()
    assert body["job_id"] == first["job_id"]  # same posting id
    assert body["posting_created"] is False   # reused, not re-scraped

    # Independent state: user 1 marks applied, user 2's copy stays 'new'.
    logged_in_client.patch(f"/api/jobs/{first['job_id']}/status", json={"status": "applied"})
    mine = logged_in_client.get(f"/api/jobs/{first['job_id']}").json()
    theirs = other_logged_in_client.get(f"/api/jobs/{first['job_id']}").json()
    assert mine["status"] == "applied"
    assert theirs["status"] == "new"


def test_jobs_not_visible_to_other_user(logged_in_client, other_logged_in_client):
    _create(logged_in_client)
    resp = other_logged_in_client.get("/api/jobs")
    assert resp.json() == []


def test_get_unknown_job_404(logged_in_client):
    resp = logged_in_client.get("/api/jobs/doesnotexist")
    assert resp.status_code == 404


def test_get_job_404_for_wrong_user(logged_in_client, other_logged_in_client):
    """A job that exists (for the first user) must 404, not leak, for the second."""
    result = _create(logged_in_client)
    resp = other_logged_in_client.get(f"/api/jobs/{result['job_id']}")
    assert resp.status_code == 404


def test_jobs_api_requires_login(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 401


def test_update_status(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.patch(f"/api/jobs/{result['job_id']}/status", json={"status": "applied"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"


def test_update_status_with_rejection_reason(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.patch(f"/api/jobs/{result['job_id']}/status", json={
        "status": "rejected", "rejection_reason": "wrong stack",
    })
    body = resp.json()
    assert body["status"] == "rejected"
    assert body["rejection_reason"] == "wrong stack"


def test_update_status_unknown_job_404(logged_in_client):
    resp = logged_in_client.patch("/api/jobs/doesnotexist/status", json={"status": "applied"})
    assert resp.status_code == 404


def test_update_score(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.patch(f"/api/jobs/{result['job_id']}/score", json={
        "score": 8.5, "reason": "strong match", "breakdown": {"stack": 9, "salary": 8},
    })
    body = resp.json()
    assert body["score"] == 8.5
    assert body["score_reason"] == "strong match"
    assert '"stack": 9' in body["score_breakdown"]


def test_update_ranking(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.patch(f"/api/jobs/{result['job_id']}/ranking", json={
        "embedding_score": 0.8, "rerank_score": 0.9, "listwise_rank": 1,
        "rank_reason": "top of batch", "debate_flag": "overrated", "debate_note": "salary unclear",
    })
    body = resp.json()
    assert body["listwise_rank"] == 1
    assert body["debate_flag"] == "overrated"


def test_update_ranking_batch(logged_in_client):
    a = _create(logged_in_client, url="https://example.com/jobs/batch-a")["job_id"]
    b = _create(logged_in_client, url="https://example.com/jobs/batch-b")["job_id"]

    resp = logged_in_client.patch("/api/jobs/ranking", json={"items": [
        {"job_id": a, "embedding_score": 0.8, "rerank_score": 0.9, "listwise_rank": 1,
         "rank_reason": "top pick", "debate_flag": "overrated", "debate_note": "salary unclear"},
        {"job_id": b, "embedding_score": 0.5, "rerank_score": None, "listwise_rank": None},
    ]})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    job_a = logged_in_client.get(f"/api/jobs/{a}").json()
    assert job_a["listwise_rank"] == 1
    assert job_a["debate_flag"] == "overrated"
    job_b = logged_in_client.get(f"/api/jobs/{b}").json()
    assert job_b["listwise_rank"] is None
    assert job_b["embedding_score"] == 0.5


def test_update_ranking_batch_all_null_optional_columns(logged_in_client):
    # Regression: FROM (VALUES ...) infers each column's type from the literals
    # across every row in the batch — a column that's NULL in every single row
    # (rank_reason/debate_flag/debate_note for jobs outside the listwise-ranked
    # top-20, which is most of rank_jobs.py's own batch on a normal run) risks
    # Postgres picking the wrong type before the SET clause's cast ever applies.
    a = _create(logged_in_client, url="https://example.com/jobs/batch-null-a")["job_id"]
    b = _create(logged_in_client, url="https://example.com/jobs/batch-null-b")["job_id"]

    resp = logged_in_client.patch("/api/jobs/ranking", json={"items": [
        {"job_id": a, "embedding_score": 0.3, "rerank_score": None, "listwise_rank": None},
        {"job_id": b, "embedding_score": 0.4, "rerank_score": None, "listwise_rank": None},
    ]})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2
    assert logged_in_client.get(f"/api/jobs/{a}").json()["embedding_score"] == 0.3


def test_update_ranking_batch_skips_jobs_the_caller_does_not_own(logged_in_client, other_logged_in_client):
    mine = _create(logged_in_client, url="https://example.com/jobs/batch-mine")["job_id"]
    theirs = _create(other_logged_in_client, url="https://example.com/jobs/batch-theirs")["job_id"]

    resp = logged_in_client.patch("/api/jobs/ranking", json={"items": [
        {"job_id": mine, "embedding_score": 0.9, "rerank_score": None, "listwise_rank": None},
        {"job_id": theirs, "embedding_score": 0.9, "rerank_score": None, "listwise_rank": None},
    ]})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1  # only "mine" matched a state row for this user

    theirs_row = other_logged_in_client.get(f"/api/jobs/{theirs}").json()
    assert theirs_row["embedding_score"] is None


def test_update_ranking_batch_empty_items(logged_in_client):
    resp = logged_in_client.patch("/api/jobs/ranking", json={"items": []})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 0


def test_update_would_apply_batch(logged_in_client):
    a = _create(logged_in_client, url="https://example.com/jobs/wa-batch-a")["job_id"]
    b = _create(logged_in_client, url="https://example.com/jobs/wa-batch-b")["job_id"]

    resp = logged_in_client.patch("/api/jobs/would-apply", json={"items": [
        {"job_id": a, "would_apply": True, "reason": "score 8.0 >= 7.0"},
        {"job_id": b, "would_apply": False, "reason": "dealbreaker_risk flagged"},
    ]})
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    job_a = logged_in_client.get(f"/api/jobs/{a}").json()
    assert job_a["would_apply"] is True
    assert job_a["would_apply_reason"] == "score 8.0 >= 7.0"
    job_b = logged_in_client.get(f"/api/jobs/{b}").json()
    assert job_b["would_apply"] is False


def test_update_structured_data_is_shared_across_users(logged_in_client, other_logged_in_client):
    result = _create(logged_in_client)
    logged_in_client.patch(f"/api/jobs/{result['job_id']}/structured-data", json={
        "data": {"salary": "20000 PLN", "remote": True},
    })
    # Second user reuses the same posting and sees the same structured_data,
    # since it's an extraction of the posting, not a per-user judgment.
    other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    theirs = other_logged_in_client.get(f"/api/jobs/{result['job_id']}").json()
    assert '"remote": true' in theirs["structured_data"]


def test_missing_structured_data_includes_job_with_description_and_no_extraction(logged_in_client):
    result = _create(logged_in_client, description="Has a description.")
    ids = [j["id"] for j in logged_in_client.get("/api/jobs/missing-structured-data").json()]
    assert result["job_id"] in ids


def test_missing_structured_data_excludes_already_extracted_job(logged_in_client):
    result = _create(logged_in_client, description="Has a description.")
    logged_in_client.patch(f"/api/jobs/{result['job_id']}/structured-data", json={"data": {"remote": True}})
    ids = [j["id"] for j in logged_in_client.get("/api/jobs/missing-structured-data").json()]
    assert result["job_id"] not in ids


def test_missing_structured_data_excludes_job_without_description(logged_in_client):
    result = _create(logged_in_client, description=None)
    ids = [j["id"] for j in logged_in_client.get("/api/jobs/missing-structured-data").json()]
    assert result["job_id"] not in ids


def test_missing_structured_data_excludes_already_decided_jobs(logged_in_client):
    # Regression: this endpoint used to have no status filter at all, so
    # scripts/extract_jobs.py (JobAgent) re-processed the whole historical pool
    # every run — reviewed/applied/rejected/auto_rejected jobs never re-enter
    # scoring or ranking, so extracting structured_data for one is pure sunk
    # Haiku cost with no downstream reader.
    for status in ("reviewed", "applied", "rejected", "auto_rejected"):
        result = _create(logged_in_client, description="Has a description.", url=f"https://example.com/jobs/{status}")
        logged_in_client.patch(f"/api/jobs/{result['job_id']}/status", json={"status": status})
        ids = [j["id"] for j in logged_in_client.get("/api/jobs/missing-structured-data").json()]
        assert result["job_id"] not in ids, f"status={status} should be excluded"


def test_missing_structured_data_is_scoped_to_the_caller(logged_in_client, other_logged_in_client):
    _create(logged_in_client, description="Has a description.")
    assert other_logged_in_client.get("/api/jobs/missing-structured-data").json() == []


def test_update_would_apply_and_stats(logged_in_client):
    result = _create(logged_in_client)
    resp = logged_in_client.patch(f"/api/jobs/{result['job_id']}/would-apply", json={
        "would_apply": True, "reason": "score >= floor",
    })
    body = resp.json()
    assert body["would_apply"] is True
    assert body["would_apply_reason"] == "score >= floor"

    stats = logged_in_client.get("/api/jobs/would-apply-stats").json()
    assert stats["flagged_total"] == 1
    assert stats["decided"] == 0
    assert stats["precision"] is None

    logged_in_client.patch(f"/api/jobs/{result['job_id']}/status", json={"status": "applied"})
    stats = logged_in_client.get("/api/jobs/would-apply-stats").json()
    assert stats["decided"] == 1
    assert stats["precision"] == 1.0


def test_search_filters_by_status_and_min_score(logged_in_client):
    a = _create(logged_in_client, url="https://example.com/jobs/a", title="A")["job_id"]
    b = _create(logged_in_client, url="https://example.com/jobs/b", title="B")["job_id"]
    logged_in_client.patch(f"/api/jobs/{a}/score", json={"score": 9.0, "reason": "great"})
    logged_in_client.patch(f"/api/jobs/{b}/score", json={"score": 3.0, "reason": "meh"})
    logged_in_client.patch(f"/api/jobs/{a}/status", json={"status": "reviewed"})

    resp = logged_in_client.get("/api/jobs", params={"status": "reviewed"})
    ids = [j["id"] for j in resp.json()]
    assert ids == [a]

    resp = logged_in_client.get("/api/jobs", params={"min_score": 5})
    ids = [j["id"] for j in resp.json()]
    assert ids == [a]


def test_search_limit_and_offset(logged_in_client):
    a = _create(logged_in_client, url="https://example.com/jobs/a", title="A")["job_id"]
    b = _create(logged_in_client, url="https://example.com/jobs/b", title="B")["job_id"]
    c = _create(logged_in_client, url="https://example.com/jobs/c", title="C")["job_id"]
    logged_in_client.patch(f"/api/jobs/{a}/score", json={"score": 9.0, "reason": "great"})
    logged_in_client.patch(f"/api/jobs/{b}/score", json={"score": 8.0, "reason": "good"})
    logged_in_client.patch(f"/api/jobs/{c}/score", json={"score": 7.0, "reason": "ok"})

    resp = logged_in_client.get("/api/jobs", params={"limit": 2})
    ids = [j["id"] for j in resp.json()]
    assert ids == [a, b]

    resp = logged_in_client.get("/api/jobs", params={"limit": 2, "offset": 2})
    ids = [j["id"] for j in resp.json()]
    assert ids == [c]

    resp = logged_in_client.get("/api/jobs")
    assert len(resp.json()) == 3


def test_stats_endpoint(logged_in_client):
    a = _create(logged_in_client, url="https://example.com/jobs/a")["job_id"]
    logged_in_client.patch(f"/api/jobs/{a}/status", json={"status": "applied"})
    stats = logged_in_client.get("/api/jobs/stats").json()
    assert stats["total"] == 1
    assert stats["applied"] == 1
    assert stats["new"] == 0


def test_stats_scoped_per_user(logged_in_client, other_logged_in_client):
    _create(logged_in_client)
    stats = other_logged_in_client.get("/api/jobs/stats").json()
    assert stats["total"] == 0
