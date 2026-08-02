def test_create_and_get_active(logged_in_client):
    resp = logged_in_client.post("/api/cv-profiles", json={
        "filename": "cv.pdf", "raw_text": "Experienced engineer.", "parsed": {"skills": ["Python"]},
    })
    assert resp.status_code == 200
    profile_id = resp.json()["id"]

    active = logged_in_client.get("/api/cv-profiles/active")
    assert active.status_code == 200
    assert active.json()["id"] == profile_id
    assert active.json()["parsed"] == {"skills": ["Python"]}


def test_new_upload_deactivates_previous(logged_in_client):
    first = logged_in_client.post("/api/cv-profiles", json={
        "filename": "a.pdf", "raw_text": "A", "parsed": {},
    }).json()["id"]
    second = logged_in_client.post("/api/cv-profiles", json={
        "filename": "b.pdf", "raw_text": "B", "parsed": {},
    }).json()["id"]

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == second

    all_profiles = logged_in_client.get("/api/cv-profiles").json()
    assert len(all_profiles) == 2

    logged_in_client.post(f"/api/cv-profiles/{first}/activate")
    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == first


def test_no_active_profile_404(logged_in_client):
    resp = logged_in_client.get("/api/cv-profiles/active")
    assert resp.status_code == 404


def test_activate_nonexistent_profile_404s_and_leaves_active_untouched(logged_in_client):
    # Regression: set_active() used to unconditionally deactivate the current
    # active row before checking whether the target id existed — a bad id
    # silently left the user with zero active profiles while reporting {"ok": true}.
    profile_id = logged_in_client.post("/api/cv-profiles", json={
        "filename": "a.pdf", "raw_text": "A", "parsed": {},
    }).json()["id"]

    resp = logged_in_client.post("/api/cv-profiles/999999/activate")
    assert resp.status_code == 404

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == profile_id


def test_activate_another_users_profile_404s_and_leaves_active_untouched(logged_in_client, other_logged_in_client):
    mine = logged_in_client.post("/api/cv-profiles", json={
        "filename": "mine.pdf", "raw_text": "Mine", "parsed": {},
    }).json()["id"]
    theirs = other_logged_in_client.post("/api/cv-profiles", json={
        "filename": "theirs.pdf", "raw_text": "Theirs", "parsed": {},
    }).json()["id"]

    resp = logged_in_client.post(f"/api/cv-profiles/{theirs}/activate")
    assert resp.status_code == 404

    active = logged_in_client.get("/api/cv-profiles/active").json()
    assert active["id"] == mine


def test_cv_profiles_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/cv-profiles", json={"filename": "a.pdf", "raw_text": "A", "parsed": {}})
    assert other_logged_in_client.get("/api/cv-profiles").json() == []
    assert other_logged_in_client.get("/api/cv-profiles/active").status_code == 404


def test_requires_login(client):
    assert client.get("/api/cv-profiles").status_code == 401
