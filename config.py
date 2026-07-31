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

# Signs the session cookie (Starlette SessionMiddleware). The dev default is
# fine for local/test runs; production (.env on the VPS) MUST set a real
# random secret — anyone who knows this value can forge session cookies.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-secret-key-change-in-production")

# Whether the session cookie is marked Secure (browser refuses to send it over
# plain HTTP). Defaults on — set SESSION_HTTPS_ONLY=false only for local dev
# over http://127.0.0.1, never in production (site is served over HTTPS there).
SESSION_HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "true").lower() != "false"

# Shared invite code required at /register. Unset (None) means registration is
# closed entirely — deny-by-default, so forgetting to configure this on a new
# deployment can't accidentally leave signups open to anyone who finds the URL.
INVITE_CODE = os.getenv("INVITE_CODE")
