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


def test_exact_cross_source_content_is_queued_for_review(logged_in_client, db_conn):
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
    aliases = logged_in_client.get(f"/api/jobs/{greenhouse['job_id']}/aliases").json()
    assert {alias["source"] for alias in aliases} == {"greenhouse"}
    cur.execute("SELECT COUNT(*) FROM job_postings WHERE id IN (%s, %s)", (linkedin["job_id"], greenhouse["job_id"]))
    assert cur.fetchone()[0] == 2
    cur.execute("SELECT COUNT(*) FROM job_compensation_bands WHERE job_id = %s", (greenhouse["job_id"],))
    assert cur.fetchone()[0] == 1
    cur.execute(
        """SELECT status, survivor_job_id, match_method
           FROM job_dedup_matches
           WHERE job_id_low = LEAST(%s, %s) AND job_id_high = GREATEST(%s, %s)""",
        (linkedin["job_id"], greenhouse["job_id"], linkedin["job_id"], greenhouse["job_id"]),
    )
    assert cur.fetchone() == ("candidate", None, "exact_content")


def test_uncertain_cross_source_match_is_recorded_without_merge(logged_in_client, db_conn):
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

    assert first["job_id"] != second["job_id"]
    cur = db_conn.cursor()
    cur.execute(
        """SELECT status, confidence FROM job_dedup_matches
           WHERE job_id_low = LEAST(%s, %s) AND job_id_high = GREATEST(%s, %s)""",
        (first["job_id"], second["job_id"], first["job_id"], second["job_id"]),
    )
    status, confidence = cur.fetchone()
    assert status == "candidate"
    assert confidence == 0.9


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
