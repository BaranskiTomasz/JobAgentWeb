def test_log_and_summary(logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.05,
    })
    summary = logged_in_client.get("/api/usage/summary").json()
    assert summary["today_cost_usd"] == 0.05
    assert summary["today_tokens"] == 1200
    assert summary["total_cost_usd"] == 0.05


def test_cost_per_100_does_not_require_a_recorded_run_summary(logged_in_client):
    # Regression: cost_per_100_usd used to come from cost_summaries, which only
    # gets a row when record_run_summary() runs to completion client-side. A
    # pipeline run can take hours, and if the local process is interrupted
    # before then (machine sleeps, terminal closed, crash), that call never
    # happens, leaving real, already-billed usage_log rows with nothing to
    # show for them. No /api/usage/run-summary call here on purpose.
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 1000, "output_tokens": 200, "cost_usd": 1.0,
    })
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 500, "output_tokens": 100, "cost_usd": 1.0,
    })
    summary = logged_in_client.get("/api/usage/summary").json()
    # 2 jobs_evaluated (module='scorer'), total cost 2.0 -> cost per 100 = 100.0
    assert summary["cost_per_100_usd"] == 100.0


def test_cost_per_100_counts_only_scorer_calls_but_all_modules_cost(logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 100, "output_tokens": 0, "cost_usd": 1.0,
    })
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "extractor", "input_tokens": 100, "output_tokens": 0, "cost_usd": 1.0,
    })
    summary = logged_in_client.get("/api/usage/summary").json()
    # 1 job evaluated (only the scorer call counts), but both calls' cost
    # counts toward the total -> cost per 100 = 2.0 / 1 * 100 = 200.0
    assert summary["cost_per_100_usd"] == 200.0


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/usage", json={
        "model": "claude-sonnet-5", "module": "scorer", "input_tokens": 100, "output_tokens": 0, "cost_usd": 5.0,
    })
    summary = other_logged_in_client.get("/api/usage/summary").json()
    assert summary["total_cost_usd"] == 0
