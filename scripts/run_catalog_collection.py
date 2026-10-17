"""Run the public catalog collector once from the server environment."""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.catalog_runner import run_catalog_collection
from db import _get_pool
import migrations


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    conn = _get_pool().getconn()
    try:
        migrations.init_db(conn)
        result = run_catalog_collection(conn)
        logging.info("catalog run result: %s", result)
        return 0
    finally:
        _get_pool().putconn(conn)


if __name__ == "__main__":
    raise SystemExit(main())
