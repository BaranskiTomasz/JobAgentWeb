import json

from db import dict_cursor


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
        canonical_url    TEXT,
        identity_fingerprint TEXT,
        content_fingerprint TEXT,
        structured_data  JSONB,
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings(company);
    CREATE TABLE IF NOT EXISTS job_posting_aliases (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        job_id       TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        url          TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        source       TEXT,
        source_id    TEXT,
        metadata     JSONB,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(job_id, url, source)
    );

    CREATE INDEX IF NOT EXISTS idx_job_posting_aliases_job ON job_posting_aliases(job_id);
    CREATE INDEX IF NOT EXISTS idx_job_posting_aliases_canonical ON job_posting_aliases(canonical_url);

    CREATE TABLE IF NOT EXISTS job_catalog_metadata (
        job_id                  TEXT PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
        technologies            TEXT[] NOT NULL DEFAULT '{}',
        work_countries          TEXT[] NOT NULL DEFAULT '{}',
        eligibility_confidence  TEXT NOT NULL DEFAULT 'unknown',
        is_public               BOOLEAN NOT NULL DEFAULT FALSE,
        classifier_version      INTEGER NOT NULL DEFAULT 0,
        updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_job_catalog_public ON job_catalog_metadata(is_public);
    CREATE INDEX IF NOT EXISTS idx_job_catalog_technologies ON job_catalog_metadata USING GIN(technologies);
    CREATE INDEX IF NOT EXISTS idx_job_catalog_countries ON job_catalog_metadata USING GIN(work_countries);

    CREATE TABLE IF NOT EXISTS job_fact_extractions (
        job_id          TEXT PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
        schema_version  INTEGER NOT NULL,
        model           TEXT NOT NULL,
        content_hash    TEXT NOT NULL,
        facts           JSONB NOT NULL,
        provenance      JSONB NOT NULL DEFAULT '{}',
        role_family     TEXT,
        seniority_min   TEXT,
        seniority_max   TEXT,
        remote          BOOLEAN,
        timezone_requirement TEXT,
        working_language TEXT,
        company_type    TEXT,
        product_vs_outsourcing TEXT,
        extracted_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_job_fact_extractions_version ON job_fact_extractions(schema_version);
    CREATE INDEX IF NOT EXISTS idx_job_fact_extractions_facts ON job_fact_extractions USING GIN(facts);

    CREATE TABLE IF NOT EXISTS job_skills (
        job_id          TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        canonical_name  TEXT NOT NULL,
        original_name   TEXT NOT NULL,
        requirement     TEXT NOT NULL,
        importance      TEXT NOT NULL,
        min_years       REAL,
        confidence      REAL NOT NULL,
        evidence        TEXT,
        PRIMARY KEY (job_id, canonical_name, requirement)
    );

    CREATE INDEX IF NOT EXISTS idx_job_skills_filter ON job_skills(canonical_name, requirement, importance);

    CREATE TABLE IF NOT EXISTS job_compensation_bands (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        job_id          TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        amount_min      NUMERIC,
        amount_max      NUMERIC,
        currency        TEXT,
        period          TEXT,
        tax_basis       TEXT,
        compensation_type TEXT,
        contract_type   TEXT,
        country_code    TEXT,
        confidence      REAL NOT NULL,
        evidence        TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_job_compensation_filter ON job_compensation_bands(currency, period, contract_type);

    CREATE TABLE IF NOT EXISTS job_eligibility (
        job_id          TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        country_code    TEXT NOT NULL,
        eligible        BOOLEAN,
        confidence      REAL NOT NULL,
        engagement_modes TEXT[] NOT NULL DEFAULT '{}',
        evidence        TEXT,
        PRIMARY KEY (job_id, country_code)
    );

    CREATE INDEX IF NOT EXISTS idx_job_eligibility_filter ON job_eligibility(country_code, eligible, confidence);

    CREATE TABLE IF NOT EXISTS job_embeddings (
        job_id     TEXT PRIMARY KEY REFERENCES job_postings(id) ON DELETE CASCADE,
        embedding  TEXT,
        model      TEXT,
        text_hash  TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS user_job_states (
        id                  INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        job_id              TEXT NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
        status              TEXT DEFAULT 'new',
        score               REAL,
        score_fingerprint   TEXT,
        score_reason        TEXT,
        score_breakdown     JSONB,
        rejection_reason    TEXT,
        embedding_score     REAL,
        rerank_score        REAL,
        listwise_rank       INTEGER,
        rank_reason         TEXT,
        debate_flag         TEXT,
        debate_note         TEXT,
        ranking_fingerprint TEXT,
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
        upstream_found INTEGER,
        query_matched INTEGER,
        date_matched INTEGER,
        geo_matched INTEGER,
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
        work_country             TEXT,
        employer_countries       TEXT,
        remote_countries         TEXT,
        hybrid_cities            TEXT,
        salary_min               INTEGER,
        salary_currency          TEXT,
        show_jobs_without_salary INTEGER DEFAULT 1,
        seniority_levels         TEXT,
        required_seniority_levels TEXT,
        role_types               TEXT,
        preferred_company_types  TEXT,
        required_company_types   TEXT,
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
    ("search_stats", "upstream_found", "INTEGER"),
    ("search_stats", "query_matched", "INTEGER"),
    ("search_stats", "date_matched", "INTEGER"),
    ("search_stats", "geo_matched", "INTEGER"),
    ("user_job_states", "score_fingerprint", "TEXT"),
    ("user_job_states", "ranking_fingerprint", "TEXT"),
    ("candidate_preferences", "work_country", "TEXT"),
    ("candidate_preferences", "employer_countries", "TEXT"),
    ("candidate_preferences", "required_seniority_levels", "TEXT"),
    ("candidate_preferences", "required_company_types", "TEXT"),
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
    ("job_postings", "canonical_url", "TEXT"),
    ("job_postings", "identity_fingerprint", "TEXT"),
    ("job_embeddings", "text_hash", "TEXT"),
    ("job_catalog_metadata", "classifier_version", "INTEGER NOT NULL DEFAULT 0"),
    ("job_fact_extractions", "role_family", "TEXT"),
    ("job_fact_extractions", "seniority_min", "TEXT"),
    ("job_fact_extractions", "seniority_max", "TEXT"),
    ("job_fact_extractions", "remote", "BOOLEAN"),
    ("job_fact_extractions", "timezone_requirement", "TEXT"),
    ("job_fact_extractions", "working_language", "TEXT"),
    ("job_fact_extractions", "company_type", "TEXT"),
    ("job_fact_extractions", "product_vs_outsourcing", "TEXT"),
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

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_fact_role "
            "ON job_fact_extractions(role_family, seniority_min, seniority_max)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_job_fact_work "
            "ON job_fact_extractions(remote, working_language, company_type)"
        )
        conn.commit()

        from jobs_repo import canonicalize_url, content_fingerprint, identity_fingerprint

        backfill_cur = dict_cursor(conn)
        backfill_cur.execute(
            """SELECT id, title, company, location, url, description, source, source_id, search_query, source_structured_data
               FROM job_postings
               WHERE canonical_url IS NULL OR identity_fingerprint IS NULL OR content_fingerprint IS NULL"""
        )
        for row in backfill_cur.fetchall():
            job = dict(row)
            canonical = canonicalize_url(job["url"])
            identity = identity_fingerprint(job)
            content = content_fingerprint(job)
            cur.execute(
                "SELECT id FROM job_postings WHERE id != %s AND canonical_url = %s LIMIT 1",
                (job["id"], canonical),
            )
            safe_canonical = None if cur.fetchone() else canonical
            cur.execute(
                """UPDATE job_postings SET canonical_url = COALESCE(canonical_url, %s),
                       identity_fingerprint = COALESCE(identity_fingerprint, %s),
                       content_fingerprint = COALESCE(content_fingerprint, %s)
                   WHERE id = %s""",
                (safe_canonical, identity, content, job["id"]),
            )
            cur.execute(
                """INSERT INTO job_posting_aliases (job_id, url, canonical_url, source, source_id, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (job_id, url, source) DO NOTHING""",
                (
                    job["id"], job["url"], canonical, job.get("source"), job.get("source_id"),
                    json.dumps({"search_query": job.get("search_query"), "source_structured_data": job.get("source_structured_data")}, default=str),
                ),
            )
        conn.commit()

        cur.execute("ALTER TABLE job_posting_aliases DROP CONSTRAINT IF EXISTS job_posting_aliases_url_key")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_posting_aliases_identity ON job_posting_aliases(job_id, url, source)")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_job_postings_canonical_url ON job_postings(canonical_url) WHERE canonical_url IS NOT NULL")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_identity_fingerprint ON job_postings(identity_fingerprint) WHERE identity_fingerprint IS NOT NULL")
        cur.execute("DROP INDEX IF EXISTS idx_job_postings_content_fingerprint")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_job_postings_content_fingerprint_lookup ON job_postings(content_fingerprint) WHERE content_fingerprint IS NOT NULL")
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

        from catalog import backfill
        backfill(conn)
        conn.commit()
    finally:
        # A failed step above leaves the transaction aborted; roll back before
        # the unlock so that failure doesn't also mask itself by making the
        # unlock/commit here raise InFailedSqlTransaction instead, and so the
        # lock always gets released for the next worker's attempt to retry.
        conn.rollback()
        cur.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_ID,))
        conn.commit()
