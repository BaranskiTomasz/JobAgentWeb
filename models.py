from datetime import datetime
from typing import Literal

from pydantic import BaseModel

_JOB_STATUSES = Literal["new", "reviewed", "applied", "rejected", "auto_rejected"]


class JobOut(BaseModel):
    id: str
    title: str
    company: str | None
    location: str | None
    url: str
    description: str | None
    source: str | None
    source_id: str | None
    search_query: str | None
    posted_at: datetime | None
    source_structured_data: str | None
    status: str
    score: float | None
    score_reason: str | None
    score_breakdown: str | None
    score_fingerprint: str | None
    rejection_reason: str | None
    structured_data: str | None
    embedding_score: float | None
    rerank_score: float | None
    listwise_rank: int | None
    rank_reason: str | None
    debate_flag: str | None
    debate_note: str | None
    ranking_fingerprint: str | None
    would_apply: bool | None
    would_apply_reason: str | None
    created_at: datetime
    updated_at: datetime
    company_total_count: int
    company_applied_count: int


class JobCreate(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    url: str
    source: str = "linkedin"
    source_id: str | None = None
    description: str | None = None
    search_query: str | None = None
    posted_at: str | None = None
    source_structured_data: dict | None = None


class JobCreateResult(BaseModel):
    job_id: str | None  # None means this user already has this posting, not inserted again
    posting_created: bool  # False means the posting was already known (from another user); skip re-fetching/re-extracting


class PublicJobOut(BaseModel):
    id: str
    title: str
    company: str | None
    location: str | None
    url: str
    source: str | None
    sources: list[str]
    posted_at: datetime | None
    created_at: datetime
    technologies: list[str]
    work_countries: list[str]
    eligibility_confidence: str
    excerpt: str | None


class CatalogImport(BaseModel):
    technology: Literal["php", "python", "nodejs", "react", "angular", "qa"]
    country: Literal["PL", "BG"]


class JobStatusUpdate(BaseModel):
    status: _JOB_STATUSES
    rejection_reason: str | None = None


class JobScoreUpdate(BaseModel):
    score: float | None
    reason: str
    breakdown: dict | None = None
    fingerprint: str | None = None


class JobRankingUpdate(BaseModel):
    embedding_score: float | None = None
    rerank_score: float | None = None
    listwise_rank: int | None = None
    rank_reason: str | None = None
    debate_flag: str | None = None
    debate_note: str | None = None
    fingerprint: str | None = None


class JobRankingBatchItem(JobRankingUpdate):
    job_id: str


class JobRankingBatchUpdate(BaseModel):
    items: list[JobRankingBatchItem]


class JobStructuredDataUpdate(BaseModel):
    data: dict


class JobDescriptionUpdate(BaseModel):
    description: str


class JobScoreAndStatusUpdate(BaseModel):
    score: float | None
    reason: str
    status: _JOB_STATUSES
    breakdown: dict | None = None
    fingerprint: str | None = None


class JobWouldApplyUpdate(BaseModel):
    would_apply: bool
    reason: str


class JobWouldApplyBatchItem(JobWouldApplyUpdate):
    job_id: str


class JobWouldApplyBatchUpdate(BaseModel):
    items: list[JobWouldApplyBatchItem]


class JobStats(BaseModel):
    total: int
    new: int
    reviewed: int
    applied: int
    rejected: int
    auto_rejected: int
    avg_score: float | None
    avg_score_new: float | None
    last_run: datetime | None
    ranked: int


class WouldApplyStats(BaseModel):
    flagged_total: int
    applied: int
    rejected: int
    decided: int
    precision: float | None


# CV profiles

class CVProfileCreate(BaseModel):
    filename: str
    raw_text: str
    parsed: dict


# Criteria

class CriteriaCreate(BaseModel):
    type: Literal["title", "location", "required", "preferred", "rejected", "search_query"]
    value: str


class CriteriaToggle(BaseModel):
    is_active: bool


# Preference profile (distilled signals)

class PreferenceProfileSave(BaseModel):
    signals: list[dict]
    applied_count: int
    rejected_count: int
    dismissed_count: int = 0


# Candidate preferences (questionnaire)

class CandidatePreferencesCreate(BaseModel):
    cv_profile_id: int | None = None
    fields: dict = {}


class CandidatePreferencesUpdate(BaseModel):
    fields: dict


# Dismissed score items

class DismissedItemCreate(BaseModel):
    item_type: Literal["pro", "con"]
    item_text: str
    reason: str


# Excluded search queries

class ExcludedQueryCreate(BaseModel):
    source: str
    search_query: str
    reason: str


# Search stats

class SearchStatRecord(BaseModel):
    session_id: int | None = None
    source: str
    search_query: str
    location: str
    cards_found: int = 0
    new_found: int = 0
    upstream_found: int | None = None
    query_matched: int | None = None
    date_matched: int | None = None
    geo_matched: int | None = None


# Sessions

class SessionFinish(BaseModel):
    jobs_found: int = 0
    jobs_scored: int = 0
    status: Literal["done", "error", "done_with_errors"] = "done"


# Usage / cost

class UsageLogCreate(BaseModel):
    model: str
    module: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class RunSummaryCreate(BaseModel):
    run_label: str
    started_at: str


# Embeddings

class EmbeddingItem(BaseModel):
    job_id: str
    embedding: list[float]
    model: str
    text_hash: str | None = None


class EmbeddingBatchUpsert(BaseModel):
    items: list[EmbeddingItem]


class EmbeddingVectorsRequest(BaseModel):
    job_ids: list[str]


class EmbeddingSimilarityRequest(BaseModel):
    ideal: list[float]
    job_ids: list[str]
