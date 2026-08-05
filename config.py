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

# Signs the session cookie. Anyone who knows this value can forge a login for
# any user, so there's no safe fallback: every environment must set a real one.
_INSECURE_DEFAULT = "dev-only-insecure-secret-key-change-in-production"
SECRET_KEY = os.getenv("SECRET_KEY", _INSECURE_DEFAULT)
if SECRET_KEY == _INSECURE_DEFAULT:
    raise ValueError(
        "SECRET_KEY not set (or left at its insecure placeholder) - sessions could be "
        "forged. Set a real random value in .env, e.g. `python -c \"import secrets; "
        "print(secrets.token_hex(32))\"`."
    )

# Set SESSION_HTTPS_ONLY=false only for local dev over plain http://127.0.0.1.
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "true").lower() != "false"

# No invite code configured means registration is closed, not open to anyone.
INVITE_CODE = os.getenv("INVITE_CODE")

# JobAgent's test suite registers a fresh user per test and needs this off;
# individual rate-limit tests flip it back with monkeypatch.
RATE_LIMIT_ENABLED = os.getenv("DISABLE_RATE_LIMIT", "false").lower() != "true"

# Lets the local JobAgent desktop client authenticate with a static key instead
# of a browser session cookie (see deps.py::get_current_user), scoped to one
# user_id. Both must be set for the bypass to activate.
JOBAGENT_API_KEY = os.getenv("JOBAGENT_API_KEY")
JOBAGENT_API_KEY_USER_ID = os.getenv("JOBAGENT_API_KEY_USER_ID")
