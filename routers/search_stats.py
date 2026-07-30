from fastapi import APIRouter, Depends

import search_stats_repo
from db import get_db
from deps import get_current_user
from models import SearchStatRecord

router = APIRouter(prefix="/api/search-stats", tags=["search-stats"])


@router.post("")
def record(body: SearchStatRecord, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    search_stats_repo.record(
        conn, user["id"], body.session_id, body.source, body.search_query,
        body.location, body.cards_found, body.new_found,
    )
    return {"ok": True}


@router.get("/summary")
def summary(source: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return search_stats_repo.get_query_summary(conn, user["id"], source)


@router.get("/zero-yield")
def zero_yield(source: str, min_searches: int = 5, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return search_stats_repo.get_zero_yield_queries(conn, user["id"], source, min_searches)
