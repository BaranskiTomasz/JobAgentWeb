"""Delete old rows from tables that otherwise grow forever with no cleanup path.

usage_log and search_stats are deliberately left out: both back an all-time
aggregate (cost_summaries, get_query_summary()) that pruning would silently
shrink.

Usage:
    POSTGRES_PASSWORD=... python scripts/prune_old_records.py
    POSTGRES_PASSWORD=... python scripts/prune_old_records.py --yes
"""
import argparse
import os
import sys

import psycopg2
import psycopg2.extras

from config import POSTGRES

_SESSIONS_MAX_AGE_DAYS = 90
_PREFERENCE_PROFILES_KEEP_PER_USER = 5

# Never 'running' (a stuck run must stay visible to has_active_run()) and
# never one with search_stats still attached (FK is ON DELETE RESTRICT, and
# search_stats is deliberately not pruned here, see module docstring).
_SESSIONS_WHERE = f"""
    status != 'running'
    AND finished_at < NOW() - INTERVAL '{_SESSIONS_MAX_AGE_DAYS} days'
    AND NOT EXISTS (SELECT 1 FROM search_stats ss WHERE ss.session_id = sessions.id)
"""


def _conn():
    password = os.environ.get("POSTGRES_PASSWORD") or POSTGRES["password"]
    if not password:
        sys.exit("Set POSTGRES_PASSWORD in the environment before running this script.")
    return psycopg2.connect(
        host=POSTGRES["host"], port=POSTGRES["port"], dbname=POSTGRES["dbname"],
        user=POSTGRES["user"], password=password,
    )


def _prune_sessions(cur, confirm_yes: bool) -> int:
    cur.execute(f"SELECT COUNT(*) AS n FROM sessions WHERE {_SESSIONS_WHERE}")
    n = cur.fetchone()["n"]
    if not n:
        print("sessions: nothing to prune.")
        return 0
    print(f"sessions: {n} finished session(s) older than {_SESSIONS_MAX_AGE_DAYS} days "
          "with no search_stats attached.")
    if not confirm_yes and input("  Delete them? [y/N] ").strip().lower() != "y":
        print("  Skipped.")
        return 0
    cur.execute(f"DELETE FROM sessions WHERE {_SESSIONS_WHERE}")
    return cur.rowcount


def _prune_preference_profiles(cur, confirm_yes: bool) -> int:
    # get_latest() only ever reads the single newest row per user, so keeping
    # a handful more is pure margin, not a functional requirement.
    cur.execute(
        """SELECT COUNT(*) AS n FROM preference_profiles pp
           WHERE (
               SELECT COUNT(*) FROM preference_profiles pp2
               WHERE pp2.user_id = pp.user_id AND pp2.id >= pp.id
           ) > %s""",
        (_PREFERENCE_PROFILES_KEEP_PER_USER,),
    )
    n = cur.fetchone()["n"]
    if not n:
        print("preference_profiles: nothing to prune.")
        return 0
    print(f"preference_profiles: {n} row(s) beyond the newest "
          f"{_PREFERENCE_PROFILES_KEEP_PER_USER} per user.")
    if not confirm_yes and input("  Delete them? [y/N] ").strip().lower() != "y":
        print("  Skipped.")
        return 0
    cur.execute(
        """DELETE FROM preference_profiles pp
           WHERE (
               SELECT COUNT(*) FROM preference_profiles pp2
               WHERE pp2.user_id = pp.user_id AND pp2.id >= pp.id
           ) > %s""",
        (_PREFERENCE_PROFILES_KEEP_PER_USER,),
    )
    return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune old rows from tables with no other cleanup path")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompts")
    args = parser.parse_args()

    conn = _conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    print(f"Target: {POSTGRES['host']}:{POSTGRES['port']}/{POSTGRES['dbname']}\n")

    deleted_sessions = _prune_sessions(cur, args.yes)
    conn.commit()
    deleted_profiles = _prune_preference_profiles(cur, args.yes)
    conn.commit()

    print(f"\nDeleted {deleted_sessions} session(s), {deleted_profiles} preference_profiles row(s).")

    cur.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
