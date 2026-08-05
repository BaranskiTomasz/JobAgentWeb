import threading

import db as db_module
from migrations import init_db


def test_concurrent_init_db_does_not_raise():
    # Regression: uvicorn runs multiple worker processes, each calling init_db()
    # on startup. Without serializing them, two workers running "CREATE INDEX IF
    # NOT EXISTS" concurrently can still hit a duplicate-key error on the
    # underlying catalog entry — the existence check and the create aren't
    # atomic across separate sessions. Observed in production: one worker
    # crashed on deploy (auto-restarted by uvicorn's supervisor, but avoidable).
    #
    # init_db() already ran once at test-server startup, so everything it
    # creates already exists by the time a normal call gets here — no race
    # window. Drop one of its indexes first so both threads below actually
    # have to create it, reproducing the real "first deploy" scenario.
    conn = db_module._get_pool().getconn()
    try:
        conn.cursor().execute("DROP INDEX IF EXISTS idx_sessions_user_status_started")
        conn.commit()
    finally:
        db_module._get_pool().putconn(conn)

    errors = []
    barrier = threading.Barrier(2)

    def _init():
        conn = db_module._get_pool().getconn()
        try:
            barrier.wait(timeout=5)  # maximize the chance both hit CREATE INDEX together
            init_db(conn)
        except Exception as e:  # pragma: no cover - only hit if the lock isn't working
            errors.append(e)
        finally:
            db_module._get_pool().putconn(conn)

    t1 = threading.Thread(target=_init)
    t2 = threading.Thread(target=_init)
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert errors == []


def test_check_constraints_reject_invalid_values():
    # Regression: status/type columns had no DB-level validation at all — a
    # typo'd value written via raw SQL (session status transitions,
    # auto_rejected writes) bypassed the Pydantic Literal checks entirely and
    # just silently vanished from every view filtering on the column.
    import uuid

    import psycopg2

    conn = db_module._get_pool().getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, 'x') RETURNING id",
            (f"check-constraint-test-{uuid.uuid4()}",),
        )
        user_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO job_postings (id, title, url) VALUES (%s, 'x', %s) RETURNING id",
            (str(uuid.uuid4()), f"https://example.com/{uuid.uuid4()}"),
        )
        job_id = cur.fetchone()[0]
        conn.commit()

        cases = [
            ("INSERT INTO user_job_states (user_id, job_id, status) VALUES (%s, %s, %s)", (user_id, job_id, "bogus")),
            ("INSERT INTO sessions (user_id, status) VALUES (%s, %s)", (user_id, "bogus")),
            ("INSERT INTO criteria (user_id, type, value) VALUES (%s, %s, 'x')", (user_id, "bogus")),
            (
                "INSERT INTO dismissed_score_items (user_id, job_id, item_type, item_text, reason) "
                "VALUES (%s, %s, %s, 'x', 'y')",
                (user_id, job_id, "bogus"),
            ),
        ]
        for sql, params in cases:
            try:
                cur.execute(sql, params)
                assert False, f"accepted an invalid value: {sql}"
            except psycopg2.errors.CheckViolation:
                pass
            finally:
                conn.rollback()
    finally:
        db_module._get_pool().putconn(conn)


def test_json_columns_are_jsonb_and_reject_malformed_json():
    # Regression: structured_data/source_structured_data/score_breakdown used to
    # be TEXT holding json.dumps() output, parsed independently (and separately
    # try/excepted) by every reader — a malformed write from any one writer
    # would silently sit there until some future json.loads() call broke on it.
    # JSONB validates at write time instead.
    import uuid

    import psycopg2

    conn = db_module._get_pool().getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE (table_name, column_name) IN "
            "(('job_postings', 'structured_data'), ('job_postings', 'source_structured_data'), "
            " ('user_job_states', 'score_breakdown')) AND data_type = 'jsonb'"
        )
        assert len(cur.fetchall()) == 3

        try:
            cur.execute(
                "INSERT INTO job_postings (id, title, url, structured_data) VALUES (%s, 'x', %s, %s)",
                (str(uuid.uuid4()), f"https://example.com/{uuid.uuid4()}", "not valid json{"),
            )
            assert False, "malformed JSON was accepted into a jsonb column"
        except psycopg2.errors.InvalidTextRepresentation:
            pass
        finally:
            conn.rollback()
    finally:
        db_module._get_pool().putconn(conn)


def test_dropped_columns_are_actually_gone():
    # Regression: salary_max/excluded_company_types/preferred_industries/
    # excluded_industries were collected/stored but never read by anything
    # downstream — removed from the app-level field whitelist first, then
    # (after confirming what real data existed) dropped from the schema
    # itself via _DROPPED_COLUMNS, not just left as orphaned dead columns.
    conn = db_module._get_pool().getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'candidate_preferences' AND column_name = ANY(%s)",
            (["salary_max", "excluded_company_types", "preferred_industries", "excluded_industries"],),
        )
        assert cur.fetchall() == []
    finally:
        db_module._get_pool().putconn(conn)
