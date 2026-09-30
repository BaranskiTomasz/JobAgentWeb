import json

import numpy as np

from db import dict_cursor


def get_indexed_ids(conn, user_id: int) -> set[str]:
    # The embedding is shared across every user who's seen the posting, but the
    # result here is scoped to postings this user has actually collected.
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT je.job_id FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id WHERE ujs.user_id = %s",
        (user_id,),
    )
    return {r["job_id"] for r in cur.fetchall()}


def get_indexed_metadata(conn, user_id: int) -> dict[str, dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT je.job_id, je.model, je.text_hash FROM job_embeddings je
           JOIN user_job_states ujs ON ujs.job_id = je.job_id WHERE ujs.user_id = %s""",
        (user_id,),
    )
    return {r["job_id"]: {"model": r["model"], "text_hash": r["text_hash"]} for r in cur.fetchall()}


def get_unindexed(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT jp.id, jp.title, jp.company, jp.location, jp.description
        FROM job_postings jp
        JOIN user_job_states ujs ON ujs.job_id = jp.id
        LEFT JOIN job_embeddings je ON je.job_id = jp.id
        WHERE ujs.user_id = %s AND jp.description IS NOT NULL AND jp.description != '' AND je.job_id IS NULL
        ORDER BY jp.created_at DESC
    """, (user_id,))
    return [dict(r) for r in cur.fetchall()]


def get_all_indexed(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("""
        SELECT jp.id, jp.title, jp.company, jp.location, jp.description, jp.source
        FROM job_postings jp
        JOIN user_job_states ujs ON ujs.job_id = jp.id
        JOIN job_embeddings je ON je.job_id = jp.id
        WHERE ujs.user_id = %s
    """, (user_id,))
    return [dict(r) for r in cur.fetchall()]


def upsert_many(conn, items: list[dict]) -> int:
    cur = conn.cursor()
    for item in items:
        cur.execute(
            """INSERT INTO job_embeddings (job_id, embedding, model, text_hash) VALUES (%s, %s, %s, %s)
               ON CONFLICT (job_id) DO UPDATE SET embedding = excluded.embedding, model = excluded.model,
                                                    text_hash = excluded.text_hash""",
            (item["job_id"], json.dumps(item["embedding"]), item["model"], item.get("text_hash")),
        )
    return len(items)


def get_vectors(conn, user_id: int, job_ids: list[str]) -> dict[str, list[float]]:
    if not job_ids:
        return {}
    cur = dict_cursor(conn)
    placeholders = ",".join(["%s"] * len(job_ids))
    cur.execute(
        f"""SELECT je.job_id, je.embedding FROM job_embeddings je
            JOIN user_job_states ujs ON ujs.job_id = je.job_id
            WHERE ujs.user_id = %s AND je.job_id IN ({placeholders})""",
        (user_id, *job_ids),
    )
    return {r["job_id"]: json.loads(r["embedding"]) for r in cur.fetchall()}


def score_by_similarity(conn, user_id: int, ideal: list[float], job_ids: list[str]) -> dict[str, float]:
    # Computed here instead of shipping raw vectors over HTTP for the caller to
    # score itself; at a couple thousand jobs that's tens of MB of vectors for
    # a result the caller immediately reduces to one float each.
    if not job_ids or not ideal:
        return {}
    vectors = get_vectors(conn, user_id, job_ids)
    if not vectors:
        return {}

    ids = list(vectors.keys())
    matrix = np.array([vectors[jid] for jid in ids], dtype=np.float64)
    ideal_arr = np.array(ideal, dtype=np.float64)

    ideal_norm = np.linalg.norm(ideal_arr)
    row_norms = np.linalg.norm(matrix, axis=1)
    denom = row_norms * ideal_norm

    dots = matrix @ ideal_arr
    scores = np.divide(dots, denom, out=np.zeros_like(dots), where=denom != 0)
    return dict(zip(ids, scores.tolist()))


_DECISION_VECTOR_LIMIT = 50


def get_decision_vectors(conn, user_id: int, model: str | None = None) -> dict:
    # Capped and most-recent-first, not full history: an unbounded centroid
    # never lets a candidate's search intent (e.g. backend to platform) shift.
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'applied' AND (%s IS NULL OR je.model = %s)
           ORDER BY ujs.updated_at DESC LIMIT %s""",
        (user_id, model, model, _DECISION_VECTOR_LIMIT),
    )
    applied = [json.loads(r["embedding"]) for r in cur.fetchall()]
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'rejected' AND (%s IS NULL OR je.model = %s)
           ORDER BY ujs.updated_at DESC LIMIT %s""",
        (user_id, model, model, _DECISION_VECTOR_LIMIT),
    )
    rejected = [json.loads(r["embedding"]) for r in cur.fetchall()]
    return {"applied": applied, "rejected": rejected}
