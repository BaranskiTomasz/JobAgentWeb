"""DEV.BG source backed by its public WordPress REST API."""
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx

from collectors.base import JobSource, RawJob
from collectors.location import workplace_suffix
from collectors.query_matcher import job_matches_query_with_focused_description
from collectors.utils import strip_html

logger = logging.getLogger(__name__)

_API_URL = "https://dev.bg/wp-json/wp/v2/job-listings"
_PAGE_SIZE = 100
_MAX_PAGES = 100
_HEADERS = {"User-Agent": "JobAgent/1.0 (job aggregator)"}

# Verified live against the real API (2026-10-17): work-mode and city names
# are both plain term names inside the single "job_listings_tag" taxonomy,
# there is no separate location/city taxonomy to filter on. These are the
# work-mode values actually observed; anything else in that taxonomy is a
# city name (e.g. "София", "Пловдив", "Варна", "Русе") or a language/skill
# tag, in which case it's still useful to keep as a stack/location hint but
# is not itself a work-mode signal.
_WORK_MODE_TERMS = {"hybrid", "fully remote", "remote", "on-site", "onsite"}


def _url_key(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))


def _embedded_terms(job: dict) -> list[dict]:
    terms = []
    for value in (job.get("_embedded") or {}).values():
        groups = value if isinstance(value, list) else []
        for group in groups:
            candidates = group if isinstance(group, list) else [group]
            terms.extend(term for term in candidates if isinstance(term, dict) and term.get("name"))
    return terms


def _company(job: dict, terms: list[dict]) -> str:
    # DEV.BG's API has no company field, acf block, or company taxonomy
    # (verified live, 2026-10-17: a real listing's top-level keys are just
    # title/content/excerpt/date_gmt/link/id/seniority/techstack/
    # job-categories/job_listings_tag, acf is always an empty list). A
    # leading <strong> tag in the content was tried as a heuristic but
    # rejected: verified live against real listings, it frequently captures
    # a marketing tagline ("We have awesome plans for you!") instead of the
    # employer name, with no reliable way to tell the two apart from markup
    # alone. A wrong company string here is worse than an empty one: it
    # feeds company-alias matching in JobAgentWeb's dedup logic and a wrong
    # value risks false merges or false splits. Leave it empty and let
    # Haiku extraction (which reads the full description) resolve it.
    for term in terms:
        taxonomy = str(term.get("taxonomy") or "").casefold()
        if "company" in taxonomy or "employer" in taxonomy:
            return str(term["name"]).strip()
    return ""


def _terms_for(terms: list[dict], *markers: str) -> list[str]:
    return [
        str(term["name"]).strip()
        for term in terms
        if any(marker in str(term.get("taxonomy") or "").casefold() for marker in markers)
    ]


def _source_data(terms: list[dict]) -> tuple[dict, list[str], set[str]]:
    tech = _terms_for(terms, "techstack", "tech_stack", "technology", "skill")
    seniority_terms = _terms_for(terms, "seniority", "experience", "level")
    # Verified live: city and work-mode names both live in the single
    # "job_listings_tag" taxonomy (e.g. this taxonomy's terms for one real
    # listing were "Hybrid" and "София" together). Split by checking against
    # the known work-mode vocabulary rather than filtering by taxonomy name,
    # which doesn't distinguish them.
    tag_terms = _terms_for(terms, "job_listings_tag", "tag")
    work_terms = [t for t in tag_terms if t.casefold() in _WORK_MODE_TERMS]
    location_terms = [t for t in tag_terms if t.casefold() not in _WORK_MODE_TERMS]
    all_names = [str(term["name"]).strip() for term in terms]

    modes: set[str] = set()
    for term in [*work_terms, *all_names]:
        normalized = term.casefold()
        if "remote" in normalized or "дистан" in normalized:
            modes.add("remote")
        if "hybrid" in normalized or "хибрид" in normalized:
            modes.add("hybrid")

    data: dict = {
        "country_eligibility": [{
            "country_code": "BG", "eligible": True, "engagement_modes": ["unknown"],
            "evidence": "DEV.BG listing: Bulgaria-based or remote-open-to-Bulgaria.",
        }],
    }
    if tech:
        data["stack"] = list(dict.fromkeys(tech))
    seniority = ""
    for term in seniority_terms:
        normalized = term.casefold()
        if "team lead" in normalized or "lead" in normalized:
            seniority = "lead"
        elif "5+" in normalized or "5 +" in normalized:
            seniority = "senior"
        elif "2-5" in normalized or "2 – 5" in normalized or "2–5" in normalized:
            seniority = "mid"
        elif "junior" in normalized or "intern" in normalized:
            seniority = "junior"
        if seniority:
            break
    if seniority:
        data["seniority"] = seniority
    if "remote" in modes:
        data.update({"remote": True, "remote_available": True, "remote_regions": ["Bulgaria"]})
    if "hybrid" in modes:
        data.update({"hybrid": True, "hybrid_available": True})
    return data, location_terms, modes


class DevBGSource(JobSource):
    def __init__(self, days_back: int = 7, **_):
        self._days_back = days_back
        self._client: httpx.Client | None = None
        self._listings_cache: tuple[list[dict], int, str | None] | None = None
        self.last_search_diagnostics = {}

    @property
    def name(self) -> str:
        return "devbg"

    def __enter__(self):
        self._client = httpx.Client(headers=_HEADERS, timeout=30, follow_redirects=True)
        return self

    def __exit__(self, *_):
        if self._client:
            self._client.close()
        self._client = None
        self._listings_cache = None
        self.last_search_diagnostics = {}

    def _fetch_listings(self) -> tuple[list[dict], int, str | None]:
        if self._listings_cache is not None:
            return self._listings_cache
        if self._client is None:
            return [], 0, "source is not open"
        jobs: list[dict] = []
        for page_number in range(1, _MAX_PAGES + 1):
            try:
                response = self._client.get(
                    _API_URL, params={"per_page": _PAGE_SIZE, "_embed": "true", "page": page_number},
                )
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                payload = response.json()
                if not isinstance(payload, list):
                    raise RuntimeError("listing response is not an array")
                total_pages = int(response.headers.get("X-WP-TotalPages", "1"))
                if total_pages < 1:
                    raise RuntimeError("invalid X-WP-TotalPages header")
            except Exception as exc:
                logger.warning("DEV.BG listing request for page %s failed: %s", page_number, exc)
                error = str(exc)
                result = (jobs, page_number - 1, error)
                self._listings_cache = result
                return result
            jobs.extend(job for job in payload if isinstance(job, dict))
            if page_number >= total_pages:
                result = (jobs, page_number, None)
                self._listings_cache = result
                return result
        result = (jobs, _MAX_PAGES, f"pagination safety cap of {_MAX_PAGES} pages reached")
        self._listings_cache = result
        return result

    def search(self, title: str, location: str, days_back: int | None = None,
               max_results: int | None = None, known_urls: set[str] | None = None) -> list[RawJob]:
        del location  # DEV.BG listings are Bulgaria-based or remote-open to Bulgaria.
        days = days_back if days_back is not None else self._days_back
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        listings, pages_fetched, pagination_error = self._fetch_listings()
        if pagination_error and not pages_fetched:
            self.set_search_diagnostics(source_status="error", source_error=pagination_error, upstream_found=0,
                                        query_matched=0, date_matched=0, geo_matched=0, pages_fetched=0)
            return []

        results: list[RawJob] = []
        known_keys = {_url_key(url) for url in (known_urls or set())}
        query_matched = date_matched = geo_matched = known_url_filtered = 0
        for job in listings:
            url = job.get("link")
            job_title = strip_html((job.get("title") or {}).get("rendered") or "") or ""
            raw_content = (job.get("content") or {}).get("rendered") or ""
            description = strip_html(raw_content)
            if not url or not job_title or not job_matches_query_with_focused_description(title, job_title, description):
                continue
            query_matched += 1
            try:
                posted_at = datetime.fromisoformat(str(job.get("date_gmt") or "").replace("Z", "+00:00"))
                if posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if posted_at < cutoff:
                continue
            date_matched += 1
            if _url_key(url) in known_keys:
                known_url_filtered += 1
                continue
            terms = _embedded_terms(job)
            source_data, cities, modes = _source_data(terms)
            geo_matched += 1
            if max_results and len(results) >= max_results:
                continue
            city = ", ".join(dict.fromkeys(cities)) or "Bulgaria"
            results.append(RawJob(
                title=job_title, company=_company(job, terms),
                location=f"{city}, Bulgaria{workplace_suffix(modes)}" if city != "Bulgaria" else f"Bulgaria{workplace_suffix(modes)}",
                url=url, source=self.name, source_id=str(job.get("id") or ""),
                description=description, posted_at=posted_at.isoformat(), source_structured_data=source_data,
            ))
        source_error = f"pagination failed after {pages_fetched} pages: {pagination_error}" if pagination_error else None
        self.set_search_diagnostics(
            source_status="partial" if pagination_error else "empty" if not listings else "ok",
            source_error=source_error, upstream_found=len(listings), query_matched=query_matched,
            date_matched=date_matched, geo_matched=geo_matched, known_url_filtered=known_url_filtered,
            pages_fetched=pages_fetched,
        )
        return results
