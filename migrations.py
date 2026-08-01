"""Idempotent schema, safe to run on every startup. job_postings/job_embeddings are
shared across users (objective facts about a posting); user_job_states and every
other table are per-user (judgments about a candidate against a posting)."""

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
        structured_data  TEXT,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

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
        score_breakdown     TEXT,
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
        id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        jobs_found  INTEGER DEFAULT 0,
        jobs_scored INTEGER DEFAULT 0,
        status      TEXT DEFAULT 'running'
    );

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
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        model         TEXT NOT NULL,
        module        TEXT NOT NULL,
        input_tokens  INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd      REAL DEFAULT 0.0
    );

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
        salary_max               INTEGER,
        salary_currency          TEXT,
        show_jobs_without_salary INTEGER DEFAULT 1,
        seniority_levels         TEXT,
        role_types               TEXT,
        preferred_company_types  TEXT,
        excluded_company_types   TEXT,
        preferred_industries     TEXT,
        excluded_industries      TEXT,
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
"""

_NEW_COLUMNS = [
    ("preference_profiles", "content_format", "TEXT DEFAULT 'text'"),
    ("preference_profiles", "dismissed_count", "INTEGER DEFAULT 0"),
    ("users", "session_epoch", "INTEGER DEFAULT 0"),
]


def init_db(conn) -> None:
    cur = conn.cursor()
    cur.execute(_SCHEMA)
    conn.commit()

    for table, column, type_sql in _NEW_COLUMNS:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {type_sql}")
        conn.commit()
