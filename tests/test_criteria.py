def test_create_and_list(logged_in_client):
    resp = logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    assert resp.status_code == 200

    rows = logged_in_client.get("/api/criteria").json()
    assert len(rows) == 1
    assert rows[0]["type"] == "required"
    assert rows[0]["value"] == "Python"
    assert rows[0]["is_active"] == 1


def test_invalid_type_rejected(logged_in_client):
    resp = logged_in_client.post("/api/criteria", json={"type": "nonsense", "value": "x"})
    assert resp.status_code == 400


def test_duplicate_same_user_ignored(logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    rows = logged_in_client.get("/api/criteria").json()
    assert len(rows) == 1


def test_same_value_allowed_for_different_users(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    other_logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    assert len(logged_in_client.get("/api/criteria").json()) == 1
    assert len(other_logged_in_client.get("/api/criteria").json()) == 1


def test_active_dict(logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    logged_in_client.post("/api/criteria", json={"type": "title", "value": "Backend"})
    active = logged_in_client.get("/api/criteria/active").json()
    assert active["required"] == ["Python"]
    assert active["titles"] == ["Backend"]


def test_toggle_and_delete(logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "required", "value": "Python"})
    row = logged_in_client.get("/api/criteria").json()[0]

    logged_in_client.patch(f"/api/criteria/{row['id']}", json={"is_active": False})
    active = logged_in_client.get("/api/criteria/active").json()
    assert active["required"] == []

    logged_in_client.delete(f"/api/criteria/{row['id']}")
    assert logged_in_client.get("/api/criteria").json() == []


def test_delete_by_type_removes_only_that_type(logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "title", "value": "Backend"})
    logged_in_client.post("/api/criteria", json={"type": "title", "value": "Platform"})
    logged_in_client.post("/api/criteria", json={"type": "location", "value": "Poland"})

    resp = logged_in_client.delete("/api/criteria/by-type/title")
    assert resp.json()["deleted"] == 2

    remaining = logged_in_client.get("/api/criteria").json()
    assert [r["type"] for r in remaining] == ["location"]


def test_delete_by_type_is_scoped_to_the_caller(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "title", "value": "Backend"})
    other_logged_in_client.post("/api/criteria", json={"type": "title", "value": "Frontend"})

    logged_in_client.delete("/api/criteria/by-type/title")

    assert logged_in_client.get("/api/criteria").json() == []
    assert len(other_logged_in_client.get("/api/criteria").json()) == 1


def test_delete_by_type_with_no_matches_is_a_noop(logged_in_client):
    resp = logged_in_client.delete("/api/criteria/by-type/title")
    assert resp.json()["deleted"] == 0
