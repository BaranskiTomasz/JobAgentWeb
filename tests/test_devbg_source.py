from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from collectors.sources.devbg import DevBGSource

_NOW = datetime.now(timezone.utc)


def _term(name, taxonomy):
    return {"name": name, "taxonomy": taxonomy}


def _listing(job_id=1, title="Machine Learning Engineer", slug="experian-machine-learning-engineer",
             content="<section><p class=\"title\"><strong>Experian</strong> is a global data and technology company.</p></section>",
             terms=None, days_old=1):
    terms = terms if terms is not None else [
        _term("2-5 години опит", "seniority"),
        _term("Data Science", "job_listing_category"),
        _term("Hybrid", "job_listings_tag"),
        _term("София", "job_listings_tag"),
        _term("AWS", "techstack"),
        _term("Python", "techstack"),
    ]
    return {
        "id": job_id,
        "title": {"rendered": title},
        "content": {"rendered": content},
        "link": f"https://dev.bg/company/jobads/{slug}/",
        "date_gmt": (_NOW - timedelta(days=days_old)).strftime("%Y-%m-%dT%H:%M:%S"),
        "_embedded": {"wp:term": [terms]},
    }


def _mock_response(payload, status_code=200, total_pages=1):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.headers = {"X-WP-TotalPages": str(total_pages)}
    return response


def _source_with(get_side_effect):
    source = DevBGSource(days_back=14)
    client = MagicMock()
    client.get.side_effect = get_side_effect
    with patch("collectors.sources.devbg.httpx.Client", return_value=client):
        source.__enter__()
    return source


def test_maps_real_listing_shape_to_rawjob():
    # Shapes verified live against https://dev.bg/wp-json/wp/v2/job-listings
    # on 2026-10-17: seniority/job_listings_tag/techstack are the real
    # taxonomy names, there is no company or location/city taxonomy.
    source = _source_with([_mock_response([_listing()])])
    results = source.search("Machine Learning Engineer", "Bulgaria")

    assert len(results) == 1
    job = results[0]
    assert job.title == "Machine Learning Engineer"
    assert job.source == "devbg"
    assert job.source_id == "1"
    assert "София" in job.location
    assert "Bulgaria" in job.location
    assert job.source_structured_data["seniority"] == "mid"
    assert job.source_structured_data["hybrid"] is True
    assert set(job.source_structured_data["stack"]) == {"AWS", "Python"}
    assert job.source_structured_data["country_eligibility"][0]["country_code"] == "BG"


def test_company_is_always_empty_no_reliable_source_signal():
    # Verified live (2026-10-17): DEV.BG's API exposes no company field or
    # taxonomy. A <strong>-tag heuristic was tried and rejected after live
    # testing showed it frequently captures a marketing tagline instead of
    # the employer name; a wrong value here is worse than an empty one
    # because it would feed JobAgentWeb's dedup company-alias matching.
    source = _source_with([_mock_response([_listing()])])
    results = source.search("Machine Learning Engineer", "Bulgaria")
    assert results[0].company == ""


def test_remote_detected_via_fallback_term_scan():
    listing = _listing(terms=[_term("Fully Remote", "job_listings_tag")])
    source = _source_with([_mock_response([listing])])
    results = source.search("Machine Learning Engineer", "Bulgaria")
    assert results[0].source_structured_data["remote"] is True


def test_paginates_across_multiple_pages():
    page1 = _mock_response([_listing(job_id=1, slug="job-one")], total_pages=2)
    page2 = _mock_response([_listing(job_id=2, slug="job-two")], total_pages=2)
    source = _source_with([page1, page2])
    results = source.search("Machine Learning Engineer", "Bulgaria")
    assert {r.source_id for r in results} == {"1", "2"}


def test_known_urls_are_filtered_out():
    listing = _listing(job_id=1, slug="experian-machine-learning-engineer")
    source = _source_with([_mock_response([listing])])
    known = {"https://dev.bg/company/jobads/experian-machine-learning-engineer/"}
    results = source.search("Machine Learning Engineer", "Bulgaria", known_urls=known)
    assert results == []


def test_old_listing_excluded_by_days_back():
    listing = _listing(days_old=30)
    source = _source_with([_mock_response([listing])])
    results = source.search("Machine Learning Engineer", "Bulgaria", days_back=7)
    assert results == []


def test_http_error_returns_empty_without_raising():
    source = _source_with([_mock_response([], status_code=500)])
    results = source.search("Machine Learning Engineer", "Bulgaria")
    assert results == []
    assert source.last_search_diagnostics["source_status"] == "error"


def test_malformed_response_returns_empty_without_raising():
    source = _source_with([_mock_response({"not": "a list"})])
    results = source.search("Machine Learning Engineer", "Bulgaria")
    assert results == []
