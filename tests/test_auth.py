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


def test_register_shows_multiple_errors_at_once(client):
    # Regression: this used to be one elif chain, so a wrong invite code
    # masked a too-short password error entirely.
    resp = client.post("/register", data={
        "username": "newperson", "password": "short", "password_confirm": "short",
        "invite_code": "not-the-real-code",
    })
    assert resp.status_code == 400
    assert "Invalid invite code" in resp.text
    assert "at least 8 characters" in resp.text


def test_register_repopulates_username_and_invite_code_on_error(client):
    # Regression: every field (including username and the correctly-typed
    # invite code) used to be wiped on any error, forcing a full retype.
    resp = client.post("/register", data={
        "username": "newperson", "password": "short", "password_confirm": "short",
        "invite_code": "test-invite-code",
    })
    assert resp.status_code == 400
    assert 'value="newperson"' in resp.text
    assert 'value="test-invite-code"' in resp.text


def test_register_never_repopulates_password_fields(client):
    resp = client.post("/register", data={
        "username": "newperson", "password": "short", "password_confirm": "short",
        "invite_code": "test-invite-code",
    })
    assert "short" not in resp.text


def test_register_page_get_has_empty_username_field(client):
    resp = client.get("/register")
    assert resp.status_code == 200
    assert 'id="username" name="username" required autofocus autocomplete="username" minlength="3" value=""' in resp.text


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


def test_login_returns_to_safe_catalog_page(client, user):
    resp = client.post("/login", data={
        "username": user["username"], "password": user["password"], "next": "/jobs/python?country=PL",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/jobs/python?country=PL"


def test_login_rejects_external_next_redirect(client, user):
    resp = client.post("/login", data={
        "username": user["username"], "password": user["password"], "next": "//evil.example",
    }, follow_redirects=False)
    assert resp.headers["location"] == "/"
    assert client.get("/api/jobs/stats").status_code == 200


def test_login_strips_whitespace_from_username(client, user):
    # Regression: login_submit only stripped the username for the rate-limit
    # key and passed the raw value to get_by_username, so a stray leading or
    # trailing space meant a real account couldn't log in.
    resp = client.post("/login", data={"username": f"  {user['username']}  ", "password": user["password"]})
    assert resp.status_code in (200, 303)
    assert client.get("/api/jobs/stats").status_code == 200


def test_concurrent_registration_of_the_same_username_does_not_500(client):
    # Regression: two concurrent registrations for the same username both pass
    # the get_by_username pre-check; the second INSERT used to trip the unique
    # constraint and raise an uncaught IntegrityError (500) instead of the
    # normal "That username is already taken" response.
    import threading

    from starlette.testclient import TestClient

    from main import app

    results = []
    barrier = threading.Barrier(2)

    def _register():
        with TestClient(app) as c:
            barrier.wait(timeout=5)
            resp = c.post("/register", data={
                "username": "raceuser", "password": "goodpassword", "password_confirm": "goodpassword",
                "invite_code": "test-invite-code",
            })
            results.append(resp.status_code)

    t1 = threading.Thread(target=_register)
    t2 = threading.Thread(target=_register)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert sorted(results) == [200, 400] or sorted(results) == [303, 400]


def test_protected_route_401_without_session(client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs/stats").status_code == 401
    assert client.get("/api/jobs/would-apply-stats").status_code == 401


def test_dashboard_shows_public_landing_when_unauthenticated(client):
    # See tests/test_main_routes.py for full coverage of public_landing.html.
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "Register" in resp.text


def test_logout_clears_session(logged_in_client):
    assert logged_in_client.get("/api/jobs/stats").status_code == 200
    resp = logged_in_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert logged_in_client.get("/api/jobs/stats").status_code == 401


def test_logout_revokes_sessions_on_other_devices_too(user, logged_in_client):
    # Regression: session cookies had no server-side revocation, so logging out
    # only cleared the local cookie and a copied/stolen session stayed valid.
    # session_epoch makes logout invalidate every outstanding cookie.
    from fastapi.testclient import TestClient
    from main import app

    other_device = TestClient(app)
    other_device.post("/login", data={"username": user["username"], "password": user["password"]})
    assert other_device.get("/api/jobs/stats").status_code == 200

    logged_in_client.post("/logout")

    assert other_device.get("/api/jobs/stats").status_code == 401


def test_login_rate_limited_after_repeated_attempts(client, monkeypatch):
    monkeypatch.setattr("config.RATE_LIMIT_ENABLED", True)  # disabled by default for the rest of the suite
    for _ in range(10):
        resp = client.post("/login", data={"username": "ghost", "password": "whatever123"})
        assert resp.status_code == 400
    resp = client.post("/login", data={"username": "ghost", "password": "whatever123"})
    assert resp.status_code == 429


def test_login_rate_limit_is_keyed_by_username_not_ip(client, monkeypatch):
    # Regression: an IP-keyed bucket would lock out every user behind Caddy's
    # loopback IP once anyone mistyped a password 10 times. Keying by username
    # means one account being hammered doesn't affect another's login.
    monkeypatch.setattr("config.RATE_LIMIT_ENABLED", True)
    for _ in range(10):
        client.post("/login", data={"username": "account-a", "password": "wrong"})
    resp = client.post("/login", data={"username": "account-b", "password": "wrong"})
    assert resp.status_code == 400  # not 429, a different username, unaffected


def test_register_rate_limited_after_repeated_attempts(client, monkeypatch):
    monkeypatch.setattr("config.RATE_LIMIT_ENABLED", True)
    for _ in range(10):
        resp = client.post("/register", data={
            "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
            "invite_code": "wrong-code",
        })
        assert resp.status_code == 400
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "wrong-code",
    })
    assert resp.status_code == 429


def test_login_and_register_are_independent_rate_limit_buckets(client, monkeypatch):
    monkeypatch.setattr("config.RATE_LIMIT_ENABLED", True)
    for _ in range(10):
        client.post("/login", data={"username": "ghost", "password": "whatever123"})
    resp = client.post("/register", data={
        "username": "newperson", "password": "goodpassword", "password_confirm": "goodpassword",
        "invite_code": "wrong-code",
    })
    assert resp.status_code == 400  # not 429, register's own bucket is untouched


class TestJobAgentApiKeyAuth:
    """The trusted-client bypass for the local JobAgent desktop installation
    (deps.py::get_current_user): a static key instead of a session cookie."""

    def test_correct_key_grants_access_without_any_login(self, client, user, monkeypatch):
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
        resp = client.get("/api/jobs/stats", headers={"X-JobAgent-Api-Key": "test-shared-secret"})
        assert resp.status_code == 200

    def test_wrong_key_is_rejected(self, client, user, monkeypatch):
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
        resp = client.get("/api/jobs/stats", headers={"X-JobAgent-Api-Key": "wrong-value"})
        assert resp.status_code == 401

    def test_missing_header_falls_back_to_session_check(self, client, monkeypatch):
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", "1")
        resp = client.get("/api/jobs/stats")
        assert resp.status_code == 401

    def test_bypass_inactive_when_not_configured(self, client, user):
        # Default state (nothing set in .env): the header must have no effect.
        resp = client.get("/api/jobs/stats", headers={"X-JobAgent-Api-Key": "anything"})
        assert resp.status_code == 401

    def test_key_scopes_to_the_configured_user_only(self, client, user, other_user, monkeypatch):
        # Regression guard: this must authenticate as the ONE configured
        # user_id, not just "any" user or the first one found.
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
        resp = client.post(
            "/api/jobs",
            headers={"X-JobAgent-Api-Key": "test-shared-secret"},
            json={"title": "Dev", "company": "Acme", "location": "Remote",
                  "url": "https://example.com/apikey-test", "source": "linkedin"},
        )
        assert resp.status_code == 200
        owner_urls = client.get("/api/jobs/urls", headers={"X-JobAgent-Api-Key": "test-shared-secret"}).json()
        assert "https://example.com/apikey-test" in owner_urls["urls"]

    def test_nonexistent_configured_user_id_falls_back_to_session_check(self, client, monkeypatch):
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", "999999")
        resp = client.get("/api/jobs/stats", headers={"X-JobAgent-Api-Key": "test-shared-secret"})
        assert resp.status_code == 401

    def test_key_cannot_reach_admin_routes_even_when_scoped_to_an_admin_account(self, client, admin_user, monkeypatch):
        # The key is scoped to one account's own automation, not an admin
        # bypass, even when it happens to point at an admin account.
        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(admin_user["id"]))
        resp = client.get("/admin", headers={"X-JobAgent-Api-Key": "test-shared-secret"})
        assert resp.status_code == 403

    def test_real_admin_session_still_reaches_admin_routes(self, admin_client):
        # Regression guard for the fix above: a genuine logged-in admin session
        # (no API key involved at all) must be unaffected.
        resp = admin_client.get("/admin")
        assert resp.status_code == 200

    def test_bypass_immune_to_session_epoch_logout(self, client, user, db_conn, monkeypatch):
        # A logout-everywhere (session_epoch bump) must not affect the API-key path.
        import users_repo
        users_repo.bump_session_epoch(db_conn, user["id"])
        db_conn.commit()

        monkeypatch.setattr("deps.JOBAGENT_API_KEY", "test-shared-secret")
        monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
        resp = client.get("/api/jobs/stats", headers={"X-JobAgent-Api-Key": "test-shared-secret"})
        assert resp.status_code == 200
