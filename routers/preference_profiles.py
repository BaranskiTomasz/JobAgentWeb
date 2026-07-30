from fastapi import APIRouter, Depends

import preference_profiles_repo
from db import get_db
from deps import get_current_user
from models import PreferenceProfileSave

router = APIRouter(prefix="/api/preference-profile", tags=["preference-profile"])


@router.get("")
def get_latest(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    profile = preference_profiles_repo.get_latest(conn, user["id"])
    return {"profile": profile}


@router.post("")
def save(body: PreferenceProfileSave, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    preference_profiles_repo.save(
        conn, user["id"], body.signals, body.applied_count, body.rejected_count, body.dismissed_count,
    )
    return {"ok": True}
