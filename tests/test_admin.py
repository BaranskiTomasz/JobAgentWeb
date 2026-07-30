def test_admin_page_requires_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 401


def test_admin_page_403_for_non_admin(logged_in_client):
    resp = logged_in_client.get("/admin")
    assert resp.status_code == 403


def test_admin_page_200_for_admin(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200
    assert "adminuser" in resp.text


def test_admin_delete_requires_admin(logged_in_client, other_user):
    resp = logged_in_client.post(f"/admin/users/{other_user['id']}/delete")
    assert resp.status_code == 403


def test_admin_cannot_delete_self(admin_client, admin_user):
    resp = admin_client.post(f"/admin/users/{admin_user['id']}/delete")
    assert resp.status_code == 400


def test_admin_delete_cascades_but_leaves_shared_postings_intact(admin_client, admin_user, other_user, other_logged_in_client):
    create = other_logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    job_id = create.json()["job_id"]

    resp = admin_client.post(f"/admin/users/{other_user['id']}/delete", follow_redirects=False)
    assert resp.status_code == 303

    # The user (and their per-user state) is gone...
    admin_page = admin_client.get("/admin")
    assert other_user["username"] not in admin_page.text

    # ...but the shared posting survives, reusable by the next user who finds it.
    admin_reuse = admin_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": "Acme", "location": "Remote",
        "url": "https://example.com/jobs/1", "source": "linkedin",
    })
    assert admin_reuse.json()["job_id"] == job_id
    assert admin_reuse.json()["posting_created"] is False
