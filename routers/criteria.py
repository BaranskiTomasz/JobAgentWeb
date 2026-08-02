from fastapi import APIRouter, Depends, HTTPException

import criteria_repo
from db import get_db
from deps import get_current_user
from models import CriteriaCreate, CriteriaToggle

router = APIRouter(prefix="/api/criteria", tags=["criteria"])


@router.get("")
def list_criteria(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return criteria_repo.get_all(conn, user["id"])


@router.get("/active")
def active_criteria(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return criteria_repo.get_active_dict(conn, user["id"])


@router.post("")
def create_criteria(body: CriteriaCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        criteria_repo.insert(conn, user["id"], body.type, body.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.patch("/{criteria_id}")
def toggle_criteria(criteria_id: int, body: CriteriaToggle, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not criteria_repo.toggle(conn, user["id"], criteria_id, body.is_active):
        raise HTTPException(status_code=404, detail="Criteria not found")
    return {"ok": True}


@router.delete("/{criteria_id}")
def delete_criteria(criteria_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not criteria_repo.delete(conn, user["id"], criteria_id):
        raise HTTPException(status_code=404, detail="Criteria not found")
    return {"ok": True}


@router.delete("/by-type/{type_}")
def delete_criteria_by_type(type_: str, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    deleted = criteria_repo.delete_by_type(conn, user["id"], type_)
    return {"deleted": deleted}
