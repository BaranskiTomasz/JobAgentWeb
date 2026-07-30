from fastapi import APIRouter, Depends

import dismissed_items_repo
from db import get_db
from deps import get_current_user

router = APIRouter(prefix="/api/dismissed-items", tags=["dismissed-items"])


@router.get("/recent")
def recent(limit: int = 50, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return dismissed_items_repo.get_recent(conn, user["id"], limit)


@router.get("/count")
def count(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"count": dismissed_items_repo.count_all(conn, user["id"])}
