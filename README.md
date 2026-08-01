# JobAgentWeb

The multi-tenant backend for [JobAgent](../JobAgent) — a FastAPI + Postgres service that owns all job-search data. Any number of users register their own account, browse and triage their own job pool from a small built-in dashboard, and connect their local JobAgent installation to this service as an authenticated API client. JobAgent itself has no database of its own; every read/write it makes is an HTTP call here.

---

## Architecture

### Shared pool vs. per-user data

The schema splits cleanly in two, defined in `migrations.py`:

- **Shared** (`job_postings`, `job_embeddings`) — a posting's text, source metadata, and LLM-extracted tags are objective facts about the listing, independent of any candidate. Scraped and extracted once, reused by every user who finds the same URL (deduplicated on `url`).
- **Per-user** (`user_job_states`, plus `criteria`, `cv_profiles`, `preference_profiles`, `candidate_preferences`, `usage_log`, `cost_summaries`, `search_stats`, `sessions`, `excluded_search_queries`, `dismissed_score_items`) — everything that's a judgment about *this* candidate: status, score, rank, would-apply flag, preferences, CV, cost history. Every one of these tables carries a `user_id` FK with `ON DELETE CASCADE`, so deleting a user's account cleanly removes everything of theirs without touching the shared pool.

`user_job_states` joins to `job_postings` on `(user_id, job_id)` — one row per (user, posting) pair. This is why "delete jobs" (`jobs_repo.delete_by_filter`) only ever removes `user_job_states` rows: it's removing the posting from *your* view, never the shared posting other users may still have.

### Auth

Username/password, bcrypt-hashed (`security.py`), backed by Starlette's signed-cookie `SessionMiddleware` — no JWT, no OAuth, no separate session table. `deps.get_current_user` resolves the session cookie to a `users` row on every request; `deps.require_admin` additionally gates on `is_admin`. Registration requires a shared invite code (`config.INVITE_CODE`, checked in `routers/auth.py`) — unset it and `/register` refuses everyone, deny-by-default. See [Deployment](#deployment) for how the current reference deployment also restricts network-level access on top of that.

### Startup

`main.py`'s `lifespan` calls `migrations.init_db(conn)` on every app start. It's fully idempotent (`CREATE TABLE IF NOT EXISTS` + `ADD COLUMN IF NOT EXISTS`), so there's no separate migration command to remember — pulling new code and restarting the process is the whole migration step.

---

## Setup

### Prerequisites

- Python 3.11+
- A Postgres instance (local or remote)

### Installation

```bash
git clone <repo-url>
cd JobAgentWeb
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

### Environment

```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=jobagent
POSTGRES_USER=jobagent
POSTGRES_PASSWORD=...

SECRET_KEY=...              # required in production — signs the session cookie
SESSION_HTTPS_ONLY=true     # set to false only for local dev over plain http://127.0.0.1
INVITE_CODE=...             # required for /register to accept anyone at all
```

`SECRET_KEY` has an insecure dev-only default (`dev-only-insecure-secret-key-change-in-production`) — **must** be overridden with a real random value in any environment reachable by anyone but you, or session cookies are forgeable. `SESSION_HTTPS_ONLY` defaults on; a `Secure`-flagged cookie is never sent back over plain HTTP, so local dev against `http://127.0.0.1` needs it set to `false` or every login-dependent request silently breaks. `INVITE_CODE` has no default at all — leaving it unset is what keeps `/register` closed (see [Auth](#auth)), so set it deliberately, not because the app demands a value to boot.

### Run

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000` — first-time visitors are redirected to `/login`, with a link to `/register`.

---

## API surface

All JSON endpoints live under `/api/*` and require a session cookie (`deps.get_current_user`); browser routes (`/`, `/login`, `/register`, `/admin`) render Jinja2 templates.

| Router | Prefix | Covers |
|--------|--------|--------|
| `auth` | `/login`, `/register`, `/logout` | Session lifecycle |
| `admin` | `/admin` | User list + delete (admin only) |
| `jobs` | `/api/jobs` | Search, stats, status/score/ranking updates, feedback export |
| `dismissed_items` | `/api/jobs/*`, `/api/dismissed-items` | Score-factor dismissals feeding preference distillation |
| `cv_profiles` | `/api/cv-profiles` | CV upload metadata + active profile |
| `criteria` | `/api/criteria` | Collector search-dimension config |
| `preference_profiles` | `/api/preference-profile` | Distilled preference signals |
| `candidate_preferences` | `/api/candidate-preferences` | Questionnaire answers |
| `excluded_queries` | `/api/excluded-search-queries` | Auto-pruned search queries |
| `search_stats` | `/api/search-stats` | Per-query collection outcome tracking |
| `sessions` | `/api/sessions` | Pipeline run tracking (start/finish/cancel/latest), one active run per user |
| `usage` | `/api/usage` | Token/cost logging and per-run summaries |
| `embeddings` | `/api/embeddings` | Shared vector storage + retrieval |
| `evaluation` | `/api/eval` | Precision@K, divergence cases, would-apply precision — JobAgent proxies this rather than recomputing it |
| `sources` | `/api/sources` | Distinct job sources for *this user's* pool, for the dashboard's source filter dropdown |

Every per-user router scopes its queries by `user_id` from the session — there is no endpoint that returns another user's `user_job_states`-backed data. `job_postings`/`job_embeddings` reads are shared by design (any authenticated user can see the same posting), never keyed by ownership.

---

## Deployment

The reference deployment runs on a single VPS: this app under `uvicorn` (systemd unit `jobagentweb.service`), Postgres locally, and Caddy in front for TLS. Two details matter beyond the basics:

- **Caddy only reverse-proxies — it doesn't gate access itself.** There's no `basic_auth` in front of the site; this app's own per-user session login (plus invite-only registration) is the access control. Caddy adds `X-Robots-Tag: noindex` and a disallow-everything `robots.txt` to keep the instance out of search indexes, nothing more. JobAgent (the API client) still reaches this host over a private WireGuard tunnel rather than the public domain, but that's a network-topology choice, not a workaround for a proxy-level auth wall.
- **Firewall**: if Postgres and this app are reachable over a tunnel interface (e.g. WireGuard's `wg0`), scope firewall rules to that interface specifically, not open to `0.0.0.0` — this app has no additional network-layer access control beyond the OS-level firewall.

Provisioning scripts (`bootstrap.sh`, `postgres_setup.sql`, `Caddyfile`, `jobagentweb.service`, `.env` example, WireGuard configs) live in the **JobAgent** repo's `deploy/` directory, not here — this app predates the split into its own repo, and deployment assets were never moved over. Follow that repo's `deploy/bootstrap.sh` for a fresh VPS setup; it clones this repo (`JobAgentWeb.git`) to `/opt/jobagentweb` and installs the matching systemd unit.

Opening registration to the public beyond the current private/invite-only setup — and how (open vs. invite codes) — is a deliberate decision to make explicitly when the time comes, not a default to fall into.

---

## Running tests

```bash
pytest
```

`tests/conftest.py` points at a dedicated `jobagentweb_test` Postgres database (never the real `jobagent` one) and truncates every table before each test (`_clean_tables`, autouse). Fixtures of note:

- `client` — a bare `TestClient`, unauthenticated
- `user` / `other_user` / `admin_user` — fresh DB rows with known plaintext passwords
- `logged_in_client` / `other_logged_in_client` / `admin_client` — pre-authenticated `TestClient`s
- `db_conn` — a raw pooled connection, for the rare test that needs to set up data no API can produce (e.g. a legacy pre-migration row shape)

Set the Postgres env vars (`POSTGRES_HOST`, etc.) to point at your test database before running — `conftest.py` defaults to the same WireGuard-tunneled host (`10.66.0.1`) used in the reference deployment, which won't resolve unless you're on that tunnel.

JobAgent's own test suite spins up a real instance of *this* app as a subprocess against the same `jobagentweb_test` database — see JobAgent's README for that side of the setup.
