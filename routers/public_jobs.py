from fastapi import APIRouter, Depends, HTTPException, Query

import catalog_repo
from db import get_db
from deps import get_current_user
from models import CatalogImport, PublicJobOut


router = APIRouter(prefix="/api/public/jobs", tags=["public-jobs"])


def _validate(technology: str, country: str) -> tuple[str, str]:
    technology = technology.lower()
    country = country.upper()
    if technology not in catalog_repo.TECHNOLOGIES:
        raise HTTPException(status_code=422, detail="Unsupported technology")
    if country not in catalog_repo.COUNTRIES:
        raise HTTPException(status_code=422, detail="Unsupported work country")
    return technology, country


@router.get("", response_model=list[PublicJobOut])
def list_public_jobs(
    technology: str = "python",
    country: str = "PL",
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db),
):
    technology, country = _validate(technology, country)
    return catalog_repo.list_jobs(conn, technology, country, limit, offset)


@router.get("/facets")
def public_job_facets(country: str = "PL", conn=Depends(get_db)):
    country = country.upper()
    if country not in catalog_repo.COUNTRIES:
        raise HTTPException(status_code=422, detail="Unsupported work country")
    return catalog_repo.facets(conn, country)


@router.post("/personalize")
def personalize_catalog(body: CatalogImport, user: dict = Depends(get_current_user), conn=Depends(get_db)):
    technology, country = _validate(body.technology, body.country)
    return {"attached": catalog_repo.attach_to_user(conn, user["id"], technology, country)}
