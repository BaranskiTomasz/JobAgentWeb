from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

import application_plan_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/application-plans", tags=["application-plans"])


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str


class FieldUpsert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str
    fact_ids: list[int] = []
    confidence: float | None = None
    is_negotiable_or_irreversible: bool = False


@router.post("")
def create_plan_endpoint(
    body: PlanCreate,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    plan_id = application_plan_repo.create_plan(conn, user["id"], body.job_id)
    plan = application_plan_repo.get_plan(conn, user["id"], plan_id)
    return {
        "id": plan["id"],
        "job_id": plan["job_id"],
        "status": plan["status"],
        "created_at": plan["created_at"],
        "updated_at": plan["updated_at"],
    }


@router.get("/{plan_id}")
def get_plan_endpoint(
    plan_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    plan = application_plan_repo.get_plan(conn, user["id"], plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Application plan not found")
    return plan


@router.get("")
def list_plans_for_job_endpoint(
    job_id: str | None = Query(None),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing required job_id query parameter")
    return application_plan_repo.list_plans_for_job(conn, user["id"], job_id)


@router.put("/{plan_id}/fields/{field_name}")
def upsert_field_endpoint(
    plan_id: int,
    field_name: str,
    body: FieldUpsert,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    try:
        field_id = application_plan_repo.upsert_field(
            conn,
            user["id"],
            plan_id,
            field_name,
            body.value,
            fact_ids=body.fact_ids,
            confidence=body.confidence,
            is_negotiable_or_irreversible=body.is_negotiable_or_irreversible,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"id": field_id, "ok": True}


@router.patch("/{plan_id}/ready")
def mark_plan_ready_endpoint(
    plan_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if application_plan_repo.mark_ready(conn, user["id"], plan_id):
        return {"ok": True}

    plan = application_plan_repo.get_plan(conn, user["id"], plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Application plan not found")
    raise HTTPException(status_code=409, detail=f"Plan status is {plan['status']}, cannot mark ready")


@router.patch("/{plan_id}/supersede")
def supersede_plan_endpoint(
    plan_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if not application_plan_repo.supersede_plan(conn, user["id"], plan_id):
        raise HTTPException(status_code=404, detail="Application plan not found")
    return {"ok": True}
