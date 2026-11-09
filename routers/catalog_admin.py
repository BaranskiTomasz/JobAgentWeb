import time
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from deps import require_automation_client

router = APIRouter(prefix="/api/catalog/collection", tags=["catalog-admin"])
catalog_collection_lock = Lock()
_MIN_SECONDS_BETWEEN_TRIGGERS = 900


class CatalogCollectionRunResponse(BaseModel):
    status: Literal["already_running", "cooldown", "trigger_requested"]


class CatalogCollectionStatusResponse(BaseModel):
    running: bool


@router.post("/run-now", response_model=CatalogCollectionRunResponse)
def run_catalog_collection_now(
    request: Request,
    user: dict[str, object] = Depends(require_automation_client),
) -> CatalogCollectionRunResponse:
    with catalog_collection_lock:
        if request.app.state.catalog_collection_running.is_set():
            return CatalogCollectionRunResponse(status="already_running")
        now = time.monotonic()
        last_trigger = request.app.state.catalog_collection_last_trigger
        if (
            last_trigger is not None
            and now - last_trigger < _MIN_SECONDS_BETWEEN_TRIGGERS
        ):
            return CatalogCollectionRunResponse(status="cooldown")
        request.app.state.scheduler.modify_job(
            "catalog_collection",
            next_run_time=datetime.now(timezone.utc),
        )
        request.app.state.catalog_collection_last_trigger = now
    return CatalogCollectionRunResponse(status="trigger_requested")


@router.get("/status", response_model=CatalogCollectionStatusResponse)
def get_catalog_collection_status(
    request: Request,
    user: dict[str, object] = Depends(require_automation_client),
) -> CatalogCollectionStatusResponse:
    return CatalogCollectionStatusResponse(
        running=request.app.state.catalog_collection_running.is_set(),
    )
