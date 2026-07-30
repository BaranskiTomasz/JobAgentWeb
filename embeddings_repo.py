import json

from db import dict_cursor


def get_indexed_ids(conn) -> set[str]:
    """Shared, not user-scoped — embeddings are a property of the posting."""
    cur = dict_cursor(conn)
    cur.execute("SELECT job_id FROM job_embeddings")
    return {r["job_id"] for r in cur.fetchall()}


def get_unindexed(conn) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT jp.id, jp.title, jp.company, jp.location, jp.description
        FROM job_postings jp
        LEFT JOIN job_embeddings je ON je.job_id = jp.id
        WHERE jp.description IS NOT NULL AND jp.description != '' AND je.job_id IS NULL
        ORDER BY jp.created_at DESC
    """)
    return [dict(r) for r in cur.fetchall()]


def get_all_indexed(conn) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT jp.id, jp.title, jp.company, jp.location, jp.description, jp.source
        FROM job_postings jp JOIN job_embeddings je ON je.job_id = jp.id
    """)
    return [dict(r) for r in cur.fetchall()]


def upsert_many(conn, items: list[dict]) -> int:
    cur = conn.cursor()
    for item in items:
        cur.execute(
            """INSERT INTO job_embeddings (job_id, embedding, model) VALUES (%s, %s, %s)
               ON CONFLICT (job_id) DO UPDATE SET embedding = excluded.embedding, model = excluded.model""",
            (item["job_id"], json.dumps(item["embedding"]), item["model"]),
        )
    return len(items)


def get_vectors(conn, job_ids: list[str]) -> dict[str, list[float]]:
    if not job_ids:
        return {}
    cur = dict_cursor(conn)
    placeholders = ",".join(["%s"] * len(job_ids))
    cur.execute(f"SELECT job_id, embedding FROM job_embeddings WHERE job_id IN ({placeholders})", job_ids)
    return {r["job_id"]: json.loads(r["embedding"]) for r in cur.fetchall()}


def get_decision_vectors(conn, user_id: int) -> dict:
    """Embedding vectors for jobs this user has applied to / rejected — the
    basis for the 'ideal job' centroid used in semantic ranking."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'applied'""",
        (user_id,),
    )
    applied = [json.loads(r["embedding"]) for r in cur.fetchall()]
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'rejected'""",
        (user_id,),
    )
    rejected = [json.loads(r["embedding"]) for r in cur.fetchall()]
    return {"applied": applied, "rejected": rejected}
