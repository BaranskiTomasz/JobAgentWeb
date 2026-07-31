def _insert_ranked(client, status, rank, url=None):
    resp = client.post("/api/jobs", json={
        "title": "Test Job", "company": "Acme", "location": "Remote",
        "url": url or f"https://example.com/eval/{rank}-{status}",
        "source": "linkedin", "description": "Role.",
    })
    job_id = resp.json()["job_id"]
    client.patch(f"/api/jobs/{job_id}/ranking", json={
        "embedding_score": 0.8, "rerank_score": 0.8, "listwise_rank": rank,
    })
    if status != "new":
        client.patch(f"/api/jobs/{job_id}/status", json={"status": status})
    return job_id


class TestPrecisionAtK:
    def test_no_ranked_jobs_returns_none(self, logged_in_client):
        body = logged_in_client.get("/api/eval/report").json()
        assert body["precision_at_5"] is None
        assert body["n_evaluated_5"] == 0

    def test_applied_counts_as_positive(self, logged_in_client):
        _insert_ranked(logged_in_client, "applied", 1)
        body = logged_in_client.get("/api/eval/report").json()
        assert body["precision_at_5"] == 1.0

    def test_rejected_counts_as_negative(self, logged_in_client):
        _insert_ranked(logged_in_client, "rejected", 1)
        body = logged_in_client.get("/api/eval/report").json()
        assert body["precision_at_5"] == 0.0

    def test_auto_rejected_counts_as_negative(self, logged_in_client):
        _insert_ranked(logged_in_client, "auto_rejected", 1)
        body = logged_in_client.get("/api/eval/report").json()
        assert body["precision_at_5"] == 0.0

    def test_reviewed_is_not_a_decision_and_is_excluded(self, logged_in_client):
        # "reviewed" means read-but-undecided — it must not enter the K pool at all,
        # positive or negative (the exact bug this test guards against: it used to
        # count as a positive decision).
        _insert_ranked(logged_in_client, "reviewed", 1)
        body = logged_in_client.get("/api/eval/report").json()
        assert body["n_evaluated_5"] == 0
        assert body["precision_at_5"] is None

    def test_k_limits_results(self, logged_in_client):
        for i in range(10):
            _insert_ranked(logged_in_client, "applied" if i < 5 else "rejected", i + 1)
        body = logged_in_client.get("/api/eval/report").json()
        assert body["n_evaluated_5"] == 5
        assert body["precision_at_5"] == 1.0
        assert body["n_evaluated_10"] == 10
        assert body["precision_at_10"] == 0.5


class TestDivergenceCases:
    def test_false_positive_high_rank_rejected(self, logged_in_client):
        _insert_ranked(logged_in_client, "rejected", 2)
        cases = logged_in_client.get("/api/eval/report").json()["divergence_cases"]
        assert len(cases) == 1
        assert cases[0]["divergence_type"] == "false_positive"

    def test_false_negative_low_rank_applied(self, logged_in_client):
        _insert_ranked(logged_in_client, "applied", 18)
        cases = logged_in_client.get("/api/eval/report").json()["divergence_cases"]
        assert len(cases) == 1
        assert cases[0]["divergence_type"] == "false_negative"

    def test_reviewed_never_produces_a_divergence_case(self, logged_in_client):
        _insert_ranked(logged_in_client, "reviewed", 1)
        cases = logged_in_client.get("/api/eval/report").json()["divergence_cases"]
        assert cases == []
