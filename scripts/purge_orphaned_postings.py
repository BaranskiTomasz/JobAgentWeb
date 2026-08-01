"""Delete job_postings rows with no remaining user_job_states.

job_postings/job_embeddings are shared across users, but nothing ever prunes
them: the dashboard's "Delete jobs" action only removes the calling user's
own user_job_states row (deliberately — the posting may still be referenced
by other users), so a posting orphaned by the last user to reference it just
sits there forever. Safe to delete: job_id is deterministic from the URL
(hashlib.md5 in jobs_repo._generate_id), so if the same URL is collected
again later it gets re-inserted fresh rather than colliding with anything
here, and dedup against a user's own history is keyed off user_job_states,
never off job_postings existing. Their job_embeddings row cascades with them
(FK ON DELETE CASCADE), so a re-collected job pays Voyage re-embedding cost
again — the reason this is a manual, confirm-first script rather than
anything scheduled.

Usage:
    POSTGRES_PASSWORD=... python scripts/purge_orphaned_postings.py
    POSTGRES_PASSWORD=... python scripts/purge_orphaned_postings.py --yes
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras

from config import POSTGRES

_ORPHAN_WHERE = "NOT EXISTS (SELECT 1 FROM user_job_states ujs WHERE ujs.job_id = jp.id)"


def _conn():
    password = os.environ.get("POSTGRES_PASSWORD") or POSTGRES["password"]
    if not password:
        sys.exit("Set POSTGRES_PASSWORD in the environment before running this script.")
    return psycopg2.connect(
        host=POSTGRES["host"], port=POSTGRES["port"], dbname=POSTGRES["dbname"],
        user=POSTGRES["user"], password=password,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete job_postings with no remaining user_job_states")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    conn = _conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    print(f"Target: {POSTGRES['host']}:{POSTGRES['port']}/{POSTGRES['dbname']}\n")

    cur.execute(f"SELECT COUNT(*) AS n FROM job_postings jp WHERE {_ORPHAN_WHERE}")
    orphaned = cur.fetchone()["n"]

    if not orphaned:
        print("No orphaned job_postings.")
        return 0

    print(f"{orphaned} job_posting(s) have no user_job_states referencing them "
          "(their job_embeddings row, if any, cascades with them).")

    if not args.yes:
        reply = input("Delete them? [y/N] ").strip().lower()
        if reply != "y":
            print("Aborted.")
            return 1

    cur.execute(f"DELETE FROM job_postings jp WHERE {_ORPHAN_WHERE}")
    deleted = cur.rowcount
    conn.commit()
    print(f"Deleted {deleted} orphaned job_posting(s).")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
