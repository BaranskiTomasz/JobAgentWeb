from pathlib import Path

import psycopg2
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import rate_limit
import users_repo
from config import INVITE_CODE
from db import get_db
from security import DUMMY_PASSWORD_HASH, hash_password, verify_password

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...), conn=Depends(get_db)):
    username = username.strip()
    rate_limit.enforce(request, "login", key=username.lower())
    user = users_repo.get_by_username(conn, username)
    # Always call verify_password, even for an unknown username — checking against
    # DUMMY_PASSWORD_HASH keeps the response time the same either way, so timing
    # alone can't be used to enumerate which usernames exist.
    valid = verify_password(password, user["password_hash"] if user else DUMMY_PASSWORD_HASH)
    if not user or not valid:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid username or password"}, status_code=400,
        )
    request.session["user_id"] = user["id"]
    request.session["session_epoch"] = user["session_epoch"]
    return RedirectResponse("/", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"errors": [], "username": "", "invite_code": ""})


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    invite_code: str = Form(""),
    conn=Depends(get_db),
):
    rate_limit.enforce(request, "register")
    username = username.strip()
    invite_code = invite_code.strip()

    # Independent per-field checks (not one elif chain) so a wrong password AND a
    # wrong invite code both get reported together — the old chain only ever
    # showed the first thing it hit, so e.g. a too-short password was invisible
    # until the (correct) invite code was fixed on a second round trip.
    errors = []
    if not INVITE_CODE:
        errors.append("Registration is currently closed.")
    elif invite_code != INVITE_CODE:
        errors.append("Invalid invite code.")

    if len(username) < 3:
        errors.append("Username must be at least 3 characters.")
    elif users_repo.get_by_username(conn, username):
        errors.append("That username is already taken.")

    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    elif password != password_confirm:
        errors.append("Passwords do not match.")

    if errors:
        # username/invite_code repopulated so a fixable mistake elsewhere doesn't
        # force retyping everything — passwords are never echoed back.
        return templates.TemplateResponse(
            request, "register.html",
            {"errors": errors, "username": username, "invite_code": invite_code},
            status_code=400,
        )

    try:
        user_id = users_repo.create(conn, username, hash_password(password))
    except psycopg2.errors.UniqueViolation:
        # Two concurrent registrations for the same username both pass the
        # get_by_username check above; the second INSERT trips the unique
        # constraint instead. get_db()'s commit would fail on this aborted
        # transaction otherwise, so roll back explicitly before responding.
        conn.rollback()
        return templates.TemplateResponse(
            request, "register.html",
            {"errors": ["That username is already taken."], "username": username, "invite_code": invite_code},
            status_code=400,
        )
    request.session["user_id"] = user_id
    request.session["session_epoch"] = 0  # matches the users.session_epoch column default
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request, conn=Depends(get_db)):
    user_id = request.session.get("user_id")
    if user_id is not None:
        # Bumps the DB epoch so every other outstanding cookie for this user (any
        # device) stops matching on its next request too — not just this one.
        users_repo.bump_session_epoch(conn, user_id)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
