import os

from dotenv import load_dotenv

load_dotenv()

POSTGRES = {
    "host":     os.getenv("POSTGRES_HOST", "localhost"),
    "port":     int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname":   os.getenv("POSTGRES_DB", "jobagent"),
    "user":     os.getenv("POSTGRES_USER", "jobagent"),
    "password": os.getenv("POSTGRES_PASSWORD"),
}

# Signs the session cookie (Starlette SessionMiddleware). Anyone who knows this
# value can forge a session cookie for any user, so — unlike settings with a
# safe default — there is no usable fallback: every environment (including
# local dev) must set a real random secret in .env.
_INSECURE_DEFAULT = "dev-only-insecure-secret-key-change-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", _INSECURE_DEFAULT)
if SECRET_KEY == _INSECURE_DEFAULT:
    raise ValueError(
        "SECRET_KEY not set (or left at its insecure placeholder) — sessions could be "
        "forged. Set a real random value in .env, e.g. `python -c \"import secrets; "
        "print(secrets.token_hex(32))\"`."
    )

# Whether the session cookie is marked Secure (browser refuses to send it over
# plain HTTP). Defaults on — set SESSION_HTTPS_ONLY=false only for local dev
# over http://127.0.0.1, never in production (site is served over HTTPS there).
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "true").lower() != "false"

# Shared invite code required at /register. Unset (None) means registration is
# closed entirely — deny-by-default, so forgetting to configure this on a new
# deployment can't accidentally leave signups open to anyone who finds the URL.
INVITE_CODE = os.getenv("INVITE_CODE")

# On by default (production). Test harnesses that legitimately hammer /login or
# /register at volume (e.g. JobAgent's suite registers a fresh user per test) set
# DISABLE_RATE_LIMIT=true; individual tests of the limiter itself flip this back
# with monkeypatch.setattr("config.RATE_LIMIT_ENABLED", True).
RATE_LIMIT_ENABLED = os.getenv("DISABLE_RATE_LIMIT", "false").lower() != "true"
