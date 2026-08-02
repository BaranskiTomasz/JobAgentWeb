import hmac

from fastapi import Depends, HTTPException, Request

import users_repo
from config import JOBAGENT_API_KEY, JOBAGENT_API_KEY_USER_ID
from db import get_db


def get_current_user(request: Request, conn=Depends(get_db)) -> dict:
    # Trusted-client bypass: the local JobAgent desktop installation authenticates
    # with a static key instead of a browser session cookie, so it's immune to
    # session expiry and the session_epoch logout mechanism below — this is the
    # one identity that should never need interactive re-login. Scoped to a
    # single, explicitly configured user_id; only active when both env vars are
    # set. hmac.compare_digest avoids a timing side-channel on the comparison.
    if JOBAGENT_API_KEY and JOBAGENT_API_KEY_USER_ID:
        header_key = request.headers.get("X-JobAgent-Api-Key")
        if header_key and hmac.compare_digest(header_key, JOBAGENT_API_KEY):
            user = users_repo.get_by_id(conn, int(JOBAGENT_API_KEY_USER_ID))
            if user is not None:
                return user

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
