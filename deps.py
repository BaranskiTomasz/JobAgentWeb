from fastapi import Depends, HTTPException, Request

import users_repo
from db import get_db


def get_current_user(request: Request, conn=Depends(get_db)) -> dict:
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = users_repo.get_by_id(conn, user_id)
    if user is None:
        # Session points at a user that no longer exists (e.g. deleted by an
        # admin) — drop the stale session instead of leaving it around.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    if request.session.get("session_epoch") != user["session_epoch"]:
        # A logout (this device or another) bumped the DB epoch since this
        # cookie was issued — the signed cookie itself is still cryptographically
        # valid, so this is the only way "logged out" actually takes effect.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return user
