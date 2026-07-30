from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import migrations
import users_repo
from config import SECRET_KEY, SESSION_HTTPS_ONLY
from db import _get_pool, get_db
from routers import (
    admin, auth, candidate_preferences, criteria, cv_profiles, dismissed_items,
    embeddings, excluded_queries, jobs, preference_profiles, search_stats,
    sessions, usage,
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
app.mount("/static", StaticFiles(directory=_BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=_BASE_DIR / "templates")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, conn=Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    user = users_repo.get_by_id(conn, user_id)
    if user is None:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html", {"user": user})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
