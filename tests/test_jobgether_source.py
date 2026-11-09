"""Tests for the Jobgether catalog source integration."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx

from collectors.catalog_runner import run_catalog_collection
from collectors.sources import available, make
from collectors.sources.jobgether import JobgetherSource
from catalog import CLASSIFIER_VERSION, classify_catalog_job

_NOW = datetime.now(timezone.utc)


def _real_jobgether_job(
    job_id="6aecd97c1c8aea01fb8927af",
    title="Senior Python Developer",
    company="EPAM Systems",
    location="Europe, European Union, EMEA, Poland",
    remote="Full Remote",
    days_old=1,
    url="https://jobgether.com/offer/6aecd97c1c8aea01fb8927af-senior-python-developer",
):
    # Shape verified live against https://jobgether.com/astroapi/ai/jobs.json on 2026-11-09.
    return {
        "id": job_id,
        "title": title,
        "company": company,
        "url": url,
        "location": location,
        "remote": remote,
        "contractType": "Full time",
        "experience": "Senior (5-10 years)",
        "salaryRange": "150000-160000 USD",
        "jobFunctions": ["Python Developer"],
        "postedAt": (_NOW - timedelta(days=days_old)).isoformat(),
    }


def _mock_json_response(payload, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = str(payload)
    return response


def _mock_html_response(html: str, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = html
    return response


def test_maps_real_captured_payload_to_rawjob():
    # AC2: maps real payload to RawJob with source="jobgether", non-empty company,
    # offer page url, posted_at, and source_structured_data.
    job_payload = _real_jobgether_job()
    api_payload = {
        "jobs": [job_payload],
        "pagination": {"page": 1, "limit": 25, "hasMore": False},
        "browseOnSiteUrl": "https://jobgether.com/search-offers?...",
        "docs": "/astroapi/ai/jobs/docs",
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response(api_payload)

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland")

    assert len(results) == 1
    raw = results[0]
    assert raw.title == "Senior Python Developer"
    assert raw.company == "EPAM Systems"
    assert raw.location == "Europe, European Union, EMEA, Poland"
    assert raw.url == "https://jobgether.com/offer/6aecd97c1c8aea01fb8927af-senior-python-developer"
    assert raw.source == "jobgether"
    assert raw.source_id == "6aecd97c1c8aea01fb8927af"
    assert raw.description is None
    assert raw.posted_at is not None
    assert raw.source_structured_data == {
        "remote": True,
        "remote_available": True,
        "remote_regions": ["Europe", "European Union", "EMEA", "Poland"],
        "contract_type": "Full time",
        "experience": "Senior (5-10 years)",
        "salary_range": "150000-160000 USD",
    }


def test_requests_astroapi_endpoint_with_safe_parameters_and_normalizes_location():
    # AC2, AC2a: requests only https://jobgether.com/astroapi/ai/jobs.json (never /api/v1/jobs)
    # asserts limit<=25, page<=10, and case-/whitespace-insensitive location slug lookup.
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response({"jobs": [], "pagination": {"hasMore": False}})

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            # Test exact title-case string passed by catalog_runner.CATALOG_COUNTRIES ("Poland")
            source.search("Python Developer", "Poland")
            # Test with whitespace and mixed casing
            source.search("Python Developer", " poland ")

    assert mock_client.get.call_count == 2
    for call in mock_client.get.call_args_list:
        url = call[0][0] if call[0] else call[1].get("url")
        assert url == "https://jobgether.com/astroapi/ai/jobs.json"
        assert "/api/v1/jobs" not in url

        params = call[1].get("params", {})
        assert params.get("locations") == "poland"
        assert params.get("limit") <= 25
        assert params.get("page") <= 10
        assert params.get("sort") == "date"


def test_remote_regions_split_and_remote_available_flag():
    # AC2: remote_regions is the split list, remote_available true only for "Full Remote"
    job_full = _real_jobgether_job(job_id="1", location="Europe, Poland", remote="Full Remote")
    job_partial = _real_jobgether_job(job_id="2", location="Bulgaria", remote="Hybrid Remote", url="https://jobgether.com/offer/2")
    api_payload = {
        "jobs": [job_full, job_partial],
        "pagination": {"page": 1, "limit": 25, "hasMore": False},
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response(api_payload)

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland")

    assert len(results) == 1
    assert results[0].source_structured_data["remote_regions"] == ["Europe", "Poland"]
    assert results[0].source_structured_data["remote_available"] is True


def test_posting_older_than_days_back_is_excluded():
    # AC2: cutoff check
    old_job = _real_jobgether_job(days_old=10)
    api_payload = {
        "jobs": [old_job],
        "pagination": {"page": 1, "limit": 25, "hasMore": False},
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response(api_payload)

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland")

    assert results == []
    assert getattr(source, "last_search_diagnostics", {}).get("date_matched") == 0


def test_known_urls_member_is_filtered_and_counted_in_diagnostics():
    # AC2: known_urls filtering
    job = _real_jobgether_job()
    api_payload = {
        "jobs": [job],
        "pagination": {"page": 1, "limit": 25, "hasMore": False},
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response(api_payload)

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland", known_urls={job["url"]})

    assert results == []
    diag = getattr(source, "last_search_diagnostics", {})
    assert diag.get("known_url_filtered") == 1
    assert diag.get("geo_matched") == 1
    assert diag.get("source_returned") == 0


def test_location_matches_rejects_us_only_posting_for_poland():
    # AC2: geo stage rejects US-only posting
    job = _real_jobgether_job(location="United States")
    api_payload = {
        "jobs": [job],
        "pagination": {"page": 1, "limit": 25, "hasMore": False},
    }

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.return_value = _mock_json_response(api_payload)

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland")

    assert results == []
    diag = getattr(source, "last_search_diagnostics", {})
    assert diag.get("geo_matched") == 0


def test_fetch_description_extracts_ld_json_jobposting_and_handles_missing():
    # AC3: returns posting text parsed from schema.org/JobPosting ld+json
    html_with_ld = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Senior Python Developer",
          "description": "<p>We are looking for a <strong>Senior Python Developer</strong>.</p><br>Experience with FastAPI required."
        }
        </script>
      </head>
      <body></body>
    </html>
    """
    html_without_ld = "<html><head></head><body>No jobs here</body></html>"

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    mock_client.get.side_effect = [
        _mock_html_response(html_with_ld),
        _mock_html_response(html_without_ld),
    ]

    source = JobgetherSource()
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        desc = source.fetch_description("https://jobgether.com/offer/1")
        assert desc is not None
        assert "We are looking for a Senior Python Developer." in desc
        assert "Experience with FastAPI required." in desc

        desc_none = source.fetch_description("https://jobgether.com/offer/2")
        assert desc_none is None


def test_fetch_description_works_outside_with_block_on_never_entered_and_exited_instances():
    # AC3a: fetch_description works when called outside source's with block,
    # on an instance that was never entered and on an exited one.
    html_with_ld = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "description": "<p>Description content</p>"
        }
        </script>
      </head>
    </html>
    """

    # 1. Never entered instance
    source_never_entered = JobgetherSource()
    mock_client_1 = MagicMock(spec=httpx.Client)
    mock_client_1.is_closed = False
    mock_client_1.get.return_value = _mock_html_response(html_with_ld)

    with patch.object(source_never_entered, "_new_client", return_value=mock_client_1), patch("time.sleep"):
        desc1 = source_never_entered.fetch_description("https://jobgether.com/offer/1")
        assert desc1 == "Description content"
        mock_client_1.close.assert_called_once()

    # 2. Exited instance
    source_exited = JobgetherSource()
    mock_client_entered = MagicMock(spec=httpx.Client)
    mock_client_entered.is_closed = False

    with patch.object(source_exited, "_new_client", return_value=mock_client_entered):
        with source_exited:
            pass
        assert source_exited._client is None

    mock_client_2 = MagicMock(spec=httpx.Client)
    mock_client_2.is_closed = False
    mock_client_2.get.return_value = _mock_html_response(html_with_ld)

    with patch.object(source_exited, "_new_client", return_value=mock_client_2), patch("time.sleep"):
        desc2 = source_exited.fetch_description("https://jobgether.com/offer/2")
        assert desc2 == "Description content"
        mock_client_2.close.assert_called_once()


def test_400_invalid_parameter_retries_once_without_locations_then_records_partial():
    # AC10: a 400 invalid_parameter retries once without locations, then returns [] with source_status="partial"
    resp_400 = MagicMock(spec=httpx.Response)
    resp_400.status_code = 400
    resp_400.json.return_value = {
        "type": "/astroapi/ai/jobs/docs#invalid_parameter",
        "title": "Invalid parameter",
        "status": 400,
        "detail": 'Invalid value for \'locations\': "poland"',
        "code": "invalid_parameter",
        "field": "locations",
    }
    resp_400.text = "Invalid value for locations"

    mock_client = MagicMock(spec=httpx.Client)
    mock_client.is_closed = False
    # Return 400 on the first call (with locations), and 400 again on retry (without locations)
    mock_client.get.side_effect = [resp_400, resp_400]

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client), patch("time.sleep"):
        with source:
            results = source.search("Python Developer", "Poland")

    assert results == []
    assert mock_client.get.call_count == 2
    first_call_params = mock_client.get.call_args_list[0][1]["params"]
    assert "locations" in first_call_params
    second_call_params = mock_client.get.call_args_list[1][1]["params"]
    assert "locations" not in second_call_params

    diag = getattr(source, "last_search_diagnostics", {})
    assert diag.get("source_status") == "partial"


def test_httpx_error_and_non_json_body_return_empty_without_raising():
    # AC10: httpx.HTTPError and non-JSON body return [] without raising
    # 1. HTTP error
    mock_client_err = MagicMock(spec=httpx.Client)
    mock_client_err.is_closed = False
    mock_client_err.get.side_effect = httpx.ConnectError("Connection refused")

    source = JobgetherSource(days_back=7)
    with patch.object(source, "_new_client", return_value=mock_client_err), patch("time.sleep"):
        with source:
            res1 = source.search("Python Developer", "Poland")
    assert res1 == []
    assert getattr(source, "last_search_diagnostics", {}).get("source_status") == "error"

    # 2. Non-JSON body
    resp_bad_json = MagicMock(spec=httpx.Response)
    resp_bad_json.status_code = 200
    resp_bad_json.json.side_effect = ValueError("Invalid JSON")
    resp_bad_json.text = "Not JSON at all"

    mock_client_bad = MagicMock(spec=httpx.Client)
    mock_client_bad.is_closed = False
    mock_client_bad.get.return_value = resp_bad_json

    source2 = JobgetherSource(days_back=7)
    with patch.object(source2, "_new_client", return_value=mock_client_bad), patch("time.sleep"):
        with source2:
            res2 = source2.search("Python Developer", "Poland")
    assert res2 == []
    assert getattr(source2, "last_search_diagnostics", {}).get("source_status") == "error"


def test_classify_catalog_job_with_captured_jobgether_payload():
    # AC4: A Jobgether posting advertising Poland or an EU/EEA/worldwide region
    # classifies with work_countries containing PL through unchanged classify_catalog_job.
    job_dict = {
        "title": "Senior Python Developer",
        "description": "We are seeking a Python Developer with experience in Django, FastAPI and PostgreSQL.",
        "location": "Europe, European Union, EMEA, Poland",
        "source": "jobgether",
        "source_structured_data": {
            "remote": True,
            "remote_available": True,
            "remote_regions": ["Europe", "European Union", "EMEA", "Poland"],
            "contract_type": "Full time",
            "experience": "Senior (5-10 years)",
            "salary_range": "150000-160000 USD",
        },
    }

    result = classify_catalog_job(job_dict)
    assert "PL" in result["work_countries"]
    assert result["is_public"] is True
    assert CLASSIFIER_VERSION == 6


def test_jobgether_registered_in_sources():
    # AC1: jobgether is in available() and can be instantiated via make()
    assert "jobgether" in available()
    instance = make("jobgether")
    assert isinstance(instance, JobgetherSource)
    assert instance.name == "jobgether"
