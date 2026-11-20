from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

import autonomy_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


class AutomationSettingsOut(BaseModel):
    max_daily_auto_sends: int = 0
    min_confidence_auto_send: float = 0.9
    allowed_auto_send_sources: list[str] = Field(default_factory=list)


class AutomationSettingsPatch(BaseModel):
    max_daily_auto_sends: int | None = None
    min_confidence_auto_send: float | None = None
    allowed_auto_send_sources: list[str] | None = None


class AutonomyDecisionOut(BaseModel):
    id: int
    user_id: int
    job_id: str | None = None
    level: str
    reasons: list[str]
    inputs: dict
    decided_at: datetime | None = None


@router.get("/settings", response_model=AutomationSettingsOut)
def get_automation_settings(
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    settings = autonomy_repo.get_settings(conn, user["id"])
    if settings is None:
        return AutomationSettingsOut()
    return settings


@router.patch("/settings", response_model=AutomationSettingsOut)
def patch_automation_settings(
    body: AutomationSettingsPatch,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    return autonomy_repo.upsert_settings(
        conn,
        user["id"],
        max_daily_auto_sends=body.max_daily_auto_sends,
        min_confidence_auto_send=body.min_confidence_auto_send,
        allowed_auto_send_sources=body.allowed_auto_send_sources,
    )


@router.get("/decisions", response_model=list[AutonomyDecisionOut])
def get_autonomy_decisions(
    limit: int = Query(50, ge=1),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    return autonomy_repo.get_recent_decisions(conn, user["id"], limit=min(limit, 200))
