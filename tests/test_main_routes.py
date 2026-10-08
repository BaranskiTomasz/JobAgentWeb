class TestRootRouteAnonymous:
    def test_anonymous_visitor_sees_jobs_not_a_login_bounce(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200
        assert "Python jobs" in resp.text
        assert "Create account" in resp.text
        assert "Log in" in resp.text

    def test_anonymous_catalog_links_to_register_and_how_it_works(self, client):
        resp = client.get("/")
        assert 'href="/register"' in resp.text
        assert 'href="/how-it-works"' in resp.text

    def test_remote_ok_is_attributed_without_using_its_logo(self, client):
        resp = client.get("/")
        assert "Remote OK" in resp.text
        assert "remoteok.ico" not in resp.text

    def test_anonymous_landing_has_no_logged_in_only_links(self, client):
        # Dashboard/Preferences/Logout would all just bounce an anonymous
        # visitor straight back to /login if clicked.
        resp = client.get("/")
        assert 'href="/preferences"' not in resp.text
        assert "Logout" not in resp.text


class TestRootRouteLoggedIn:
    def test_logged_in_user_does_not_see_public_landing(self, logged_in_client):
        resp = logged_in_client.get("/")
        assert "Create an account" not in resp.text

    def test_logged_in_zero_jobs_still_sees_the_empty_state_landing(self, logged_in_client, user):
        resp = logged_in_client.get("/")
        assert f"No jobs here yet, {user['username']}" in resp.text


class TestHowItWorksRoute:
    def test_reachable_when_logged_out(self, client):
        # Regression: this used to redirect anonymous visitors to /login, so a
        # visitor deciding whether to register couldn't read how the pipeline
        # works without registering first.
        resp = client.get("/how-it-works", follow_redirects=False)
        assert resp.status_code == 200
        assert "Browse freely. Personalize when you are ready." in resp.text

    def test_logged_out_nav_has_no_dashboard_or_logout_links(self, client):
        # /preferences is intentionally not checked here, how_it_works.html's
        # body text references it inline as part of explaining the pipeline
        # (unrelated to the nav menu this test targets).
        resp = client.get("/how-it-works")
        assert "Logout" not in resp.text
        assert 'href="/login"' in resp.text
        assert 'href="/register"' in resp.text

    def test_reachable_when_logged_in(self, logged_in_client):
        resp = logged_in_client.get("/how-it-works")
        assert resp.status_code == 200

    def test_logged_in_nav_has_dashboard_and_logout_links(self, logged_in_client):
        resp = logged_in_client.get("/how-it-works")
        assert 'href="/preferences"' in resp.text
        assert "Logout" in resp.text


class TestPreferencesRoute:
    def test_redirects_anonymous_to_login(self, client):
        resp = client.get("/preferences", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login"

    def test_reachable_when_logged_in(self, logged_in_client):
        resp = logged_in_client.get("/preferences")
        assert resp.status_code == 200
        # Data is loaded client-side via fetch(), not baked into the initial
        # HTML, so the page itself has no candidate_preferences_repo lookup
        # to test here beyond a successful render.
        assert 'id="save-btn"' in resp.text
