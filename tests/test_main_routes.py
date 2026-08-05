class TestRootRouteAnonymous:
    def test_anonymous_visitor_sees_public_landing_not_a_login_bounce(self, client):
        # Regression: a logged-out visitor's first contact used to be an
        # immediate redirect to /login with no explanation of the product at all.
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 200
        assert "Register" in resp.text
        assert "Log in" in resp.text

    def test_anonymous_landing_links_to_register_and_how_it_works(self, client):
        resp = client.get("/")
        assert 'href="/register"' in resp.text
        assert 'href="/how-it-works"' in resp.text

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
        assert "From a CV to a ranked shortlist" in resp.text

    def test_logged_out_nav_has_no_dashboard_or_logout_links(self, client):
        # /preferences is intentionally not checked here — how_it_works.html's
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
