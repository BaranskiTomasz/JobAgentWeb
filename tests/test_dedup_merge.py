import uuid


def _create(client, *, source, url, company, description=None, source_id=None):
    response = client.post("/api/jobs", json={
        "title": "Senior Backend Engineer",
        "company": company,
        "location": "Remote Europe",
        "url": url,
        "source": source,
        "source_id": source_id,
        "description": description,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_cross_source_content_is_auto_merged(logged_in_client, db_conn):
    token = uuid.uuid4().hex
    company = f"Acme {token}"
    linkedin = _create(
        logged_in_client,
        source="linkedin",
        source_id=f"li-{token}",
        url=f"https://linkedin.com/jobs/view/{token}",
        company=company,
    )
    greenhouse = _create(
        logged_in_client,
        source="greenhouse",
        source_id=f"acme:{token}",
        url=f"https://boards.greenhouse.io/acme/jobs/{token}",
        company=company,
    )
    cur = db_conn.cursor()
    cur.execute(
        """INSERT INTO job_compensation_bands
               (job_id, amount_min, amount_max, currency, period, confidence)
           VALUES (%s, 100, 140, 'EUR', 'yearly', 0.8),
                  (%s, 110, 150, 'EUR', 'yearly', 0.9)""",
        (linkedin["job_id"], greenhouse["job_id"]),
    )
    db_conn.commit()

    description = "Build reliable distributed backend services in Python and PostgreSQL. " * 5
    first = logged_in_client.patch(
        f"/api/jobs/{linkedin['job_id']}/description", json={"description": description},
    )
    second = logged_in_client.patch(
        f"/api/jobs/{greenhouse['job_id']}/description", json={"description": description},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == greenhouse["job_id"]
    # greenhouse (an ATS source) outranks linkedin as survivor regardless of
    # insertion order - AUTO_MERGE_CONFIDENCE is low enough now (0.60) that
    # exact_content (0.94) auto-merges instead of waiting for admin review.
    aliases = logged_in_client.get(f"/api/jobs/{greenhouse['job_id']}/aliases").json()
    assert {alias["source"] for alias in aliases} == {"greenhouse", "linkedin"}
    cur.execute("SELECT COUNT(*) FROM job_postings WHERE id IN (%s, %s)", (linkedin["job_id"], greenhouse["job_id"]))
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM job_compensation_bands WHERE job_id = %s", (greenhouse["job_id"],))
    assert cur.fetchone()[0] == 2
    cur.execute(
        """SELECT status, survivor_job_id
           FROM job_dedup_matches
           WHERE job_id_low = LEAST(%s, %s) AND job_id_high = GREATEST(%s, %s)""",
        (linkedin["job_id"], greenhouse["job_id"], linkedin["job_id"], greenhouse["job_id"]),
    )
    # The first PATCH (linkedin's own description) already triggers the merge
    # the moment it sees greenhouse's still-old description - same company
    # and title is enough for identity_only (0.60) to clear the bar now, so
    # the pair never gets a chance to reach the stronger exact_content tier.
    assert cur.fetchone() == ("auto_merged", greenhouse["job_id"])


def test_uncertain_cross_source_match_is_auto_merged(logged_in_client, db_conn):
    # Same company + title, 40 of 48 description tokens shared (83%) clears
    # the identity_description_candidate bar (0.90) - AUTO_MERGE_CONFIDENCE
    # is low enough now (0.60) that this auto-merges on insert instead of
    # waiting in the review queue. second's own id never reaches the
    # caller once merged, so look its match up by first's id instead.
    token = uuid.uuid4().hex
    common = " ".join(f"shared{i}" for i in range(40))
    left_description = common + " alpha beta gamma delta"
    right_description = common + " epsilon zeta eta theta"
    first = _create(
        logged_in_client,
        source="jobicy",
        url=f"https://jobicy.example/{token}",
        company=f"Candidate {token}",
        description=left_description,
    )
    second = _create(
        logged_in_client,
        source="remotive",
        url=f"https://remotive.example/{token}",
        company=f"Candidate {token}",
        description=right_description,
    )

    assert second["job_id"] is None
    cur = db_conn.cursor()
    cur.execute(
        "SELECT status, confidence FROM job_dedup_matches WHERE %s IN (job_id_low, job_id_high)",
        (first["job_id"],),
    )
    status, confidence = cur.fetchone()
    assert status == "auto_merged"
    assert confidence == 0.9
    aliases = logged_in_client.get(f"/api/jobs/{first['job_id']}/aliases").json()
    assert {alias["source"] for alias in aliases} == {"jobicy", "remotive"}


def test_cross_source_matching_is_limited_to_21_days(logged_in_client, db_conn):
    token = uuid.uuid4().hex
    description = "Build reliable distributed backend services in Python and PostgreSQL. " * 5
    old = _create(
        logged_in_client,
        source="jobicy",
        url=f"https://jobicy.example/old-{token}",
        company=f"Old {token}",
        description=description,
    )
    cur = db_conn.cursor()
    cur.execute(
        """UPDATE job_postings
           SET created_at = CURRENT_TIMESTAMP - INTERVAL '22 days',
               posted_at = CURRENT_TIMESTAMP - INTERVAL '22 days'
           WHERE id = %s""",
        (old["job_id"],),
    )
    db_conn.commit()
    current = _create(
        logged_in_client,
        source="remotive",
        url=f"https://remotive.example/current-{token}",
        company=f"Old {token}",
        description=description,
    )

    assert old["job_id"] != current["job_id"]
    cur.execute(
        "SELECT COUNT(*) FROM job_dedup_matches WHERE job_id_low = LEAST(%s, %s) AND job_id_high = GREATEST(%s, %s)",
        (old["job_id"], current["job_id"], old["job_id"], current["job_id"]),
    )
    assert cur.fetchone()[0] == 0
