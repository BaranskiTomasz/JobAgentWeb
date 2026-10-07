from source_identity import (
    company_alias,
    identity_aliases,
    requisition_identity,
    source_identity,
    title_aliases,
)


def test_ats_source_ids_are_provider_scoped_and_stable():
    job = {"source": "Greenhouse", "source_id": "Acme-Board:12345", "company": "Acme, Inc.", "title": "Sr. Software Engineer"}
    identity = requisition_identity(job)
    assert identity is not None
    assert identity.key == "greenhouse:acme-board:12345"
    assert source_identity(job) == identity.key
    assert identity.company_key == "acme"
    assert identity.title_key == "senior software engineer"


def test_url_is_fallback_when_adapter_has_no_source_id():
    job = {"source": "ashby", "url": "https://jobs.example.com/posting/ABC-123", "company": "Example GmbH", "title": "Backend Engineer"}
    assert source_identity(job) == "ashby:abc-123"
    assert company_alias("Example GmbH") == "example"


def test_title_aliases_are_conservative():
    assert title_aliases("Backend Engineer") == {"backend engineer"}
    assert "senior" in identity_aliases({"source": "lever", "source_id": "x-1", "title": "Sr Engineer", "company": "A"})["title_aliases"][0]


def test_missing_identity_is_not_fabricated():
    assert source_identity({"source": "linkedin", "source_id": "", "url": "https://www.linkedin.com/jobs/view/"}) is None
