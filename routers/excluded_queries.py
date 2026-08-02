from fastapi import APIRouter, Depends, HTTPException

import excluded_queries_repo
from db import get_db
from deps import get_current_user
from models import ExcludedQueryCreate

router = APIRouter(prefix="/api/excluded-search-queries", tags=["excluded-search-queries"])


@router.get("")
def list_all(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return excluded_queries_repo.get_all(conn, user["id"])


@router.get("/by-source")
def get_excluded(source: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return excluded_queries_repo.get_excluded(conn, user["id"], source)


@router.post("")
def exclude(body: ExcludedQueryCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    excluded_queries_repo.exclude(conn, user["id"], body.source, body.search_query, body.reason)
    return {"ok": True}


@router.post("/{excluded_id}/reinstate")
def reinstate(excluded_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not excluded_queries_repo.reinstate(conn, user["id"], excluded_id):
        raise HTTPException(status_code=404, detail="Excluded query not found")
    return {"ok": True}
