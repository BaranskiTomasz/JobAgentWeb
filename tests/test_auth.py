def test_register_creates_user_and_logs_in(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code in (200, 303)

    api_resp = client.get("/api/jobs/stats")
    assert api_resp.status_code == 200


def test_register_wrong_invite_code_rejected(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "not-the-real-code",
    })
    assert resp.status_code == 400
    assert "Invalid invite code" in resp.text
    assert client.get("/api/jobs/stats").status_code == 401


def test_register_missing_invite_code_rejected(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
    })
    assert resp.status_code == 400
    assert "Invalid invite code" in resp.text


def test_register_no_invite_code_configured_closes_registration(client, monkeypatch):
    monkeypatch.setattr("routers.auth.INVITE_CODE", None)
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert "Registration is currently closed" in resp.text


def test_register_password_mismatch_rejected(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "different",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert "do not match" in resp.text

    assert client.get("/api/jobs/stats").status_code == 401


def test_register_short_password_rejected(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "short", "password_confirm": "short",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert "at least 8 characters" in resp.text


def test_register_short_username_rejected(client):
    resp = client.post("/register", data={
        "username": "ab", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert "at least 3 characters" in resp.text


def test_register_duplicate_username_rejected(client, user):
    resp = client.post("/register", data={
        "username": user["username"], "password": "anotherpassword", "password_confirm": "anotherpassword",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert "already taken" in resp.text


def test_login_wrong_password_rejected(client, user):
    resp = client.post("/login", data={"username": user["username"], "password": "wrongpassword"})
    assert resp.status_code == 400
    assert "Invalid username or password" in resp.text
    assert client.get("/api/jobs/stats").status_code == 401


def test_login_unknown_username_rejected(client):
    resp = client.post("/login", data={"username": "ghost", "password": "whatever123"})
    assert resp.status_code == 400


def test_login_success_grants_access(client, user):
    resp = client.post("/login", data={"username": user["username"], "password": user["password"]})
    assert resp.status_code in (200, 303)
    assert client.get("/api/jobs/stats").status_code == 200


def test_protected_route_401_without_session(client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs/stats").status_code == 401
    assert client.get("/api/jobs/would-apply-stats").status_code == 401


def test_dashboard_redirects_to_login_when_unauthenticated(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_logout_clears_session(logged_in_client):
    assert logged_in_client.get("/api/jobs/stats").status_code == 200
    resp = logged_in_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert logged_in_client.get("/api/jobs/stats").status_code == 401
