from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import users_repo
from db import get_db
from deps import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("", response_class=HTMLResponse)
def admin_page(request: Request, user: dict = Depends(require_admin), conn=Depends(get_db)):
    users = users_repo.list_all(conn)
    return templates.TemplateResponse(request, "admin.html", {"users": users, "current_user_id": user["id"]})


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, user: dict = Depends(require_admin), conn=Depends(get_db)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account from the admin panel")
    users_repo.delete(conn, user_id)
    return RedirectResponse("/admin", status_code=303)
