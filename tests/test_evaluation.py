import jobs_repo


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

    def test_tied_rank_orders_most_recently_decided_first(self, user, logged_in_client, db_conn):
        # Regression: listwise_rank is only ever 1-20 and freezes at decision time,
        # so many decided jobs end up sharing the same rank after enough runs.
        # Without an updated_at tiebreak, Postgres returns ties in an arbitrary
        # (effectively oldest-first) order, silently pinning precision@K and the
        # calibration feedback to the earliest decisions forever.
        older = _insert_ranked(logged_in_client, "applied", 1, url="https://example.com/eval/tie-older")
        newer = _insert_ranked(logged_in_client, "applied", 1, url="https://example.com/eval/tie-newer")

        rows = jobs_repo.get_ranked(db_conn, user["id"], ["applied"])
        assert [r["id"] for r in rows] == [newer, older]

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


class TestApplyRateByBucket:
    def test_no_ranked_jobs_returns_all_empty_buckets(self, logged_in_client):
        buckets = logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]
        assert [b["range"] for b in buckets] == ["1-5", "6-10", "11-15", "16-20"]
        assert all(b["apply_rate"] is None and b["n"] == 0 for b in buckets)

    def test_applied_and_rejected_split_within_a_bucket(self, logged_in_client):
        _insert_ranked(logged_in_client, "applied", 1)
        _insert_ranked(logged_in_client, "rejected", 2)
        buckets = logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]
        first = next(b for b in buckets if b["range"] == "1-5")
        assert first["apply_rate"] == 0.5
        assert first["n"] == 2

    def test_ranks_bucketed_correctly_by_range(self, logged_in_client):
        _insert_ranked(logged_in_client, "applied", 7)   # 6-10
        _insert_ranked(logged_in_client, "applied", 20)  # 16-20
        buckets = {b["range"]: b for b in logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]}
        assert buckets["1-5"]["n"] == 0
        assert buckets["6-10"]["n"] == 1
        assert buckets["11-15"]["n"] == 0
        assert buckets["16-20"]["n"] == 1

    def test_reviewed_is_excluded_from_buckets(self, logged_in_client):
        _insert_ranked(logged_in_client, "reviewed", 1)
        buckets = logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]
        assert all(b["n"] == 0 for b in buckets)

    def test_sample_size_grows_with_decision_history_unlike_precision_at_k(self, logged_in_client):
        # The whole point of the replacement: precision@5 only ever reflects 5
        # data points no matter how much history accumulates. The bucket for the
        # same rank range must keep growing as more jobs are decided there.
        for i in range(8):
            _insert_ranked(logged_in_client, "applied" if i % 2 == 0 else "rejected", 1, url=f"https://example.com/eval/bucket-growth-{i}")
        body = logged_in_client.get("/api/eval/report").json()
        assert body["n_evaluated_5"] == 5  # precision@5 still capped at 5...
        first_bucket = next(b for b in body["apply_rate_by_bucket"] if b["range"] == "1-5")
        assert first_bucket["n"] == 8  # ...but the bucket reflects all 8 decisions

    def test_fallback_rank_reason_is_excluded_from_buckets(self, logged_in_client):
        # A FALLBACK_RANK_REASON row's position comes from rerank order, not Opus
        # judgment — counting it would credit/blame the wrong stage of the pipeline.
        job_id = _insert_ranked(logged_in_client, "applied", 1)
        logged_in_client.patch(f"/api/jobs/{job_id}/ranking", json={
            "embedding_score": 0.8, "rerank_score": 0.8, "listwise_rank": 1,
            "rank_reason": "[unranked — Opus ranking unavailable this run, showing rerank order]",
        })
        buckets = logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]
        assert all(b["n"] == 0 for b in buckets)

    def test_exploration_pick_is_excluded_from_buckets(self, logged_in_client):
        # An exploration slot's rank reflects pool composition (a randomly
        # injected outsider), not the normal deterministic pipeline's judgment —
        # same exclusion reasoning as the fallback/omitted sentinels.
        job_id = _insert_ranked(logged_in_client, "applied", 2)
        logged_in_client.patch(f"/api/jobs/{job_id}/ranking", json={
            "embedding_score": 0.8, "rerank_score": 0.8, "listwise_rank": 2,
            "rank_reason": "[EXPLORATION] Great fit despite being outside the top-20 pool.",
        })
        buckets = logged_in_client.get("/api/eval/report").json()["apply_rate_by_bucket"]
        assert all(b["n"] == 0 for b in buckets)


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
