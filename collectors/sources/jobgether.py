"""Jobgether source, public JSON API for AI agents (no auth required)."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx

from collectors.base import JobSource, RawJob
from collectors.location import location_matches
from collectors.query_matcher import job_matches_query_with_focused_description
from collectors.utils import strip_html

logger = logging.getLogger(__name__)

_API_URL = "https://jobgether.com/astroapi/ai/jobs.json"
_HEADERS = {
    "User-Agent": "JobAgent/1.0 (job aggregator)",
    "Accept": "application/json",
}
_CRAWL_DELAY_SECONDS = 2.0
_MAX_LIMIT = 25
_MAX_PAGES = 3
_LOCATION_SLUGS = {
    "poland": "poland",
    "bulgaria": "bulgaria",
}


def _published_at(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


class JobgetherSource(JobSource):
    requires_stealth_pauses = False

    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None

    @property
    def name(self) -> str:
        return "jobgether"

    def _new_client(self) -> httpx.Client:
        return httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True)

    def __enter__(self):
        self._client = self._new_client()
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
        self._client = None

    def login(self) -> None:
        pass

    def fetch_description(self, url: str) -> str | None:
        # Both callers run this outside the `with` block: catalog_runner drains
        # its `pending` list after __exit__, and JobAgent's _fetch_one never
        # enters the source at all. Fall back to a standalone client.
        client = self._client
        owned = client is None or client.is_closed
        if owned:
            client = self._new_client()
        try:
            time.sleep(_CRAWL_DELAY_SECONDS)
            resp = client.get(url)
        except httpx.HTTPError:
            return None
        finally:
            if owned:
                client.close()

        if resp.status_code != 200:
            return None

        # Look for <script type="application/ld+json"> blocks with @type JobPosting
        scripts = re.findall(
            r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>',
            resp.text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        for script_content in scripts:
            try:
                data = json.loads(script_content)
            except Exception:
                continue

            candidates = data if isinstance(data, list) else [data]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("@type")
                if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
                    desc = item.get("description")
                    if desc:
                        return strip_html(desc)
        return None

    def search(
        self,
        title: str,
        location: str,
        days_back: int | None = None,
        max_results: int | None = None,
        known_urls: set[str] | None = None,
    ) -> list[RawJob]:
        days = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        location_slug = _LOCATION_SLUGS.get(location.strip().casefold())

        client = self._client
        owned = client is None or client.is_closed
        if owned:
            client = self._new_client()

        raw_jobs: list[dict] = []
        try:
            page = 1
            retry_without_location = False
            while page <= _MAX_PAGES:
                params: dict[str, str | int] = {
                    "keyword": title,
                    "sort": "date",
                    "limit": _MAX_LIMIT,
                    "page": page,
                }
                if location_slug and not retry_without_location:
                    params["locations"] = location_slug

                time.sleep(_CRAWL_DELAY_SECONDS)
                try:
                    resp = client.get(_API_URL, params=params)
                except httpx.HTTPError as exc:
                    logger.warning("Jobgether request failed: %s", exc)
                    self.set_search_diagnostics(
                        source_status="error",
                        source_error=str(exc)[:1000],
                        upstream_found=0,
                    )
                    return []

                if resp.status_code == 400:
                    try:
                        error_data = resp.json()
                    except Exception:
                        error_data = {}
                    if error_data.get("code") == "invalid_parameter" and location_slug and not retry_without_location:
                        logger.warning("Jobgether 400 invalid_parameter for locations=%s; retrying once without locations", location_slug)
                        retry_without_location = True
                        continue
                    # Either not invalid_parameter, or already retried without locations
                    self.set_search_diagnostics(
                        source_status="partial",
                        source_error=f"HTTP 400: {resp.text[:1000]}",
                        upstream_found=len(raw_jobs),
                    )
                    return []

                if resp.status_code != 200:
                    self.set_search_diagnostics(
                        source_status="error",
                        source_error=f"HTTP {resp.status_code}: {resp.text[:1000]}",
                        upstream_found=len(raw_jobs),
                    )
                    return []

                try:
                    payload = resp.json()
                except Exception as exc:
                    self.set_search_diagnostics(
                        source_status="error",
                        source_error=f"JSON decode error: {exc}",
                        upstream_found=len(raw_jobs),
                    )
                    return []

                jobs_list = payload.get("jobs", []) if isinstance(payload, dict) else []
                if isinstance(jobs_list, list):
                    for item in jobs_list:
                        if isinstance(item, dict):
                            raw_jobs.append(item)
                        else:
                            logger.warning("Jobgether: skipping malformed job item (not a dict): %r", item)

                pagination = payload.get("pagination") if isinstance(payload, dict) else {}
                has_more = pagination.get("hasMore", False) if isinstance(pagination, dict) else False
                if not has_more or (max_results and len(raw_jobs) >= max_results):
                    break
                page += 1
        finally:
            if owned:
                client.close()

        # Filtering in Remotive order:
        # 1. job_matches_query_with_focused_description
        # 2. postedAt within days_back
        # 3. location_matches(job["location"], location)
        # 4. known_urls
        results: list[RawJob] = []
        query_matched = 0
        date_matched = 0
        geo_matched = 0
        known_url_filtered = 0

        for job in raw_jobs:
            if max_results and len(results) >= max_results:
                break

            job_title = job.get("title") or ""
            # List payload description is not provided, query matcher handles details=None
            if not job_matches_query_with_focused_description(title, job_title, None):
                continue
            query_matched += 1

            pub_dt = _published_at(job.get("postedAt"))
            if pub_dt is None or pub_dt < cutoff:
                continue
            date_matched += 1

            job_loc = job.get("location") or ""
            if not location_matches(job_loc, location):
                continue
            geo_matched += 1

            url = job.get("url") or ""
            if not url:
                continue

            if known_urls and url in known_urls:
                known_url_filtered += 1
                continue

            remote_regions = [part.strip() for part in job_loc.split(",") if part.strip()]
            results.append(
                RawJob(
                    title=job_title,
                    company=job.get("company") or "",
                    location=job_loc,
                    url=url,
                    source="jobgether",
                    source_id=str(job.get("id")) if job.get("id") else None,
                    description=None,
                    posted_at=pub_dt.isoformat(),
                    source_structured_data={
                        "remote": True,
                        "remote_available": job.get("remote") == "Full Remote",
                        "remote_regions": remote_regions,
                        "contract_type": job.get("contractType"),
                        "experience": job.get("experience"),
                        "salary_range": job.get("salaryRange"),
                    },
                )
            )

        self.set_search_diagnostics(
            upstream_found=len(raw_jobs),
            query_matched=query_matched,
            date_matched=date_matched,
            geo_matched=geo_matched,
            source_returned=len(results),
            known_url_filtered=known_url_filtered,
            source_status="ok",
        )
        return results
