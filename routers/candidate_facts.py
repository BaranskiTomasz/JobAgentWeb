from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

import candidate_facts_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/candidate-facts", tags=["candidate-facts"])

_FACT_TYPES = Literal[
    "work_experience",
    "education",
    "skill",
    "certification",
    "project",
    "language",
    "achievement",
    "other",
]


class CandidateFactCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_type: _FACT_TYPES
    value: str


class CandidateFactOut(BaseModel):
    id: int
    user_id: int
    fact_type: str
    value: str
    source_quote: str | None = None
    source: str
    source_ref: int | None = None
    is_active: int
    created_at: datetime | None = None


@router.get("", response_model=list[CandidateFactOut])
def list_candidate_facts(
    fact_type: str | None = Query(None),
    active_only: bool = Query(True),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if active_only:
        return candidate_facts_repo.get_active(conn, user["id"], fact_type=fact_type)
    facts = candidate_facts_repo.get_all(conn, user["id"])
    if fact_type is not None:
        facts = [f for f in facts if f.get("fact_type") == fact_type]
    return facts


@router.post("", response_model=CandidateFactOut)
def create_candidate_fact(
    body: CandidateFactCreate,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    fact_id = candidate_facts_repo.insert(
        conn,
        user["id"],
        body.fact_type,
        body.value,
        source="manual",
        source_quote=None,
        source_ref=None,
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT id, user_id, fact_type, value, source_quote, source, source_ref, is_active, created_at "
        "FROM candidate_facts WHERE id = %s AND user_id = %s",
        (fact_id, user["id"]),
    )
    row = cur.fetchone()
    return {
        "id": row[0],
        "user_id": row[1],
        "fact_type": row[2],
        "value": row[3],
        "source_quote": row[4],
        "source": row[5],
        "source_ref": row[6],
        "is_active": row[7],
        "created_at": row[8],
    }


@router.patch("/{fact_id}/deactivate")
def deactivate_candidate_fact(
    fact_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if not candidate_facts_repo.deactivate(conn, user["id"], fact_id):
        raise HTTPException(status_code=404, detail="Candidate fact not found")
    return {"ok": True}


@router.delete("/{fact_id}")
def delete_candidate_fact(
    fact_id: int,
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    if not candidate_facts_repo.delete(conn, user["id"], fact_id):
        raise HTTPException(status_code=404, detail="Candidate fact not found")
    return {"ok": True}
