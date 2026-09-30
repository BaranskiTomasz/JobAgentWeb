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


def test_remote_work_country_and_employer_markets_are_stored_separately(logged_in_client):
    response = logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"],
        "work_country": "Poland",
        "employer_countries": ["United States", "United Kingdom"],
        "seniority_levels": ["senior"],
        "required_seniority_levels": [],
        "preferred_company_types": ["product"],
        "required_company_types": [],
    }})
    assert response.status_code == 200
    active = logged_in_client.get("/api/candidate-preferences/active").json()
    assert active["work_country"] == "Poland"
    assert active["employer_countries"] == ["United States", "United Kingdom"]
    assert active["required_seniority_levels"] == []
    assert active["required_company_types"] == []


def test_invalid_field_rejected(logged_in_client):
    resp = logged_in_client.post("/api/candidate-preferences", json={"fields": {"not_a_real_field": 1}})
    assert resp.status_code == 400


def test_removed_dead_fields_are_rejected(logged_in_client):
    # Regression: these fields were removed from _JSON_FIELDS/_SCALAR_FIELDS
    # since nothing downstream ever read them. Confirms they're actually
    # gone, not just unused.
    for field in ("salary_max", "excluded_company_types", "preferred_industries", "excluded_industries"):
        resp = logged_in_client.post("/api/candidate-preferences", json={"fields": {field: 1}})
        assert resp.status_code == 400, f"{field} should have been rejected"


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


def test_activate_nonexistent_404s_and_leaves_active_untouched(logged_in_client):
    # Regression: set_active() used to deactivate the current row before
    # checking the target id existed, so a bad id left zero active rows.
    pref_id = logged_in_client.post("/api/candidate-preferences", json={"fields": {}}).json()["id"]
    resp = logged_in_client.post("/api/candidate-preferences/999999/activate")
    assert resp.status_code == 404
    assert logged_in_client.get("/api/candidate-preferences/active").json()["id"] == pref_id


def test_update_nonexistent_404s(logged_in_client):
    resp = logged_in_client.patch("/api/candidate-preferences/999999", json={"fields": {"salary_min": 1}})
    assert resp.status_code == 404


def test_update_another_users_preferences_404s(logged_in_client, other_logged_in_client):
    theirs = other_logged_in_client.post("/api/candidate-preferences", json={"fields": {}}).json()["id"]
    resp = logged_in_client.patch(f"/api/candidate-preferences/{theirs}", json={"fields": {"salary_min": 1}})
    assert resp.status_code == 404


def test_delete_nonexistent_404s(logged_in_client):
    resp = logged_in_client.delete("/api/candidate-preferences/999999")
    assert resp.status_code == 404


def test_save_syncs_location_criteria_from_work_mode(logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote", "hybrid"],
        "remote_countries": ["Poland", "Germany"],
        "hybrid_cities": ["Warsaw"],
    }})
    locations = logged_in_client.get("/api/criteria/active").json()["locations"]
    assert set(locations) == {"Poland", "Germany", "Warsaw"}


def test_work_country_drives_remote_search_location_criterion(logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"],
        "work_country": "Poland",
        "employer_countries": ["United States"],
    }})
    locations = logged_in_client.get("/api/criteria/active").json()["locations"]
    assert locations == ["Poland"]


def test_save_syncs_rejected_and_preferred_criteria_from_tech(logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "avoided_tech": ["PHP"], "extra_tech": ["Kubernetes"],
    }})
    active = logged_in_client.get("/api/criteria/active").json()
    assert active["rejected"] == ["PHP"]
    assert active["preferred"] == ["Kubernetes"]


def test_save_replaces_rather_than_accumulates_synced_criteria(logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {"avoided_tech": ["PHP"]}})
    logged_in_client.post("/api/candidate-preferences", json={"fields": {"avoided_tech": ["jQuery"]}})
    rejected = logged_in_client.get("/api/criteria/active").json()["rejected"]
    assert rejected == ["jQuery"]


def test_update_active_preferences_resynchronizes_criteria(logged_in_client):
    pref_id = logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"], "remote_countries": ["Poland"], "avoided_tech": ["PHP"],
    }}).json()["id"]
    response = logged_in_client.patch(f"/api/candidate-preferences/{pref_id}", json={"fields": {
        "remote_countries": ["Germany"], "avoided_tech": ["Java"],
    }})
    assert response.status_code == 200
    active = logged_in_client.get("/api/criteria/active").json()
    assert active["locations"] == ["Germany"]
    assert active["rejected"] == ["Java"]


def test_activate_preferences_resynchronizes_criteria(logged_in_client):
    first = logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"], "remote_countries": ["Poland"], "avoided_tech": ["PHP"],
    }}).json()["id"]
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"], "remote_countries": ["Germany"], "avoided_tech": ["Java"],
    }})
    response = logged_in_client.post(f"/api/candidate-preferences/{first}/activate")
    assert response.status_code == 200
    active = logged_in_client.get("/api/criteria/active").json()
    assert active["locations"] == ["Poland"]
    assert active["rejected"] == ["PHP"]


def test_save_resynchronizes_title_and_search_query_criteria(logged_in_client):
    logged_in_client.post("/api/criteria", json={"type": "title", "value": "Backend Engineer"})
    logged_in_client.post("/api/criteria", json={"type": "search_query", "value": "Legacy query"})
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "work_mode": ["remote"],
        "extra_tech": ["Python", "Docker"],
        "role_types": ["developer", "security"],
    }})
    active = logged_in_client.get("/api/criteria/active").json()
    assert set(active["titles"]) == {"Python Developer", "Software Engineer", "Security Engineer"}
    assert active["search_queries"] == []


def test_search_queries_skip_tools_that_are_not_job_roles(logged_in_client):
    logged_in_client.post("/api/candidate-preferences", json={"fields": {
        "extra_tech": ["PHP", "Symfony", "Doctrine", "MySQL", "RabbitMQ", "Claude Code"],
        "role_types": ["developer"],
    }})
    active = logged_in_client.get("/api/criteria/active").json()
    assert set(active["titles"]) == {"PHP Developer", "Symfony Developer", "Software Engineer"}
