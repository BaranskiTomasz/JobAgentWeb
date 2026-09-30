from jobs_repo import _description_similarity, canonicalize_url, content_fingerprint, identity_fingerprint


def test_canonicalize_url_removes_tracking_and_normalizes_origin():
    assert canonicalize_url("http://www.Example.com:80/jobs/1/?utm_source=x") == "https://example.com/jobs/1"


def test_canonicalize_url_preserves_potentially_functional_ref_parameter():
    assert canonicalize_url("https://example.com/jobs/1?ref=feed") == "https://example.com/jobs/1?ref=feed"


def test_identity_fingerprint_ignores_case_and_diacritics():
    first = {"title": "Senior Backend Engineer", "company": "Żółta Firma"}
    second = {"title": "senior backend engineer", "company": "Zolta Firma"}
    assert identity_fingerprint(first) == identity_fingerprint(second)


def test_identity_fingerprint_ignores_company_punctuation():
    first = {"title": "Senior Python Engineer", "company": "Acme Sp. z o.o."}
    second = {"title": "Senior Python Engineer", "company": "ACME SP Z O O"}
    assert identity_fingerprint(first) == identity_fingerprint(second)


def test_description_similarity_accepts_small_cross_source_edits():
    base = " ".join(f"technology{i}" for i in range(35))
    assert _description_similarity(base + " greenhouse", base + " linkedin") > 0.9


def test_description_similarity_rejects_different_vacancies():
    backend = " ".join(f"backend{i}" for i in range(30))
    frontend = " ".join(f"frontend{i}" for i in range(30))
    assert _description_similarity(backend, frontend) == 0.0


def test_content_fingerprint_includes_location_and_description():
    base = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Remote EU",
        "description": " ".join(f"word{i}" for i in range(30)),
    }
    assert content_fingerprint(base) != content_fingerprint({**base, "location": "Remote US"})
