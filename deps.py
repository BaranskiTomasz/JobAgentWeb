import hmac

from fastapi import Depends, HTTPException, Request
from psycopg2.extensions import connection as PgConnection

import automation_keys_repo
import users_repo
from config import JOBAGENT_API_KEY, JOBAGENT_API_KEY_USER_ID
from db import get_db


def _authenticate_automation_key(
    request: Request,
    conn: PgConnection,
    header_key: str,
) -> dict[str, object]:
    """Resolve an automation key to its owner, or raise 401.

    This path is terminal because degrading to cookie authentication could
    silently run the pipeline as a different user.
    """
    if JOBAGENT_API_KEY and JOBAGENT_API_KEY_USER_ID:
        if hmac.compare_digest(header_key, JOBAGENT_API_KEY):
            user = users_repo.get_by_id(conn, int(JOBAGENT_API_KEY_USER_ID))
            if user is not None:
                request.state.trusted_client = True
                request.state.automation_can_access_catalog = True
                return user

            raise HTTPException(status_code=401, detail="Invalid automation key")

    key = automation_keys_repo.get_by_raw_key(conn, header_key)
    if key is not None:
        user = users_repo.get_by_id(conn, key["user_id"])
        if user is not None:
            request.state.trusted_client = True
            request.state.automation_can_access_catalog = key["can_access_catalog"]
            return user

    raise HTTPException(status_code=401, detail="Invalid automation key")


def get_current_user(
    request: Request,
    conn: PgConnection = Depends(get_db),
) -> dict[str, object]:
    header_key = request.headers.get("X-JobAgent-Api-Key")
    if header_key:
        return _authenticate_automation_key(request, conn, header_key)

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


def require_admin(
    request: Request,
    user: dict[str, object] = Depends(get_current_user),
) -> dict[str, object]:
    if getattr(request.state, "trusted_client", False):
        raise HTTPException(status_code=403, detail="Admin only")
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def require_automation_client(
    request: Request,
    user: dict[str, object] = Depends(get_current_user),
) -> dict[str, object]:
    if getattr(request.state, "trusted_client", False):
        return user
    raise HTTPException(status_code=403, detail="Automation client only")


def require_catalog_automation_client(
    request: Request,
    user: dict[str, object] = Depends(require_automation_client),
) -> dict[str, object]:
    if getattr(request.state, "automation_can_access_catalog", False):
        return user
    raise HTTPException(status_code=403, detail="Catalog automation client only")
