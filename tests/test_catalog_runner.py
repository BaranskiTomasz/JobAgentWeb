from types import SimpleNamespace

from collectors.base import RawJob
from collectors import catalog_runner
from extractors import catalog_extractor


class _Source:
    def __init__(self, jobs=None, error=None, **_):
        self.jobs = jobs or []
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def login(self):
        return None

    def search(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.jobs

    def fetch_description(self, _url):
        return None


def _job(url="https://example.test/job"):
    return RawJob("Python Developer", "Example", "Remote Poland", url, "example", description="Python remote role")


def test_catalog_runner_deduplicates_records_stats_and_extracts(monkeypatch):
    inserted = []
    stats = []
    extracted = []
    monkeypatch.setattr(catalog_runner, "available", lambda: ["example"])
    monkeypatch.setattr(catalog_runner, "make", lambda *_args, **_kwargs: _Source([_job(), _job()]))
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())

    def insert(_conn, _user_id, job, **_kwargs):
        inserted.append(job)
        return {"job_id": "new-job" if len(inserted) == 1 else None, "posting_created": len(inserted) == 1}

    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", insert)
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_shared_missing_facts", lambda *_args: [{"id": "new-job", "description": "x"}])
    monkeypatch.setattr(catalog_runner.search_stats_repo, "record", lambda *_args, **kwargs: stats.append(kwargs))
    monkeypatch.setattr(catalog_runner.catalog_repo, "attach_catalog_for_all_users", lambda _conn: {})
    result = catalog_runner.run_catalog_collection(
        SimpleNamespace(commit=lambda: None), source_ids=["example"], slot=0,
        extractor=lambda _conn, jobs, **_kwargs: extracted.append(jobs) or len(jobs),
    )
    assert result["jobs_new"] == 1
    assert result["extracted"] == 1
    assert stats and any(item.get("duplicate_found") == 1 for item in stats)
    assert extracted == [[{"id": "new-job", "description": "x"}]]


def test_catalog_runner_extracts_backlog_from_a_prior_run_not_just_this_ones_finds(monkeypatch):
    # A prior run's extraction can fail wholesale (an Anthropic outage, say)
    # and leave postings stuck with missing facts forever, since they're
    # already in known_urls and nothing will re-insert them. This run finds
    # nothing new of its own but should still pick up that old backlog.
    extracted = []
    monkeypatch.setattr(catalog_runner, "available", lambda: ["example"])
    monkeypatch.setattr(catalog_runner, "make", lambda *_args, **_kwargs: _Source([]))
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", lambda *_args, **_kwargs: {"job_id": None, "posting_created": False})
    monkeypatch.setattr(
        catalog_runner.jobs_repo, "get_shared_missing_facts",
        lambda *_args: [{"id": "stuck-from-earlier-run", "description": "x"}],
    )
    monkeypatch.setattr(catalog_runner.search_stats_repo, "record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(catalog_runner.catalog_repo, "attach_catalog_for_all_users", lambda _conn: {})
    result = catalog_runner.run_catalog_collection(
        SimpleNamespace(commit=lambda: None), source_ids=["example"], slot=0,
        extractor=lambda _conn, jobs, **_kwargs: extracted.append(jobs) or len(jobs),
    )
    assert result["jobs_new"] == 0
    assert result["extracted"] == 1
    assert extracted == [[{"id": "stuck-from-earlier-run", "description": "x"}]]


def test_catalog_runner_attaches_after_extraction(monkeypatch):
    stages = []
    monkeypatch.setattr(catalog_runner, "available", lambda: ["example"])
    monkeypatch.setattr(catalog_runner, "make", lambda *_args, **_kwargs: _Source([]))
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(
        catalog_runner.jobs_repo, "get_shared_missing_facts",
        lambda *_args: [{"id": "pending", "description": "x"}],
    )
    monkeypatch.setattr(catalog_runner.search_stats_repo, "record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        catalog_runner.catalog_repo, "attach_catalog_for_all_users",
        lambda _conn: stages.append("attach") or {1: 2},
    )

    catalog_runner.run_catalog_collection(
        SimpleNamespace(commit=lambda: stages.append("commit")), source_ids=["example"], slot=0,
        extractor=lambda *_args, **_kwargs: stages.append("extract") or 1,
    )

    assert stages == ["commit", "extract", "attach", "commit"]


def test_catalog_runner_continues_when_source_raises(monkeypatch):
    stats = []
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(catalog_runner, "make", lambda source, **_kwargs: _Source(error=RuntimeError("down")) if source == "bad" else _Source([_job("https://ok.test/job")]))
    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", lambda *_args, **_kwargs: {"job_id": "ok", "posting_created": True})
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_shared_missing_facts", lambda *_args: [])
    monkeypatch.setattr(catalog_runner.search_stats_repo, "record", lambda *_args, **kwargs: stats.append(kwargs))
    monkeypatch.setattr(catalog_runner.catalog_repo, "attach_catalog_for_all_users", lambda _conn: {})
    result = catalog_runner.run_catalog_collection(SimpleNamespace(commit=lambda: None, rollback=lambda: None), source_ids=["bad", "ok"], slot=0)
    assert result["jobs_new"] == 1
    assert any(item.get("source_status") == "error" for item in stats)


def test_catalog_runner_commits_successful_source_before_later_source_rollback(monkeypatch):
    stats = []

    class FakeDeadlockDetected(Exception):
        pass

    class FakeConnection:
        def __init__(self):
            self.actions = []
            self.staged = []
            self.committed = []

        def commit(self):
            self.actions.append("commit")
            self.committed.extend(self.staged)
            self.staged.clear()

        def rollback(self):
            self.actions.append("rollback")
            self.staged.clear()

    class OneShotSource(_Source):
        def search(self, query, *_args, **_kwargs):
            if self.jobs:
                self.jobs[0].title = query
            jobs, self.jobs = self.jobs, []
            return jobs

    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(
        catalog_runner, "make",
        lambda source, **_kwargs: OneShotSource([_job(f"https://{source}.test/job")]),
    )

    def insert(conn, _user_id, job, **_kwargs):
        conn.staged.append(job["url"])
        if "bad" in job.get("url", ""):
            raise FakeDeadlockDetected("deadlock detected")
        return {"job_id": "ok-job", "posting_created": True}

    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", insert)
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_shared_missing_facts", lambda *_args: [])
    monkeypatch.setattr(
        catalog_runner.search_stats_repo, "record",
        lambda conn, _uid, _sid, source, query, loc, cards, new, **kwargs: (
            conn.staged.append(f"stats:{source}:{kwargs.get('source_status')}")
            or stats.append(
                {"source": source, "query": query, "location": loc, "cards": cards, "new": new, **kwargs}
            )
        ),
    )
    monkeypatch.setattr(catalog_runner.catalog_repo, "attach_catalog_for_all_users", lambda _conn: {})

    conn = FakeConnection()
    result = catalog_runner.run_catalog_collection(conn, source_ids=["first_ok", "bad"], slot=0)

    assert conn.actions == ["commit", "rollback", "commit", "commit"]
    assert result["jobs_new"] == 1
    assert "https://first_ok.test/job" in conn.committed
    assert "https://bad.test/job" not in conn.committed
    assert any(item.get("source") == "bad" and item.get("source_status") == "error" and "deadlock detected" in str(item.get("source_error")) for item in stats)
    assert any(item.get("source") == "first_ok" and item.get("source_status") == "ok" and item.get("inserted_found") == 1 for item in stats)


def test_catalog_gate_uses_anthropic_tool_schema(monkeypatch):
    calls = []

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=10, output_tokens=20),
                content=[SimpleNamespace(type="tool_use", input={
                    "remote": True, "hybrid": False, "remote_available": True,
                    "hybrid_available": False, "office_presence_required": False,
                    "remote_regions": ["Poland"], "country_eligibility": [], "evidence": {},
                })],
            )

    monkeypatch.setattr(catalog_extractor, "_get_client", lambda: SimpleNamespace(messages=Messages()))
    facts = catalog_extractor.extract_catalog_gate("A remote job in Poland")
    assert facts["remote_available"] is True
    assert calls[0]["tool_choice"] == {"type": "tool", "name": "submit_catalog_gate"}


def test_catalog_runner_records_source_diagnostics_and_clears_between_searches(monkeypatch):
    # AC14: records each source's own last_search_diagnostics into search_stats
    # instead of hardcoding source_status="ok", respects allowlist, and clears
    # diagnostics before each search.
    stats = []

    class DiagnosticStubSource:
        def __init__(self, **_):
            self.calls = 0
            self.last_search_diagnostics = {}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def login(self):
            return None

        def search(self, query, location, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                self.last_search_diagnostics = {
                    "source_status": "partial",
                    "source_error": "rate limited partially",
                    "upstream_found": 50,
                    "query_matched": 40,
                    "date_matched": 30,
                    "geo_matched": 20,
                    "source_returned": 10,
                    "disallowed_key": "should_be_filtered",
                }
                return [RawJob("PHP Developer", "Acme", "Remote Poland", "https://diag.test/job1", "stub_source", description="PHP Developer role")]
            # Call 2 does not set last_search_diagnostics; verify it was cleared
            # and doesn't inherit call 1's values
            assert self.last_search_diagnostics == {}
            return []

        def fetch_description(self, _url):
            return None

    monkeypatch.setattr(catalog_runner, "available", lambda: ["stub_source"])
    monkeypatch.setattr(catalog_runner, "make", lambda *_args, **_kwargs: DiagnosticStubSource())
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", lambda *_args, **_kwargs: {"job_id": "job-1", "posting_created": True})
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_shared_missing_facts", lambda *_args: [])
    monkeypatch.setattr(catalog_runner.catalog_repo, "attach_catalog_for_all_users", lambda _conn: {})
    monkeypatch.setattr(
        catalog_runner.search_stats_repo, "record",
        lambda _conn, _uid, _sid, source, query, loc, cards, new, **kwargs: stats.append(
            {"source": source, "query": query, "location": loc, "cards": cards, "new": new, **kwargs}
        ),
    )

    result = catalog_runner.run_catalog_collection(
        SimpleNamespace(commit=lambda: None), source_ids=["stub_source"], slot=0,
    )

    assert result["jobs_found"] >= 1
    # Check first search recorded partial status and funnel counters from source diagnostics
    first_stat = stats[0]
    assert first_stat["source_status"] == "partial"
    assert first_stat["source_error"] == "rate limited partially"
    assert first_stat["upstream_found"] == 50
    assert first_stat["query_matched"] == 40
    assert first_stat["date_matched"] == 30
    assert first_stat["geo_matched"] == 20
    assert first_stat["source_returned"] == 10
    assert "disallowed_key" not in first_stat

    # Check second search had cleared diagnostics and defaulted to "ok"
    second_stat = stats[1]
    assert second_stat["source_status"] == "ok"
    assert second_stat.get("upstream_found") is None
