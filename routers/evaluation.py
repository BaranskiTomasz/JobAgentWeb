from fastapi import APIRouter, Depends

import jobs_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/eval", tags=["eval"])

# Mirrors JobAgent's config.WOULD_APPLY["score_floor"], display-only context
# for the calibration report, not a value this service enforces itself.
WOULD_APPLY_SCORE_FLOOR = 7.0

# Mirrors JobAgent's ranker/listwise.py FALLBACK_RANK_REASON / OMITTED_RANK_REASON
# and ranker/exploration.py's EXPLORATION_RANK_REASON_PREFIX (sibling repo, not
# importable here). A row matching one of these wasn't placed by real Opus
# judgment, so it's excluded rather than miscounted into a bucket it didn't earn.
_FALLBACK_RANK_REASON = "[unranked, Opus ranking unavailable this run, showing rerank order]"
_OMITTED_RANK_REASON = "[omitted by Opus, not in its ranking response, appended at the end]"
_EXPLORATION_RANK_REASON_PREFIX = "[EXPLORATION] "

# Mirrors JobAgent's config.RANKING["top_n_listwise"] = 20, partitioned into
# quarters.
_RANK_BUCKETS = [(1, 5), (6, 10), (11, 15), (16, 20)]


def _precision_at_k(conn, user_id: int, k: int) -> dict:
    # Only "applied"/"rejected" count as real decisions. "reviewed" is
    # read-but-undecided, and "auto_rejected" is the pipeline rejecting a job
    # before the user ever saw it, so counting either would grade the ranking
    # against a decision the user never actually made.
    #
    # Kept for backward compatibility with older dashboard builds, but
    # superseded by _apply_rate_by_bucket, which grows with more data instead
    # of freezing on the K best-ever-ranked decided jobs.
    rows = jobs_repo.get_ranked(conn, user_id, ["applied", "rejected"], limit=k)
    if not rows:
        return {"precision_at_k": None, "n_evaluated": 0}
    positive = sum(1 for r in rows if r["status"] == "applied")
    return {"precision_at_k": round(positive / len(rows), 3), "n_evaluated": len(rows)}


def _is_excluded_from_bucket_metric(rank_reason: str | None) -> bool:
    if not rank_reason:
        return False
    return (
        rank_reason in (_FALLBACK_RANK_REASON, _OMITTED_RANK_REASON)
        or rank_reason.startswith(_EXPLORATION_RANK_REASON_PREFIX)
    )


def _apply_rate_by_bucket(conn, user_id: int) -> list[dict]:
    # Apply-rate per listwise_rank bucket, over every decided+ranked job rather
    # than a fixed top-K slice, so the sample grows with every new decision and
    # reveals whether apply-rate drops as rank worsens. auto_rejected excluded
    # for the same reason as _precision_at_k.
    rows = jobs_repo.get_ranked(conn, user_id, ["applied", "rejected"])
    rows = [r for r in rows if not _is_excluded_from_bucket_metric(r.get("rank_reason"))]

    buckets = []
    for lo, hi in _RANK_BUCKETS:
        in_bucket = [r for r in rows if lo <= r["listwise_rank"] <= hi]
        if not in_bucket:
            buckets.append({"range": f"{lo}-{hi}", "apply_rate": None, "n": 0})
            continue
        applied = sum(1 for r in in_bucket if r["status"] == "applied")
        buckets.append({"range": f"{lo}-{hi}", "apply_rate": round(applied / len(in_bucket), 3), "n": len(in_bucket)})
    return buckets


@router.get("/report")
def report(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    p5 = _precision_at_k(conn, user["id"], 5)
    p10 = _precision_at_k(conn, user["id"], 10)
    return {
        "precision_at_5": p5["precision_at_k"],
        "precision_at_10": p10["precision_at_k"],
        "n_evaluated_5": p5["n_evaluated"],
        "n_evaluated_10": p10["n_evaluated"],
        "apply_rate_by_bucket": _apply_rate_by_bucket(conn, user["id"]),
        "divergence_cases": jobs_repo.get_divergence_cases(conn, user["id"]),
        "total_ranked": jobs_repo.count_ranked(conn, user["id"]),
        "would_apply": jobs_repo.get_would_apply_stats(conn, user["id"]),
        "would_apply_score_floor": WOULD_APPLY_SCORE_FLOOR,
    }
