from fastapi import APIRouter, Depends

import usage_repo
from db import get_db
from deps import get_current_user
from models import RunSummaryCreate, UsageLogCreate

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.post("")
def log(body: UsageLogCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    usage_repo.log_usage(conn, user["id"], body.model, body.module, body.input_tokens, body.output_tokens, body.cost_usd)
    return {"ok": True}


@router.get("/summary")
def summary(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return usage_repo.get_summary(conn, user["id"])


@router.post("/run-summary")
def run_summary(body: RunSummaryCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    usage_repo.record_run_summary(conn, user["id"], body.run_label, body.started_at)
    return {"ok": True}


@router.get("/history")
def history(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return usage_repo.get_history(conn, user["id"])
