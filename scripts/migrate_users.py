"""One-off migration: split the pre-multi-tenant `jobs` table into the shared
`job_postings` table + per-user `user_job_states`, add a `users` table, and
backfill `user_id` onto every other existing table, assigning everything to a
single bootstrap user (today's sole real user). Run once, from the local
machine, against the real `jobagent` Postgres over the WireGuard tunnel:

    POSTGRES_PASSWORD=... python scripts/migrate_users.py

Idempotent-ish: uses ON CONFLICT DO NOTHING / IF NOT EXISTS everywhere, and
checks for an existing bootstrap user before creating one, so a re-run after a
partial failure picks up roughly where it left off. It is NOT safe to run
against a database that's already been migrated by a *different* run of this
script (e.g. two different bootstrap usernames) — take a pg_dump backup before
running, as documented in the migration plan, and don't run this twice with
different assumptions.

The bootstrap user's password_hash is a placeholder — there's no registration
flow yet (that's Phase B). Set a real password for this account once
login/registration exists, before relying on it to authenticate.
"""
import os
import sys

import psycopg2
import psycopg2.extras

from config import POSTGRES

BOOTSTRAP_USERNAME = "tobiasz"

# Tables that get a plain `user_id` column added and backfilled to the
# bootstrap user. job_embeddings is deliberately excluded — it stays shared,
# only its job_id FK gets re-pointed at job_postings (see _repoint_job_fk).
TABLES_WITH_USER_ID = [
    "criteria", "sessions", "cv_profiles", "preference_profiles", "usage_log",
    "cost_summaries", "excluded_search_queries", "candidate_preferences",
    "dismissed_score_items", "search_stats",
]

# Tables whose job_id FK currently points at `jobs` and must be re-pointed at
# `job_postings` once it's populated.
TABLES_WITH_JOB_FK = ["job_embeddings", "dismissed_score_items"]


def _conn():
    password = os.environ.get("POSTGRES_PASSWORD") or POSTGRES["password"]
    if not password:
        sys.exit("Set POSTGRES_PASSWORD in the environment before running this script.")
    return psycopg2.connect(
        host=POSTGRES["host"], port=POSTGRES["port"], dbname=POSTGRES["dbname"],
        user=POSTGRES["user"], password=password,
    )


def _ensure_bootstrap_user(cur) -> int:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            username      TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin      INTEGER DEFAULT 0,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("SELECT id FROM users WHERE username = %s", (BOOTSTRAP_USERNAME,))
    row = cur.fetchone()
    if row:
        print(f"Bootstrap user already exists: id={row['id']}")
        return row["id"]
    cur.execute(
        "INSERT INTO users (username, password_hash, is_admin) VALUES (%s, %s, 1) RETURNING id",
        (BOOTSTRAP_USERNAME, "UNSET-until-phase-b-sets-a-real-password"),
    )
    user_id = cur.fetchone()["id"]
    print(f"Created bootstrap user: id={user_id}, username={BOOTSTRAP_USERNAME!r}")
    return user_id


def _create_job_postings_and_states(cur) -> None:
    cur.execute("""
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
        )
    """)
    cur.execute("""
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
        )
    """)


def _migrate_jobs(cur, user_id: int) -> int:
    cur.execute("SELECT * FROM jobs")
    jobs = cur.fetchall()
    for j in jobs:
        cur.execute("""
            INSERT INTO job_postings
                (id, title, company, location, url, description, source, source_id,
                 search_query, structured_data, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO NOTHING
        """, (j["id"], j["title"], j["company"], j["location"], j["url"], j["description"],
              j["source"], j["source_id"], j["search_query"], j["structured_data"],
              j["created_at"], j["updated_at"]))
        cur.execute("""
            INSERT INTO user_job_states
                (user_id, job_id, status, score, score_reason, score_breakdown,
                 rejection_reason, embedding_score, rerank_score, listwise_rank,
                 rank_reason, debate_flag, debate_note, would_apply, would_apply_reason,
                 created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (user_id, job_id) DO NOTHING
        """, (user_id, j["id"], j["status"], j["score"], j["score_reason"], j["score_breakdown"],
              j["rejection_reason"], j["embedding_score"], j["rerank_score"], j["listwise_rank"],
              j["rank_reason"], j["debate_flag"], j["debate_note"], j["would_apply"],
              j["would_apply_reason"], j["created_at"], j["updated_at"]))
    return len(jobs)


def _backfill_user_id(cur, table: str, user_id: int) -> None:
    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id INTEGER")
    cur.execute(f"UPDATE {table} SET user_id = %s WHERE user_id IS NULL", (user_id,))
    cur.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL")
    cur.execute(f"""
        SELECT 1 FROM pg_constraint
        WHERE conrelid = %s::regclass AND confrelid = 'users'::regclass
    """, (table,))
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_user_id "
                    f"FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE")


def _rescope_unique_constraints(cur) -> None:
    """criteria and excluded_search_queries had single-tenant UNIQUE constraints
    (type,value) / (source,search_query) that would incorrectly stop two
    different users from ever having the same criteria/excluded query. Swap
    them for user_id-scoped equivalents now that user_id exists on both."""
    swaps = [
        ("criteria", "criteria_type_value_key", "(user_id, type, value)"),
        ("excluded_search_queries", "excluded_search_queries_source_search_query_key",
         "(user_id, source, search_query)"),
    ]
    for table, old_name, new_cols in swaps:
        cur.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (old_name,))
        if cur.fetchone():
            cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {old_name}")
        cur.execute(f"""
            SELECT 1 FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype = 'u'
              AND pg_get_constraintdef(oid) = 'UNIQUE {new_cols}'
        """, (table,))
        if not cur.fetchone():
            cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT uq_{table}_scoped UNIQUE {new_cols}")


def _repoint_job_fk(cur, table: str) -> None:
    """Drop this table's FK on job_id -> jobs(id) and re-add it pointing at
    job_postings(id) instead. job_postings must already contain every id the
    old `jobs` table did (see _migrate_jobs) for this to succeed."""
    cur.execute("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = %s::regclass AND confrelid = 'jobs'::regclass
    """, (table,))
    row = cur.fetchone()
    if row:
        cur.execute(f"ALTER TABLE {table} DROP CONSTRAINT {row['conname']}")
    cur.execute(f"""
        SELECT 1 FROM pg_constraint
        WHERE conrelid = %s::regclass AND confrelid = 'job_postings'::regclass
    """, (table,))
    if not cur.fetchone():
        cur.execute(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_job_postings "
                    f"FOREIGN KEY (job_id) REFERENCES job_postings(id) ON DELETE CASCADE")


def main():
    conn = _conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    print(f"Target: {POSTGRES['host']}:{POSTGRES['port']}/{POSTGRES['dbname']}\n")

    user_id = _ensure_bootstrap_user(cur)
    conn.commit()

    _create_job_postings_and_states(cur)
    conn.commit()

    n_jobs = _migrate_jobs(cur, user_id)
    conn.commit()
    print(f"Migrated {n_jobs} row(s) from jobs -> job_postings + user_job_states")

    for table in TABLES_WITH_USER_ID:
        _backfill_user_id(cur, table, user_id)
        conn.commit()
        print(f"  {table:26s} user_id backfilled")

    for table in TABLES_WITH_JOB_FK:
        _repoint_job_fk(cur, table)
        conn.commit()
        print(f"  {table:26s} job_id FK re-pointed to job_postings")

    _rescope_unique_constraints(cur)
    conn.commit()
    print("  criteria / excluded_search_queries unique constraints rescoped to (user_id, ...)")

    print("\nVerifying row counts (old jobs vs new tables)...")
    cur.execute("SELECT COUNT(*) AS n FROM jobs")
    old_n = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM job_postings")
    postings_n = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) AS n FROM user_job_states WHERE user_id = %s", (user_id,))
    states_n = cur.fetchone()["n"]
    print(f"  jobs (old)        = {old_n}")
    print(f"  job_postings      = {postings_n}")
    print(f"  user_job_states   = {states_n} (for bootstrap user)")
    if not (old_n == postings_n == states_n):
        sys.exit(f"\nMISMATCH — not renaming old `jobs` table. Investigate before re-running.")

    print("\nSpot-checking a JSON column (score_breakdown) survived intact...")
    cur.execute("SELECT id, score_breakdown FROM jobs WHERE score_breakdown IS NOT NULL LIMIT 1")
    sample = cur.fetchone()
    if sample:
        cur.execute(
            "SELECT score_breakdown FROM user_job_states WHERE user_id = %s AND job_id = %s",
            (user_id, sample["id"]),
        )
        migrated = cur.fetchone()["score_breakdown"]
        if migrated != sample["score_breakdown"]:
            sys.exit(f"MISMATCH in score_breakdown for job {sample['id']} — not renaming old `jobs` table.")
        print(f"  OK — job {sample['id']} score_breakdown matches.")

    cur.execute("ALTER TABLE jobs RENAME TO jobs_deprecated_backup")
    conn.commit()
    print("\nAll checks passed. Renamed old `jobs` table to `jobs_deprecated_backup` (not dropped).")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
