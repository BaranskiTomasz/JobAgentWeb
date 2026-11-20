from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

import apply_execution_repo
from db import get_db
from deps import get_current_user

router = APIRouter(tags=["application-executions"])


class ExecutionCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    idempotency_key: str | None = None
    autonomy_decision_id: int | None = None


class ExecutionStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    last_error: str | None = None
    external_application_id: str | None = None


@router.post("/api/application-plans/{plan_id}/executions")
def create_execution_endpoint(
    plan_id: int,
    body: ExecutionCreate,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    try:
        return apply_execution_repo.create_execution(
            conn,
            user["id"],
            plan_id,
            autonomy_decision_id=body.autonomy_decision_id,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/api/application-plans/{plan_id}/executions")
def list_executions_endpoint(
    plan_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    return apply_execution_repo.list_executions_for_plan(conn, user["id"], plan_id)


@router.get("/api/executions/{execution_id}")
def get_execution_endpoint(
    execution_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    execution = apply_execution_repo.get_execution(conn, user["id"], execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Application execution not found")
    return execution


@router.patch("/api/executions/{execution_id}/status")
def update_execution_status_endpoint(
    execution_id: int,
    body: ExecutionStatusUpdate,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    execution = apply_execution_repo.get_execution(conn, user["id"], execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Application execution not found")

    try:
        return apply_execution_repo.update_status(
            conn,
            user["id"],
            execution_id,
            body.status,
            last_error=body.last_error,
            external_application_id=body.external_application_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
