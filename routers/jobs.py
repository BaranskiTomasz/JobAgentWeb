from fastapi import APIRouter, Depends, HTTPException, Query

import dismissed_items_repo
import jobs_repo
from db import get_db
from deps import get_current_user, require_automation_client
from models import (
    DismissedItemCreate, JobCreate, JobCreateResult, JobDescriptionUpdate, JobOut,
    JobRankingBatchUpdate, JobRankingUpdate, JobScoreAndStatusUpdate, JobScoreUpdate,
    JobFactsUpdate, JobStats, JobStatusUpdate, JobStructuredDataUpdate, JobWouldApplyBatchUpdate,
    JobWouldApplyUpdate, WouldApplyStats,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_or_404(conn, user_id: int, job_id: str) -> dict:
    job = jobs_repo.get_by_id(conn, user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = None,
    min_score: float | None = None,
    query: str | None = None,
    source: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    return jobs_repo.search(
        conn, user["id"], status=status, min_score=min_score, query=query, source=source,
        limit=limit, offset=offset,
    )


@router.get("/stats", response_model=JobStats)
def job_stats(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_stats(conn, user["id"])


@router.get("/would-apply-stats", response_model=WouldApplyStats)
def would_apply_stats(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_would_apply_stats(conn, user["id"])


@router.get("/urls")
def get_all_urls(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"urls": list(jobs_repo.get_all_urls(conn, user["id"]))}


@router.get("/missing-descriptions")
def missing_descriptions(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_missing_descriptions(conn, user["id"])


@router.get("/missing-structured-data", response_model=list[JobOut])
def missing_structured_data(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_missing_structured_data(conn, user["id"])


@router.get("/missing-facts", response_model=list[JobOut])
def missing_facts(
    schema_version: int,
    limit: int = Query(200, ge=1, le=2000),
    max_age_days: int = Query(14, ge=1, le=90),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    return jobs_repo.get_missing_facts(conn, user["id"], schema_version, limit, max_age_days)


@router.get("/new", response_model=list[JobOut])
def get_new(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_new(conn, user["id"])


@router.get("/unscored", response_model=list[JobOut])
def get_unscored(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_unscored(conn, user["id"])


@router.get("/new-with-descriptions", response_model=list[JobOut])
def get_new_with_descriptions(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_new_with_descriptions(conn, user["id"])


@router.get("/dealbreaker-rejected-with-descriptions", response_model=list[JobOut])
def get_dealbreaker_rejected_with_descriptions(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_dealbreaker_rejected_with_descriptions(conn, user["id"])


@router.get("/for-ranking", response_model=list[JobOut])
def get_jobs_for_ranking(limit: int = 2000, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_jobs_for_ranking(conn, user["id"], limit)


@router.get("/examples")
def get_examples(
    limit_positive: int = 25, limit_negative: int = 25,
    user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    positive, negative = jobs_repo.get_examples(conn, user["id"], limit_positive, limit_negative)
    return {"positive": positive, "negative": negative}


@router.get("/feedback")
def get_all_feedback(
    since: str | None = None, limit_applied: int | None = None, limit_rejected: int | None = None,
    user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    if since:
        applied, rejected = jobs_repo.get_feedback_since(conn, user["id"], since)
    else:
        applied, rejected = jobs_repo.get_all_feedback(conn, user["id"], limit_applied, limit_rejected)
    return {"applied": applied, "rejected": rejected}


@router.get("/applied-ids")
def get_applied_job_ids(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"ids": jobs_repo.get_applied_job_ids(conn, user["id"])}


@router.get("/rejected-ids")
def get_rejected_job_ids(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"ids": jobs_repo.get_rejected_job_ids(conn, user["id"])}


@router.get("/decisions-count")
def count_decisions(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"count": jobs_repo.count_decisions(conn, user["id"])}


@router.get("/query-outcome-stats")
def get_query_outcome_stats(source: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_query_outcome_stats(conn, user["id"], source)


@router.get("/count")
def count_by_filter(
    status: list[str] = Query(default=[]),
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    return {"count": jobs_repo.count_by_filter(conn, user["id"], status, date_from, date_to)}


@router.get("/ranked", response_model=list[JobOut])
def get_ranked(status: list[str] = Query(...), user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return jobs_repo.get_ranked(conn, user["id"], status)


@router.get("/ranked-count")
def ranked_count(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"count": jobs_repo.count_ranked(conn, user["id"])}


@router.post("/reset-auto-rejected")
def reset_auto_rejected(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"reset": jobs_repo.reset_auto_rejected(conn, user["id"])}


@router.delete("")
def delete_by_filter(
    status: list[str] = Query(default=[]),
    date_from: str | None = None,
    date_to: str | None = None,
    user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    return {"deleted": jobs_repo.delete_by_filter(conn, user["id"], status, date_from, date_to)}


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return _get_or_404(conn, user["id"], job_id)


@router.get("/{job_id}/aliases")
def get_job_aliases(job_id: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    return jobs_repo.get_aliases(conn, user["id"], job_id)


@router.post("", response_model=JobCreateResult)
def create_job(job: JobCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    result = jobs_repo.insert(conn, user["id"], job.model_dump())
    return JobCreateResult(**result)


@router.patch("/{job_id}/status", response_model=JobOut)
def update_status(job_id: str, body: JobStatusUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_status(conn, user["id"], job_id, body.status, body.rejection_reason)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/{job_id}/score", response_model=JobOut)
def update_score(job_id: str, body: JobScoreUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_score(conn, user["id"], job_id, body.score, body.reason, body.breakdown, body.fingerprint)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/{job_id}/score-and-status", response_model=JobOut)
def update_score_and_status(job_id: str, body: JobScoreAndStatusUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_score_and_status(conn, user["id"], job_id, body.score, body.reason, body.status, body.breakdown, body.fingerprint)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/{job_id}/description", response_model=JobOut)
def update_description(job_id: str, body: JobDescriptionUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_description(conn, job_id, body.description)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/{job_id}/ranking", response_model=JobOut)
def update_ranking(job_id: str, body: JobRankingUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_ranking_scores(
        conn, user["id"], job_id, body.embedding_score, body.rerank_score, body.listwise_rank,
        body.rank_reason, body.debate_flag, body.debate_note, body.fingerprint,
    )
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/ranking")
def update_ranking_batch(body: JobRankingBatchUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    updated = jobs_repo.update_ranking_scores_batch(conn, user["id"], [item.model_dump() for item in body.items])
    return {"updated": updated}


@router.patch("/{job_id}/structured-data", response_model=JobOut)
def update_structured_data(
    job_id: str, body: JobStructuredDataUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_structured_data(conn, job_id, body.data)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.put("/{job_id}/facts")
def update_facts(
    job_id: str, body: JobFactsUpdate, user: dict = Depends(require_automation_client), conn=Depends(get_db),
):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_facts(
        conn, job_id, body.schema_version, body.model, body.content_hash, body.facts, body.provenance,
    )
    return {"ok": True}


@router.patch("/{job_id}/would-apply", response_model=JobOut)
def update_would_apply(
    job_id: str, body: JobWouldApplyUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db),
):
    _get_or_404(conn, user["id"], job_id)
    jobs_repo.update_would_apply(conn, user["id"], job_id, body.would_apply, body.reason)
    return jobs_repo.get_by_id(conn, user["id"], job_id)


@router.patch("/would-apply")
def update_would_apply_batch(body: JobWouldApplyBatchUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    updated = jobs_repo.update_would_apply_batch(conn, user["id"], [item.model_dump() for item in body.items])
    return {"updated": updated}


@router.get("/{job_id}/dismissed-items")
def get_dismissed_items(job_id: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"items": dismissed_items_repo.get_for_job(conn, user["id"], job_id)}


@router.post("/{job_id}/dismiss-item")
def dismiss_item(job_id: str, body: DismissedItemCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    _get_or_404(conn, user["id"], job_id)
    dismissed_items_repo.insert(conn, user["id"], job_id, body.item_type, body.item_text, body.reason)
    return {"ok": True}
