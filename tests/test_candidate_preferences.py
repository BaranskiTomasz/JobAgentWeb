def test_create_and_get_active(logged_in_client):
    resp = logged_in_client.post("/api/candidate-preferences", json={
        "cv_profile_id": None,
        "fields": {"work_mode": ["remote", "hybrid"], "salary_min": 15000},
    })
    assert resp.status_code == 200
    pref_id = resp.json()["id"]

    active = logged_in_client.get("/api/candidate-preferences/active").json()
    assert active["id"] == pref_id
    assert active["work_mode"] == ["remote", "hybrid"]
    assert active["salary_min"] == 15000


def test_invalid_field_rejected(logged_in_client):
    resp = logged_in_client.post("/api/candidate-preferences", json={"fields": {"not_a_real_field": 1}})
    assert resp.status_code == 400


def test_update_in_place(logged_in_client):
    pref_id = logged_in_client.post("/api/candidate-preferences", json={
        "fields": {"salary_min": 10000},
    }).json()["id"]
    logged_in_client.patch(f"/api/candidate-preferences/{pref_id}", json={"fields": {"salary_min": 20000}})
    active = logged_in_client.get("/api/candidate-preferences/active").json()
    assert active["salary_min"] == 20000


def test_new_snapshot_deactivates_previous(logged_in_client):
    first = logged_in_client.post("/api/candidate-preferences", json={"fields": {}}).json()["id"]
    second = logged_in_client.post("/api/candidate-preferences", json={"fields": {}}).json()["id"]
    assert logged_in_client.get("/api/candidate-preferences/active").json()["id"] == second

    logged_in_client.post(f"/api/candidate-preferences/{first}/activate")
    assert logged_in_client.get("/api/candidate-preferences/active").json()["id"] == first


def test_delete(logged_in_client):
    pref_id = logged_in_client.post("/api/candidate-preferences", json={"fields": {}}).json()["id"]
    logged_in_client.delete(f"/api/candidate-preferences/{pref_id}")
    assert logged_in_client.get("/api/candidate-preferences").json() == []


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {}})
    assert other_logged_in_client.get("/api/candidate-preferences").json() == []
