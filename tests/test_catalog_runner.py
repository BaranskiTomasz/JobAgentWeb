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
    result = catalog_runner.run_catalog_collection(
        SimpleNamespace(commit=lambda: None), source_ids=["example"], slot=0,
        extractor=lambda _conn, jobs, **_kwargs: extracted.append(jobs) or len(jobs),
    )
    assert result["jobs_new"] == 0
    assert result["extracted"] == 1
    assert extracted == [[{"id": "stuck-from-earlier-run", "description": "x"}]]


def test_catalog_runner_continues_when_source_raises(monkeypatch):
    stats = []
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_all_shared_urls", lambda _conn: set())
    monkeypatch.setattr(catalog_runner, "make", lambda source, **_kwargs: _Source(error=RuntimeError("down")) if source == "bad" else _Source([_job("https://ok.test/job")]))
    monkeypatch.setattr(catalog_runner.jobs_repo, "insert", lambda *_args, **_kwargs: {"job_id": "ok", "posting_created": True})
    monkeypatch.setattr(catalog_runner.jobs_repo, "get_shared_missing_facts", lambda *_args: [])
    monkeypatch.setattr(catalog_runner.search_stats_repo, "record", lambda *_args, **kwargs: stats.append(kwargs))
    result = catalog_runner.run_catalog_collection(SimpleNamespace(commit=lambda: None), source_ids=["bad", "ok"], slot=0)
    assert result["jobs_new"] == 1
    assert any(item.get("source_status") == "error" for item in stats)


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
