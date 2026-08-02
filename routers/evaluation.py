from fastapi import APIRouter, Depends

import jobs_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/eval", tags=["eval"])

# Mirrors JobAgent's config.WOULD_APPLY["score_floor"] — display-only context for
# the calibration report, not a value this service enforces itself.
WOULD_APPLY_SCORE_FLOOR = 7.0

# Mirror JobAgent's ranker/listwise.py FALLBACK_RANK_REASON / OMITTED_RANK_REASON
# and ranker/exploration.py's EXPLORATION_RANK_REASON_PREFIX (sibling repo, not
# importable here). A row whose rank_reason matches one of these wasn't placed by
# the normal deterministic-pipeline + Opus judgment this metric measures — it's
# either a degraded-run fallback position or a deliberately-injected exploration
# pick — so it's excluded rather than silently miscounted into a bucket it didn't
# earn.
_FALLBACK_RANK_REASON = "[unranked — Opus ranking unavailable this run, showing rerank order]"
_OMITTED_RANK_REASON = "[omitted by Opus — not in its ranking response, appended at the end]"
_EXPLORATION_RANK_REASON_PREFIX = "[EXPLORATION] "

# Mirrors JobAgent's config.RANKING["top_n_listwise"] = 20, partitioned into
# quarters — a clean bucketing of the only rank range the normal (non-exploration)
# pipeline ever produces.
_RANK_BUCKETS = [(1, 5), (6, 10), (11, 15), (16, 20)]


def _precision_at_k(conn, user_id: int, k: int) -> dict:
    """"reviewed" means read-but-undecided (see the dashboard's own status meaning),
    not a decision — counting it as a positive would credit the ranking for jobs the
    user never actually validated, so it's excluded entirely, same as divergence_cases.

    Kept for backward compatibility (older deployed dashboard builds may still read
    precision_at_5/10) but superseded by _apply_rate_by_bucket: this only ever
    reflects the K best-ever-frozen-rank decided jobs across all history, which
    never grows with more data and never reflects the *current* ranking's quality."""
    rows = jobs_repo.get_ranked(conn, user_id, ["applied", "rejected", "auto_rejected"], limit=k)
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
    """Apply-rate per listwise_rank bucket, over ALL decided+ranked jobs (not a
    fixed top-K slice) — replaces precision@K, which took the K best-ever-frozen
    ranks across all history and so (a) mixed decisions made under wildly
    different ranking/preference states, (b) let old well-ranked decided jobs
    dominate forever since their frozen rank never gets displaced, and (c) never
    grew with more decision data. This instead reveals whether apply-rate
    monotonically decreases as rank worsens — the real signal of ranking
    quality — and its sample size grows with every decision."""
    rows = jobs_repo.get_ranked(conn, user_id, ["applied", "rejected", "auto_rejected"])
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
