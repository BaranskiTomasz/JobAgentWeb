import pytest

import automation_keys_repo
import jobs_repo


_FACTS = {
    "schema_version": 1,
    "model": "test-model",
    "content_hash": "hash",
    "facts": {},
    "provenance": {},
}


@pytest.fixture
def shared_job_id(db_conn):
    result = jobs_repo.insert(
        db_conn,
        None,
        {
            "title": "Shared job",
            "url": "https://example.com/shared-catalog-job",
            "source": "test",
        },
        attach_to_user=False,
    )
    db_conn.commit()
    return result["job_id"]


@pytest.mark.parametrize(
    "method,path_template,body",
    [
        ("get", "/api/jobs/catalog/missing-facts?schema_version=1", None),
        ("get", "/api/jobs/catalog/urls", None),
        (
            "post",
            "/api/jobs/catalog",
            {"title": "New shared", "url": "https://example.com/new-shared"},
        ),
        (
            "patch",
            "/api/jobs/catalog/{job_id}/description",
            {"description": "Updated"},
        ),
        ("put", "/api/jobs/catalog/{job_id}/facts", _FACTS),
    ],
)
def test_catalog_routes_reject_unscoped_database_key(
    client, user, db_conn, shared_job_id, method, path_template, body,
):
    _, raw_key = automation_keys_repo.create(db_conn, user["id"], "unscoped")
    db_conn.commit()
    response = getattr(client, method)(
        path_template.format(job_id=shared_job_id),
        headers={"X-JobAgent-Api-Key": raw_key},
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Catalog automation client only"}


@pytest.mark.parametrize(
    "method,path_template,body",
    [
        ("get", "/api/jobs/catalog/missing-facts?schema_version=1", None),
        ("get", "/api/jobs/catalog/urls", None),
        (
            "post",
            "/api/jobs/catalog",
            {"title": "New shared", "url": "https://example.com/scoped-new"},
        ),
        (
            "patch",
            "/api/jobs/catalog/{job_id}/description",
            {"description": "Updated"},
        ),
        ("put", "/api/jobs/catalog/{job_id}/facts", _FACTS),
    ],
)
def test_catalog_routes_accept_scoped_database_key(
    client, user, db_conn, shared_job_id, method, path_template, body,
):
    _, raw_key = automation_keys_repo.create(
        db_conn, user["id"], "scoped", can_access_catalog=True,
    )
    db_conn.commit()
    response = getattr(client, method)(
        path_template.format(job_id=shared_job_id),
        headers={"X-JobAgent-Api-Key": raw_key},
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code < 300, response.text
    cur = db_conn.cursor()
    if method == "post":
        cur.execute("SELECT id FROM job_postings WHERE url = %s", (body["url"],))
        new_job_id = cur.fetchone()[0]
        cur.execute("SELECT 1 FROM user_job_states WHERE job_id = %s", (new_job_id,))
        assert cur.fetchone() is None
    elif method == "patch":
        cur.execute("SELECT description FROM job_postings WHERE id = %s", (shared_job_id,))
        assert cur.fetchone() == (body["description"],)
    elif method == "put":
        cur.execute("SELECT job_id FROM job_fact_extractions WHERE job_id = %s", (shared_job_id,))
        assert cur.fetchone() == (shared_job_id,)


@pytest.mark.parametrize(
    "method,path_template,body",
    [
        ("get", "/api/jobs/catalog/missing-facts?schema_version=1", None),
        ("get", "/api/jobs/catalog/urls", None),
        ("post", "/api/jobs/catalog", {"title": "Legacy", "url": "https://example.com/legacy"}),
        ("patch", "/api/jobs/catalog/{job_id}/description", {"description": "Legacy update"}),
        ("put", "/api/jobs/catalog/{job_id}/facts", _FACTS),
    ],
)
def test_catalog_routes_keep_full_legacy_key_access(
    client, user, shared_job_id, method, path_template, body, monkeypatch,
):
    monkeypatch.setattr("deps.JOBAGENT_API_KEY", "legacy-key")
    monkeypatch.setattr("deps.JOBAGENT_API_KEY_USER_ID", str(user["id"]))
    response = getattr(client, method)(
        path_template.format(job_id=shared_job_id),
        headers={"X-JobAgent-Api-Key": "legacy-key"},
        **({"json": body} if body is not None else {}),
    )
    assert response.status_code < 300, response.text


def test_unscoped_key_can_use_collection_status(client, user, db_conn):
    _, raw_key = automation_keys_repo.create(db_conn, user["id"], "unscoped")
    db_conn.commit()
    response = client.get(
        "/api/catalog/collection/status",
        headers={"X-JobAgent-Api-Key": raw_key},
    )
    assert response.status_code == 200


def test_personal_facts_key_is_scoped_to_owned_posting(
    client, user, other_user, db_conn,
):
    owned = jobs_repo.insert(
        db_conn,
        user["id"],
        {"title": "Owned", "company": "Acme", "url": "https://example.com/owned"},
    )["job_id"]
    foreign = jobs_repo.insert(
        db_conn,
        other_user["id"],
        {"title": "Foreign", "company": "Acme", "url": "https://example.com/foreign"},
    )["job_id"]
    _, raw_key = automation_keys_repo.create(db_conn, user["id"], "facts")
    db_conn.commit()
    headers = {"X-JobAgent-Api-Key": raw_key}
    accepted = client.put(f"/api/jobs/{owned}/facts", headers=headers, json=_FACTS)
    rejected = client.put(f"/api/jobs/{foreign}/facts", headers=headers, json=_FACTS)
    assert accepted.status_code == 200
    assert rejected.status_code == 404
    cur = db_conn.cursor()
    cur.execute("SELECT job_id FROM job_fact_extractions")
    assert cur.fetchall() == [(owned,)]
