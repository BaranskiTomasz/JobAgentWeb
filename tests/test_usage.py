def test_log_and_summary(logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.05,
    })
    summary = logged_in_client.get("/api/usage/summary").json()
    assert summary["today_cost_usd"] == 0.05
    assert summary["today_tokens"] == 1200
    assert summary["total_cost_usd"] == 0.05


def test_run_summary_and_cost_per_100(logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 1000, "output_tokens": 200, "cost_usd": 1.0,
    })
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 500, "output_tokens": 100, "cost_usd": 1.0,
    })
    logged_in_client.post("/api/usage/run-summary", json={
        "run_label": "run_agent", "started_at": "2020-01-01 00:00:00",
    })
    summary = logged_in_client.get("/api/usage/summary").json()
    # 2 jobs_evaluated (module='scorer'), total cost 2.0 -> cost per 100 = 100.0
    assert summary["cost_per_100_usd"] == 100.0


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 100, "output_tokens": 0, "cost_usd": 5.0,
    })
    summary = other_logged_in_client.get("/api/usage/summary").json()
    assert summary["total_cost_usd"] == 0
