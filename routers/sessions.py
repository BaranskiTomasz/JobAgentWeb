from fastapi import APIRouter, Depends, HTTPException

import sessions_repo
from db import get_db
from deps import get_current_user
from models import SessionFinish

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("")
def start(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    try:
        session_id = sessions_repo.start(conn, user["id"])
    except sessions_repo.SessionAlreadyActiveError:
        raise HTTPException(
            status_code=409,
            detail="A run is already active for this account. If this is stale "
                   "(e.g. a crashed process), cancel it first: POST /api/sessions/cancel-active.",
        )
    return {"id": session_id}


@router.patch("/{session_id}/finish")
def finish(session_id: int, body: SessionFinish, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    sessions_repo.finish(conn, user["id"], session_id, body.jobs_found, body.jobs_scored, body.status)
    return {"ok": True}


@router.post("/cancel-active")
def cancel_active(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    sessions_repo.cancel_active(conn, user["id"])
    return {"ok": True}


@router.get("/has-active")
def has_active(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"active": sessions_repo.has_active_run(conn, user["id"])}


@router.get("/last-finished")
def last_finished(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    return {"finished_at": sessions_repo.get_last_finished_at(conn, user["id"])}


@router.get("/latest")
def latest(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    session = sessions_repo.get_latest(conn, user["id"])
    return {"session": session}
