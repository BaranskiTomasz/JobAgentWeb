from fastapi import APIRouter, Depends, HTTPException

import cv_profiles_repo
from db import get_db
from deps import get_current_user
from models import CVProfileCreate

router = APIRouter(prefix="/api/cv-profiles", tags=["cv-profiles"])


@router.get("")
def list_profiles(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return cv_profiles_repo.list_all(conn, user["id"])


@router.get("/active")
def get_active(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    profile = cv_profiles_repo.get_active(conn, user["id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="No active CV profile")
    return profile


@router.post("")
def create_profile(body: CVProfileCreate, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    profile_id = cv_profiles_repo.insert(conn, user["id"], body.filename, body.raw_text, body.parsed)
    return {"id": profile_id}


@router.post("/{profile_id}/activate")
def activate_profile(profile_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not cv_profiles_repo.set_active(conn, user["id"], profile_id):
        raise HTTPException(status_code=404, detail="CV profile not found")
    return {"ok": True}
