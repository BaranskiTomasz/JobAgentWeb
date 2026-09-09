# Idempotent schema, safe to run on every startup.
_SCHEMA = """
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        username      TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin      INTEGER DEFAULT 0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS job_postings (
        id               TEXT PRIMARY KEY,
        title            TEXT NOT NULL,
        company          TEXT,
        location         TEXT,
        url              TEXT UNIQUE,
        description      TEXT,
        source           TEXT DEFAULT 'linkedin',
        source_id        TEXT,
        search_query     TEXT,
        structured_data  JSONB,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings(company);

    CREATE TABLE IF NOT EXISTS job_embeddings (
        job_id     TEXT PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
        embedding  TEXT,
        model      TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS user_job_states (
        id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        job_id              TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        status              TEXT DEFAULT 'new',
        score               REAL,
        score_reason        TEXT,
        score_breakdown     JSONB,
        rejection_reason    TEXT,
        embedding_score     REAL,
        rerank_score        REAL,
        listwise_rank       INTEGER,
        rank_reason         TEXT,
        debate_flag         TEXT,
        debate_note         TEXT,
        would_apply         INTEGER,
        would_apply_reason  TEXT,
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, job_id)
    );

    DROP INDEX IF EXISTS idx_user_job_states_user;
    CREATE INDEX IF NOT EXISTS idx_user_job_states_user_status ON user_job_states(user_id, status);

    CREATE TABLE IF NOT EXISTS criteria (
        id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        type       TEXT NOT NULL,
        value      TEXT NOT NULL,
        is_active  INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, type, value)
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at  TIMESTAMP,
        jobs_found   INTEGER DEFAULT 0,
        jobs_scored  INTEGER DEFAULT 0,
        status       TEXT DEFAULT 'running'
    );

    CREATE INDEX IF NOT EXISTS idx_sessions_user_status_started ON sessions(user_id, status, started_at);

    CREATE TABLE IF NOT EXISTS cv_profiles (
        id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        filename   TEXT,
        raw_text   TEXT,
        parsed     TEXT,
        is_active  INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS preference_profiles (
        id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        content        TEXT NOT NULL,
        applied_count  INTEGER DEFAULT 0,
        rejected_count INTEGER DEFAULT 0,
        updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS usage_log (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at    TIMESTAMP DEFAULT (NOW() AT TIME ZONE 'utc'),
        model         TEXT NOT NULL,
        module        TEXT NOT NULL,
        input_tokens  INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd      REAL DEFAULT 0.0
    );

    -- Force UTC for databases created before this default existed, so it
    -- matches the UTC timestamps record_run_summary() compares it against.
    ALTER TABLE usage_log ALTER COLUMN created_at SET DEFAULT (NOW() AT TIME ZONE 'utc');

    CREATE INDEX IF NOT EXISTS idx_usage_log_user_created ON usage_log(user_id, created_at);

    CREATE TABLE IF NOT EXISTS cost_summaries (
        id               INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        run_label        TEXT NOT NULL,
        started_at       TIMESTAMP NOT NULL,
        finished_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        jobs_evaluated   INTEGER DEFAULT 0,
        total_cost_usd   REAL DEFAULT 0.0,
        cost_per_100_usd REAL,
        breakdown        TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_cost_summaries_user_started ON cost_summaries(user_id, started_at DESC);

    CREATE TABLE IF NOT EXISTS search_stats (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        session_id   INTEGER REFERENCES sessions(id),
        source       TEXT NOT NULL,
        search_query TEXT NOT NULL,
        location     TEXT NOT NULL,
        cards_found  INTEGER DEFAULT 0,
        new_found    INTEGER DEFAULT 0,
        searched_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_search_stats_query ON search_stats(source, search_query);
    CREATE INDEX IF NOT EXISTS idx_search_stats_user_source_searched ON search_stats(user_id, source, searched_at);

    CREATE TABLE IF NOT EXISTS excluded_search_queries (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        source       TEXT NOT NULL,
        search_query TEXT NOT NULL,
        reason       TEXT NOT NULL,
        excluded_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, source, search_query)
    );

    CREATE TABLE IF NOT EXISTS candidate_preferences (
        id                       INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id                  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        cv_profile_id            INTEGER REFERENCES cv_profiles(id),
        work_mode                TEXT,
        remote_countries         TEXT,
        hybrid_cities            TEXT,
        salary_min               INTEGER,
        salary_currency          TEXT,
        show_jobs_without_salary INTEGER DEFAULT 1,
        seniority_levels         TEXT,
        role_types               TEXT,
        preferred_company_types  TEXT,
        extra_tech               TEXT,
        avoided_tech             TEXT,
        languages                TEXT,
        open_notes               TEXT,
        is_active                INTEGER DEFAULT 1,
        created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS dismissed_score_items (
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        job_id      TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        item_type   TEXT NOT NULL,
        item_text   TEXT NOT NULL,
        reason      TEXT NOT NULL,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_dismissed_score_items_job ON dismissed_score_items(job_id);
    CREATE INDEX IF NOT EXISTS idx_dismissed_score_items_user_id ON dismissed_score_items(user_id, id DESC);
"""

_NEW_COLUMNS = [
    ("preference_profiles", "content_format", "TEXT DEFAULT 'text'"),
    ("preference_profiles", "dismissed_count", "INTEGER DEFAULT 0"),
    ("users", "session_epoch", "INTEGER DEFAULT 0"),
    # Set only when a collector stage actually finishes, distinct from finished_at
    # (every session gets that regardless of run type).
    ("sessions", "collected_at", "TIMESTAMP"),
    # The posting's own publication date, distinct from created_at (scrape time).
    # NULL for postings collected before this existed or for sources that don't expose it.
    ("job_postings", "posted_at", "TIMESTAMP"),
    # Structured fields a source's own API provides natively, layered on top of
    # structured_data's LLM extraction (source-native beats LLM guess).
    ("job_postings", "source_structured_data", "JSONB"),
]

# Columns that started as TEXT holding json.dumps() output and are converted to
# JSONB here for write-time validation. A fresh install already gets JSONB from
# _SCHEMA/_NEW_COLUMNS above, so this only matters for older databases. Guarded
# by an information_schema check because re-running the ALTER once the column
# is already jsonb would fail: NULLIF(jsonb_col, '') can't compare against the
# text literal ''.
_JSONB_COLUMNS = [
    ("job_postings", "structured_data"),
    ("job_postings", "source_structured_data"),
    ("user_job_states", "score_breakdown"),
]

# Removed from _SCHEMA above (a fresh install never creates them), but could
# still exist on an older database. These were collected but never read by
# anything downstream.
_DROPPED_COLUMNS = [
    ("candidate_preferences", "salary_max"),
    ("candidate_preferences", "excluded_company_types"),
    ("candidate_preferences", "preferred_industries"),
    ("candidate_preferences", "excluded_industries"),
]

# Mirrors the value sets already enforced app-side (Pydantic Literal in
# models.py, criteria_repo.py's VALID_TYPES) as a DB-level backstop for raw SQL
# writes that skip those models entirely.
_CHECK_CONSTRAINTS = [
    (
        "user_job_states", "user_job_states_status_check",
        "CHECK (status IN ('new', 'reviewed', 'applied', 'rejected', 'auto_rejected'))",
    ),
    (
        # 'failed' is legacy: no current code path writes it, but real rows on
        # the live database predate the current 'error'/'done_with_errors'
        # vocabulary and still carry it.
        "sessions", "sessions_status_check",
        "CHECK (status IN ('running', 'done', 'cancelled', 'error', 'done_with_errors', 'failed'))",
    ),
    (
        "criteria", "criteria_type_check",
        "CHECK (type IN ('title', 'location', 'required', 'preferred', 'rejected', 'search_query'))",
    ),
    (
        "dismissed_score_items", "dismissed_score_items_item_type_check",
        "CHECK (item_type IN ('pro', 'con'))",
    ),
]


# Arbitrary lock id, distinct from sessions_repo.py's per-user advisory lock.
# uvicorn's multiple worker processes each call init_db() on startup; without
# this, two workers running CREATE INDEX IF NOT EXISTS concurrently can still
# hit a duplicate-key error, since the check and the create aren't atomic
# across separate sessions.
_MIGRATION_LOCK_ID = 913377


def init_db(conn) -> None:
    cur = conn.cursor()
    cur.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
    try:
        cur.execute(_SCHEMA)
        conn.commit()

        for table, column, type_sql in _NEW_COLUMNS:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_sql}")
            conn.commit()

        for table, column in _DROPPED_COLUMNS:
            cur.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
            conn.commit()

        for table, column in _JSONB_COLUMNS:
            cur.execute(
                "SELECT data_type FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
                (table, column),
            )
            row = cur.fetchone()
            if row and row[0] != "jsonb":
                cur.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE JSONB USING NULLIF({column}, '')::jsonb")
                conn.commit()

        for table, name, check_sql in _CHECK_CONSTRAINTS:
            # DROP + ADD instead of an ADD-and-swallow-duplicate_object DO block:
            # that pattern is a no-op once the constraint already exists under
            # this name, even if check_sql has since changed, so a widened
            # value set would silently never reach the database. This always
            # ends up matching the current definition here exactly.
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
            cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} {check_sql}")
            conn.commit()
    finally:
        # A failed step above leaves the transaction aborted; roll back before
        # the unlock so that failure doesn't also mask itself by making the
        # unlock/commit here raise InFailedSqlTransaction instead, and so the
        # lock always gets released for the next worker's attempt to retry.
        conn.rollback()
        cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))
        conn.commit()
