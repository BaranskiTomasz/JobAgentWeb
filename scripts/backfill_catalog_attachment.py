"""Attach eligible public catalog jobs to active users once."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from catalog_repo import attach_catalog_for_all_users
from db import _get_pool


def main() -> int:
    conn = _get_pool().getconn()
    try:
        attached = attach_catalog_for_all_users(conn)
        conn.commit()
        print(json.dumps(attached, sort_keys=True))
    except Exception:
        conn.rollback()
        raise
    finally:
        _get_pool().putconn(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
