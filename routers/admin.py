from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import dedup_repo
import users_repo
from config import INVITE_CODE
from db import get_db
from deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request, user: dict = Depends(require_admin), conn=Depends(get_db)):
    users = users_repo.list_all(conn)
    return templates.TemplateResponse(
        request, "admin.html",
        {"users": users, "current_user_id": user["id"], "invite_code": INVITE_CODE},
    )


@router.get("/dedup", response_class=HTMLResponse)
def dedup_page(request: Request, user: dict = Depends(require_admin), conn=Depends(get_db)):
    candidates = dedup_repo.list_pending_candidates(conn)
    return templates.TemplateResponse(
        request, "admin_dedup.html",
        {"candidates": candidates, "current_user_id": user["id"]},
    )


@router.post("/dedup/{match_id}/merge")
def merge_dedup_candidate(
    match_id: int,
    job_id_low: str = Form(...),
    job_id_high: str = Form(...),
    survivor_job_id: str = Form(...),
    user: dict = Depends(require_admin),
    conn=Depends(get_db),
):
    dedup_repo.merge_jobs(
        conn, job_id_low, job_id_high, survivor_job_id=survivor_job_id,
        match_id=match_id, match_method="manual_merge", confidence=1.0,
    )
    return RedirectResponse("/admin/dedup", status_code=303)


@router.post("/dedup/{match_id}/reject")
def reject_dedup_candidate(
    match_id: int, user: dict = Depends(require_admin), conn=Depends(get_db),
):
    dedup_repo.reject_match(conn, match_id)
    return RedirectResponse("/admin/dedup", status_code=303)


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, user: dict = Depends(require_admin), conn=Depends(get_db)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account from the admin panel")
    users_repo.delete(conn, user_id)
    return RedirectResponse("/admin", status_code=303)
