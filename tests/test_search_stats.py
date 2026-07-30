def test_record_and_summary(logged_in_client):
    logged_in_client.post("/api/search-stats", json={
        "source": "linkedin", "search_query": "backend engineer", "location": "Poland",
        "cards_found": 10, "new_found": 3,
    })
    logged_in_client.post("/api/search-stats", json={
        "source": "linkedin", "search_query": "backend engineer", "location": "Germany",
        "cards_found": 0, "new_found": 0,
    })

    summary = logged_in_client.get("/api/search-stats/summary", params={"source": "linkedin"}).json()
    assert len(summary) == 1
    row = summary[0]
    assert row["search_query"] == "backend engineer"
    assert row["total_searches"] == 2
    assert row["zero_result_searches"] == 1
    assert row["total_new_found"] == 3


def test_zero_yield_queries(logged_in_client):
    for _ in range(5):
        logged_in_client.post("/api/search-stats", json={
            "source": "linkedin", "search_query": "dead query", "location": "Poland",
            "cards_found": 2, "new_found": 0,
        })
    logged_in_client.post("/api/search-stats", json={
        "source": "linkedin", "search_query": "good query", "location": "Poland",
        "cards_found": 5, "new_found": 2,
    })

    dead = logged_in_client.get("/api/search-stats/zero-yield", params={"source": "linkedin", "min_searches": 5}).json()
    assert dead == ["dead query"]


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/search-stats", json={
        "source": "linkedin", "search_query": "q", "location": "Poland", "cards_found": 1, "new_found": 1,
    })
    assert other_logged_in_client.get("/api/search-stats/summary", params={"source": "linkedin"}).json() == []
