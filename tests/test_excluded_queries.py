def test_exclude_and_list(logged_in_client):
    resp = logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "always zero yield",
    })
    assert resp.status_code == 200

    rows = logged_in_client.get("/api/excluded-search-queries").json()
    assert len(rows) == 1
    assert rows[0]["search_query"] == "junior java"


def test_reexclude_updates_reason(logged_in_client):
    logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "first reason",
    })
    logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "updated reason",
    })
    rows = logged_in_client.get("/api/excluded-search-queries").json()
    assert len(rows) == 1
    assert rows[0]["reason"] == "updated reason"


def test_get_excluded_by_source(logged_in_client):
    logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "bad",
    })
    result = logged_in_client.get("/api/excluded-search-queries/by-source", params={"source": "linkedin"}).json()
    assert result == {"junior java": "bad"}


def test_reinstate(logged_in_client):
    logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "bad",
    })
    row = logged_in_client.get("/api/excluded-search-queries").json()[0]
    logged_in_client.post(f"/api/excluded-search-queries/{row['id']}/reinstate")
    assert logged_in_client.get("/api/excluded-search-queries").json() == []


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/excluded-search-queries", json={
        "source": "linkedin", "search_query": "junior java", "reason": "bad",
    })
    assert other_logged_in_client.get("/api/excluded-search-queries").json() == []
