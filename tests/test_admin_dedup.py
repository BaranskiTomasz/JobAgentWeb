import uuid


def _create_candidate(logged_in_client, db_conn):
    # A source_id collision where company/location don't actually match is
    # the only match tier that still never auto-merges (AUTO_MERGE_CONFIDENCE
    # is 0.60 now, covering every other tier) - it's a detected conflict,
    # not a confidence signal, so it's the one reliable way to land a fixture
    # in the pending-review queue rather than have it merge immediately.
    token = uuid.uuid4().hex
    description = "Build reliable distributed backend services in Python and PostgreSQL. " * 4
    first = logged_in_client.post("/api/jobs", json={
        "title": "Backend Engineer", "company": f"Acme {token}", "location": "Berlin, Germany",
        "description": description,
        "url": f"https://boards.greenhouse.io/acme/jobs/{token}",
        "source": "greenhouse", "source_id": f"dup:{token}",
    })
    second = logged_in_client.post("/api/jobs", json={
        "title": "Sales Director", "company": f"Globex {token}", "location": "New York, United States",
        "description": "Lead enterprise sales across North America.",
        "url": f"https://boards.greenhouse.io/globex/jobs/{token}",
        "source": "greenhouse", "source_id": f"dup:{token}",
    })
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["job_id"]
    second_id = second.json()["job_id"]
    assert first_id is not None
    assert second_id is not None

    cur = db_conn.cursor()
    cur.execute(
        """SELECT id, job_id_low, job_id_high, match_method, confidence
             FROM job_dedup_matches
            WHERE job_id_low = LEAST(%s, %s) AND job_id_high = GREATEST(%s, %s)""",
        (first_id, second_id, first_id, second_id),
    )
    match_id, job_id_low, job_id_high, method, confidence = cur.fetchone()
    assert (method, confidence) == ("source_requisition_conflict", 0.90)
    return match_id, job_id_low, job_id_high


def test_dedup_page_requires_login(client):
    response = client.get("/admin/dedup", follow_redirects=False)
    assert response.status_code == 401


def test_dedup_page_forbids_non_admin(logged_in_client):
    response = logged_in_client.get("/admin/dedup")
    assert response.status_code == 403


def test_dedup_page_shows_empty_state(admin_client):
    response = admin_client.get("/admin/dedup")
    assert response.status_code == 200
    assert "Pending candidates (0)" in response.text
    assert "No pending candidates." in response.text


def test_dedup_page_lists_pending_candidate(logged_in_client, admin_client, db_conn):
    _create_candidate(logged_in_client, db_conn)

    response = admin_client.get("/admin/dedup")

    assert response.status_code == 200
    assert "Pending candidates (1)" in response.text
    assert "90% confidence" in response.text
    assert "source_requisition_conflict" in response.text
    assert "Acme" in response.text
    assert "Globex" in response.text


def test_merge_candidate_keeps_selected_survivor(logged_in_client, admin_client, db_conn):
    match_id, job_id_low, job_id_high = _create_candidate(logged_in_client, db_conn)

    response = admin_client.post(
        f"/admin/dedup/{match_id}/merge",
        data={
            "job_id_low": job_id_low,
            "job_id_high": job_id_high,
            "survivor_job_id": job_id_high,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/dedup"
    cur = db_conn.cursor()
    cur.execute("SELECT id FROM job_postings WHERE id IN (%s, %s)", (job_id_low, job_id_high))
    assert cur.fetchall() == [(job_id_high,)]
    cur.execute(
        "SELECT status, survivor_job_id, match_method, confidence FROM job_dedup_matches WHERE id = %s",
        (match_id,),
    )
    assert cur.fetchone() == ("merged", job_id_high, "manual_merge", 1.0)


def test_reject_candidate_removes_it_from_pending_list(logged_in_client, admin_client, db_conn):
    match_id, _, _ = _create_candidate(logged_in_client, db_conn)

    response = admin_client.post(
        f"/admin/dedup/{match_id}/reject", follow_redirects=False,
    )

    assert response.status_code == 303
    cur = db_conn.cursor()
    cur.execute("SELECT status FROM job_dedup_matches WHERE id = %s", (match_id,))
    assert cur.fetchone() == ("rejected",)
    page = admin_client.get("/admin/dedup")
    assert "No pending candidates." in page.text
    assert "source_requisition_conflict" not in page.text


def test_merge_candidate_requires_admin(logged_in_client):
    response = logged_in_client.post(
        "/admin/dedup/1/merge",
        data={"job_id_low": "a", "job_id_high": "b", "survivor_job_id": "a"},
    )
    assert response.status_code == 403


def test_reject_candidate_requires_admin(logged_in_client):
    response = logged_in_client.post("/admin/dedup/1/reject")
    assert response.status_code == 403
