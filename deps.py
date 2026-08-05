import hmac

from fastapi import Depends, HTTPException, Request

import users_repo
from config import JOBAGENT_API_KEY, JOBAGENT_API_KEY_USER_ID
from db import get_db


def get_current_user(request: Request, conn=Depends(get_db)) -> dict:
    # The JobAgent desktop client authenticates with a static key, bypassing
    # session cookies entirely (so it never needs interactive re-login).
    # compare_digest avoids leaking key bytes through a timing side-channel.
    if JOBAGENT_API_KEY and JOBAGENT_API_KEY_USER_ID:
        header_key = request.headers.get("X-JobAgent-Api-Key")
        if header_key and hmac.compare_digest(header_key, JOBAGENT_API_KEY):
            user = users_repo.get_by_id(conn, int(JOBAGENT_API_KEY_USER_ID))
            if user is not None:
                # A static, non-expiring key shouldn't also grant admin rights,
                # even if the account it's scoped to happens to be an admin.
                request.state.trusted_client = True
                return user

    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = users_repo.get_by_id(conn, user_id)
    if user is None:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    if request.session.get("session_epoch") != user["session_epoch"]:
        # The signed cookie is still cryptographically valid after a logout;
        # bumping the DB epoch is what actually makes "logged out" take effect.
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request, user: dict = Depends(get_current_user)) -> dict:
    if getattr(request.state, "trusted_client", False):
        raise HTTPException(status_code=403, detail="Admin only")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return user
