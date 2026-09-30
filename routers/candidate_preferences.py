from fastapi import APIRouter, Depends, HTTPException

import candidate_preferences_repo
import criteria_repo
from db import get_db
from deps import get_current_user
from models import CandidatePreferencesCreate, CandidatePreferencesUpdate

router = APIRouter(prefix="/api/candidate-preferences", tags=["candidate-preferences"])

_ROLE_QUERIES = {
    "developer": "Software Engineer",
    "qa": "QA Engineer",
    "devops": "DevOps Engineer",
    "data": "Data Engineer",
    "architect": "Software Architect",
    "team_lead": "Engineering Manager",
    "security": "Security Engineer",
}
_GENERIC_TECH = {"docker", "git", "ci/cd", "postgresql", "redis", "sql"}


def _search_queries(fields: dict) -> list[str]:
    queries = []
    for tech in fields.get("extra_tech") or []:
        value = tech.strip()
        if value and value.lower() not in _GENERIC_TECH:
            queries.append(value)
    for role in fields.get("role_types") or []:
        value = _ROLE_QUERIES.get(role, role.strip())
        if value:
            queries.append(value)
    return list(dict.fromkeys(queries))[:10]


def _sync_criteria_from_preferences(conn, user_id: int, fields: dict) -> None:
    work_mode = fields.get("work_mode") or []
    locations = []
    if "remote" in work_mode:
        if fields.get("work_country"):
            locations.append(fields["work_country"])
        else:
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

    criteria_repo.delete_by_type(conn, user_id, "title")
    criteria_repo.delete_by_type(conn, user_id, "search_query")
    for value in _search_queries(fields):
        criteria_repo.insert(conn, user_id, "title", value)


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
    _sync_criteria_from_preferences(conn, user["id"], candidate_preferences_repo.get_active(conn, user["id"]))
    return {"ok": True}


@router.patch("/{pref_id}")
def update(pref_id: int, body: CandidatePreferencesUpdate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        found = candidate_preferences_repo.update(conn, user["id"], pref_id, body.fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="Candidate preferences not found")
    active = candidate_preferences_repo.get_active(conn, user["id"])
    if active and active["id"] == pref_id:
        _sync_criteria_from_preferences(conn, user["id"], active)
    return {"ok": True}


@router.delete("/{pref_id}")
def delete(pref_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not candidate_preferences_repo.delete(conn, user["id"], pref_id):
        raise HTTPException(status_code=404, detail="Candidate preferences not found")
    return {"ok": True}
