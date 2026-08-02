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
