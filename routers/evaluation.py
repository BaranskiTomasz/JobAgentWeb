from fastapi import APIRouter, Depends

import jobs_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/eval", tags=["eval"])

# Mirrors JobAgent's config.WOULD_APPLY["score_floor"] — display-only context for
# the calibration report, not a value this service enforces itself.
WOULD_APPLY_SCORE_FLOOR = 7.0


def _precision_at_k(conn, user_id: int, k: int) -> dict:
    """"reviewed" means read-but-undecided (see the dashboard's own status meaning),
    not a decision — counting it as a positive would credit the ranking for jobs the
    user never actually validated, so it's excluded entirely, same as divergence_cases."""
    rows = jobs_repo.get_ranked(conn, user_id, ["applied", "rejected", "auto_rejected"], limit=k)
    if not rows:
        return {"precision_at_k": None, "n_evaluated": 0}
    positive = sum(1 for r in rows if r["status"] == "applied")
    return {"precision_at_k": round(positive / len(rows), 3), "n_evaluated": len(rows)}


@router.get("/report")
def report(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    p5 = _precision_at_k(conn, user["id"], 5)
    p10 = _precision_at_k(conn, user["id"], 10)
    return {
        "precision_at_5": p5["precision_at_k"],
        "precision_at_10": p10["precision_at_k"],
        "n_evaluated_5": p5["n_evaluated"],
        "n_evaluated_10": p10["n_evaluated"],
        "divergence_cases": jobs_repo.get_divergence_cases(conn, user["id"]),
        "total_ranked": jobs_repo.count_ranked(conn, user["id"]),
        "would_apply": jobs_repo.get_would_apply_stats(conn, user["id"]),
        "would_apply_score_floor": WOULD_APPLY_SCORE_FLOOR,
    }
