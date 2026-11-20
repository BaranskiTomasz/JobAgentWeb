import logging

from fastapi import APIRouter, Depends, HTTPException

import candidate_facts_repo
import cv_fact_extractor
import cv_profiles_repo
from db import get_db
from deps import get_current_user
from models import CVProfileCreate

logger = logging.getLogger(__name__)

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
    previous = cv_profiles_repo.get_active(conn, user["id"])
    previous_profile_id = previous["id"] if previous else None

    profile_id = cv_profiles_repo.insert(conn, user["id"], body.filename, body.raw_text, body.parsed)

    # A SAVEPOINT, not a bare try/except: get_db()'s commit() runs at the end
    # of this whole request, on the SAME connection/transaction as the insert
    # above -- a raised DB error here (not just an extraction error) leaves
    # Postgres in an aborted-transaction state, and committing an aborted
    # transaction silently loses the already-inserted CV profile too, even
    # though this route still returns 200. Rolling back to a savepoint
    # recovers the connection without discarding the insert that preceded it.
    cur = conn.cursor()
    cur.execute("SAVEPOINT cv_fact_extraction")
    try:
        facts = cv_fact_extractor.extract_facts_from_cv(body.raw_text)
        if facts:
            if previous_profile_id is not None:
                candidate_facts_repo.deactivate_by_source(conn, user["id"], "cv_upload", previous_profile_id)
            candidate_facts_repo.bulk_insert(
                conn,
                user["id"],
                [{**f, "source": "cv_upload", "source_ref": profile_id} for f in facts],
            )
    except Exception as e:
        logger.warning("Failed to extract or store candidate facts for profile %s: %s", profile_id, e)
        cur.execute("ROLLBACK TO SAVEPOINT cv_fact_extraction")

    return {"id": profile_id}


@router.post("/{profile_id}/activate")
def activate_profile(profile_id: int, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    if not cv_profiles_repo.set_active(conn, user["id"], profile_id):
        raise HTTPException(status_code=404, detail="CV profile not found")
    return {"ok": True}
