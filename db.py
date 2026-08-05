from typing import Iterator

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from config import POSTGRES

_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1, maxconn=10,
            host=POSTGRES["host"], port=POSTGRES["port"], dbname=POSTGRES["dbname"],
            user=POSTGRES["user"], password=POSTGRES["password"],
        )
    return _pool


def get_db() -> Iterator[psycopg2.extensions.connection]:
    # Roll back on error so a failed request doesn't leave a half-applied write
    # for whoever borrows this connection from the pool next.
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
