"""Server-side collection of the profile-agnostic public job catalog."""
from __future__ import annotations

import logging
from datetime import date

import jobs_repo
import search_stats_repo
from collectors.query_matcher import job_matches_query
from collectors.sources import available, make
from extractors.catalog_extractor import FACT_SCHEMA_VERSION, run_extraction

logger = logging.getLogger(__name__)

CATALOG_QUERIES = (
    "PHP Developer", "Python Developer", "Node.js Developer", "React Developer",
    "Angular Developer", "QA Engineer", "Java Developer", ".NET Developer",
    "Go Developer", "Software Developer", "Software Engineer", "Backend Developer",
    "Frontend Developer", "Full Stack Developer", "Mobile Developer", "DevOps Engineer",
    "Data Engineer", "Machine Learning Engineer",
)
CATALOG_COUNTRIES = ("Poland", "Bulgaria")


def queries_for_slot(slot: int, per_run: int = 2) -> list[str]:
    start = (slot * per_run) % len(CATALOG_QUERIES)
    return [CATALOG_QUERIES[(start + offset) % len(CATALOG_QUERIES)] for offset in range(per_run)]


def _record(conn, source: str, query: str, location: str, cards: int, new: int, **extra) -> None:
    search_stats_repo.record(conn, None, None, source, query, location, cards, new,
                             inserted_found=new, **extra)


def run_catalog_collection(conn, *, days_back: int = 7, max_jobs: int | None = None,
                           max_jobs_per_source: int | None = None, slot: int | None = None,
                           source_ids: list[str] | None = None, extractor=run_extraction) -> dict:
    """Collect, enrich descriptions, then extract facts for this run's new jobs.

    Each source and each extraction is isolated so scheduled execution remains
    healthy when a board or Anthropic has a transient failure.
    """
    queries = queries_for_slot(slot if slot is not None else date.today().toordinal())
    sources = source_ids or available()
    known_urls = jobs_repo.get_all_shared_urls(conn)
    job_ids: list[str] = []
    found = new = 0
    logger.info("catalog collection started: queries=%s sources=%s", queries, sources)
    for source_id in sources:
        if max_jobs is not None and new >= max_jobs:
            break
        try:
            source = make(source_id, days_back=days_back, catalog=True)
            source_new = 0
            pending: list[tuple[str, str]] = []
            with source:
                source.login()
                for query in queries:
                    for location in CATALOG_COUNTRIES:
                        if max_jobs_per_source is not None and source_new >= max_jobs_per_source:
                            break
                        if max_jobs is not None and new >= max_jobs:
                            break
                        try:
                            raw_jobs = source.search(query, location, known_urls=known_urls)
                            raw_jobs = [raw for raw in raw_jobs if job_matches_query(query, raw.title, raw.description)]
                            found += len(raw_jobs)
                            inserted = duplicates = 0
                            for raw in raw_jobs:
                                if max_jobs is not None and new >= max_jobs:
                                    break
                                if max_jobs_per_source is not None and source_new >= max_jobs_per_source:
                                    break
                                if raw.url in known_urls:
                                    # Belt and suspenders: don't rely solely on each
                                    # source's own known_urls filtering, a source
                                    # returning the same posting across two queries
                                    # or countries in this run would otherwise cost
                                    # a wasted insert attempt per repeat.
                                    duplicates += 1
                                    continue
                                result = jobs_repo.insert(conn, None, raw.__dict__ | {"search_query": query}, attach_to_user=False)
                                job_id = result.get("job_id")
                                if not job_id or not result.get("posting_created"):
                                    duplicates += 1
                                    continue
                                known_urls.add(raw.url)
                                job_ids.append(job_id)
                                new += 1
                                source_new += 1
                                inserted += 1
                                if not raw.description:
                                    pending.append((job_id, raw.url))
                            _record(conn, source_id, query, location, len(raw_jobs), inserted,
                                    source_returned=len(raw_jobs), global_matched=len(raw_jobs),
                                    duplicate_found=duplicates, source_status="ok")
                        except Exception as error:
                            logger.exception("catalog source %s failed for %s/%s", source_id, query, location)
                            _record(conn, source_id, query, location, 0, 0, source_status="error", source_error=str(error)[:1000])
            for job_id, url in pending:
                try:
                    description = source.fetch_description(url)
                    if description:
                        jobs_repo.update_description(conn, job_id, description)
                except Exception:
                    logger.exception("catalog description fetch failed: %s", url)
            logger.info("catalog source complete: source=%s new=%s", source_id, source_new)
        except Exception as error:
            logger.exception("catalog source setup failed: %s", source_id)
            try:
                _record(conn, source_id, "__source__", "", 0, 0, source_status="error", source_error=str(error)[:1000])
            except Exception:
                logger.exception("could not record catalog source failure: %s", source_id)
    extracted = 0
    try:
        pending_facts = [job for job in jobs_repo.get_shared_missing_facts(conn, FACT_SCHEMA_VERSION, len(job_ids) or 1)
                         if job["id"] in set(job_ids)]
        extracted = extractor(conn, pending_facts, catalog=True) if pending_facts else 0
    except Exception:
        logger.exception("catalog extraction stage failed")
    conn.commit()
    result = {"jobs_found": found, "jobs_new": new, "job_ids": job_ids, "extracted": extracted}
    logger.info("catalog collection finished: found=%s new=%s extracted=%s", found, new, extracted)
    return result
