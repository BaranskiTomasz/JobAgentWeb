from fastapi import APIRouter, Depends, HTTPException, Query

import catalog_repo
from db import get_db
from deps import get_current_user
from models import CatalogImport, PublicJobOut, PublicJobSearchOut


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


@router.get("/search", response_model=PublicJobSearchOut)
def search_public_jobs(
    technology: str = "python", country: str = "PL",
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
    q: str | None = Query(None, max_length=200), source: str | None = Query(None, max_length=100),
    company: str | None = Query(None, max_length=200), seniority: str | None = None,
    skill: str | None = Query(None, max_length=100), role_family: str | None = None,
    contract_type: str | None = None, currency: str | None = None,
    salary_min: float | None = Query(None, ge=0), salary_period: str | None = None,
    working_language: str | None = None,
    timezone: str | None = Query(None, max_length=100), company_type: str | None = None,
    company_stage: str | None = Query(None, max_length=100),
    team_size: str | None = Query(None, max_length=100),
    industry: str | None = Query(None, max_length=100), on_call: bool | None = None,
    travel: str | None = Query(None, max_length=100),
    office_visits: str | None = Query(None, max_length=100),
    sort: str = Query("date", pattern="^(date|company|title|salary)$"), conn=Depends(get_db),
):
    technology, country = _validate(technology, country)
    return catalog_repo.search_jobs(
        conn, technology, country, limit, offset, query=q, source=source, company=company,
        seniority=seniority, skill=skill, role_family=role_family,
        contract_type=contract_type, currency=currency, salary_min=salary_min,
        salary_period=salary_period, working_language=working_language, timezone=timezone,
        company_type=company_type, company_stage=company_stage, team_size=team_size,
        industry=industry, on_call=on_call, travel=travel, office_visits=office_visits,
        sort=sort,
    )


@router.get("/filter-options")
def public_job_filter_options(technology: str = "python", country: str = "PL", conn=Depends(get_db)):
    technology, country = _validate(technology, country)
    return catalog_repo.filter_options(conn, technology, country)


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
