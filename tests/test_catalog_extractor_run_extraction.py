from unittest.mock import MagicMock, patch

from extractors import catalog_extractor


def _job(job_id="job-1"):
    return {"id": job_id, "title": "Python Developer", "company": "Acme", "description": "Python remote role", "source": "example"}


def test_one_jobs_db_error_does_not_poison_the_rest_of_the_batch():
    # A failed statement (a bad value hitting a column constraint, say) leaves
    # a shared connection's transaction aborted - every later statement on it
    # raises "current transaction is aborted" otherwise, cascading one job's
    # failure into every job still left in the batch.
    conn = MagicMock()
    jobs = [_job("job-1"), _job("job-2")]

    def update_facts(_conn, job_id, *_args, **_kwargs):
        if job_id == "job-1":
            raise Exception("malformed array literal")

    with patch.object(catalog_extractor, "extract_job", return_value={"remote": True}), \
         patch.object(catalog_extractor.job_repository, "update_facts", side_effect=update_facts) as mock_update:
        updated = catalog_extractor.run_extraction(conn, jobs, catalog=False)

    assert updated == 1
    assert mock_update.call_count == 2
    conn.rollback.assert_called_once()


def test_normalize_facts_drops_non_string_stack_entries_instead_of_crashing():
    result = catalog_extractor._normalize_facts({
        "stack": ["Python", {"name": "Go", "level": "expert"}],
        "stack_required": [{"name": "Python"}],
        "stack_preferred": ["Kotlin"],
    })
    assert result["stack"] == ["Python", "python"]
    assert result["stack_required"] == []
    assert result["stack_preferred"] == ["Kotlin"]
