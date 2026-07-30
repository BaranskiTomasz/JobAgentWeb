from fastapi import APIRouter, Depends, HTTPException

import candidate_preferences_repo
from db import get_db
from deps import get_current_user
from models import CandidatePreferencesCreate, CandidatePreferencesUpdate

router = APIRouter(prefix="/api/candidate-preferences", tags=["candidate-preferences"])


@router.get("")
def list_all(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return candidate_preferences_repo.list_all(conn, user["id"])


@router.get("/active")
def get_active(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    prefs = candidate_preferences_repo.get_active(conn, user["id"])
    if prefs is None:
        raise HTTPException(status_code=404, detail="No active candidate preferences")
    return prefs


@router.post("")
def create(body: CandidatePreferencesCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        pref_id = candidate_preferences_repo.insert(conn, user["id"], body.cv_profile_id, body.fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": pref_id}


@router.post("/{pref_id}/activate")
def activate(pref_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    candidate_preferences_repo.set_active(conn, user["id"], pref_id)
    return {"ok": True}


@router.patch("/{pref_id}")
def update(pref_id: int, body: CandidatePreferencesUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        candidate_preferences_repo.update(conn, user["id"], pref_id, body.fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/{pref_id}")
def delete(pref_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    candidate_preferences_repo.delete(conn, user["id"], pref_id)
    return {"ok": True}
