from fastapi import APIRouter, Depends, HTTPException

import candidate_preferences_repo
import criteria_repo
from db import get_db
from deps import get_current_user
from models import CandidatePreferencesCreate, CandidatePreferencesUpdate

router = APIRouter(prefix="/api/candidate-preferences", tags=["candidate-preferences"])


def _sync_criteria_from_preferences(conn, user_id: int, fields: dict) -> None:
    # Keeps the collector's location/rejected/preferred search criteria in
    # sync whenever preferences are saved from this dashboard. Deliberately
    # does NOT touch "title"/"search_query" criteria: JobAgent's own
    # equivalent flow derives those via a Claude call
    # (web/routes/candidate_preferences.py::_derive_search_queries), and this
    # service has no Anthropic integration of its own to do that with.
    work_mode = fields.get("work_mode") or []
    locations = []
    if "remote" in work_mode:
        locations += fields.get("remote_countries") or []
    if "hybrid" in work_mode or "onsite" in work_mode:
        locations += fields.get("hybrid_cities") or []
    criteria_repo.delete_by_type(conn, user_id, "location")
    for v in locations:
        criteria_repo.insert(conn, user_id, "location", v)

    criteria_repo.delete_by_type(conn, user_id, "rejected")
    for v in fields.get("avoided_tech") or []:
        criteria_repo.insert(conn, user_id, "rejected", v)

    criteria_repo.delete_by_type(conn, user_id, "preferred")
    for v in fields.get("extra_tech") or []:
        criteria_repo.insert(conn, user_id, "preferred", v)


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
    _sync_criteria_from_preferences(conn, user["id"], body.fields)
    return {"id": pref_id}


@router.post("/{pref_id}/activate")
def activate(pref_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not candidate_preferences_repo.set_active(conn, user["id"], pref_id):
        raise HTTPException(status_code=404, detail="Candidate preferences not found")
    return {"ok": True}


@router.patch("/{pref_id}")
def update(pref_id: int, body: CandidatePreferencesUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        found = candidate_preferences_repo.update(conn, user["id"], pref_id, body.fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="Candidate preferences not found")
    return {"ok": True}


@router.delete("/{pref_id}")
def delete(pref_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not candidate_preferences_repo.delete(conn, user["id"], pref_id):
        raise HTTPException(status_code=404, detail="Candidate preferences not found")
    return {"ok": True}
