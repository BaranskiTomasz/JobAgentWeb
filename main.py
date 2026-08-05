from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import candidate_preferences_repo
import jobs_repo
import migrations
import users_repo
from config import SECRET_KEY, SESSION_HTTPS_ONLY
from db import _get_pool, get_db
from routers import (
    admin, auth, candidate_preferences, criteria, cv_profiles, dismissed_items,
    embeddings, evaluation, excluded_queries, jobs, preference_profiles,
    search_stats, sessions, sources, usage,
)

_BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = _get_pool().getconn()
    try:
        migrations.init_db(conn)
    finally:
        _get_pool().putconn(conn)
    yield


app = FastAPI(title="JobAgentWeb", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, https_only=SESSION_HTTPS_ONLY)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(jobs.router)
app.include_router(dismissed_items.router)
app.include_router(cv_profiles.router)
app.include_router(criteria.router)
app.include_router(preference_profiles.router)
app.include_router(candidate_preferences.router)
app.include_router(excluded_queries.router)
app.include_router(search_stats.router)
app.include_router(sessions.router)
app.include_router(usage.router)
app.include_router(embeddings.router)
app.include_router(sources.router)
app.include_router(evaluation.router)
app.mount("/static", StaticFiles(directory=_BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=_BASE_DIR / "templates")


def _require_user(request: Request, conn) -> dict | None:
    # See deps.get_current_user for why the session_epoch check exists.
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = users_repo.get_by_id(conn, user_id)
    if user is None or request.session.get("session_epoch") != user["session_epoch"]:
        request.session.clear()
        return None
    return user


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, view: str | None = None, conn=Depends(get_db)):
    user = _require_user(request, conn)
    if user is None:
        # Distinct from landing.html, which assumes an already-logged-in,
        # zero-jobs account and addresses the user by username.
        return templates.TemplateResponse(request, "public_landing.html", {"user": None})
    stats = jobs_repo.get_stats(conn, user["id"])
    if stats["total"] == 0 and view != "dashboard":
        return templates.TemplateResponse(request, "landing.html", {"user": user})
    return templates.TemplateResponse(request, "dashboard.html", {"user": user})


@app.get("/how-it-works", response_class=HTMLResponse)
def how_it_works(request: Request, conn=Depends(get_db)):
    # Reachable logged-out: public_landing.html links here for more detail.
    user = _require_user(request, conn)
    return templates.TemplateResponse(request, "how_it_works.html", {"user": user})


@app.get("/preferences", response_class=HTMLResponse)
def preferences_page(request: Request, conn=Depends(get_db)):
    user = _require_user(request, conn)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    prefs = candidate_preferences_repo.get_active(conn, user["id"])
    return templates.TemplateResponse(request, "preferences.html", {"user": user, "prefs": prefs})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
