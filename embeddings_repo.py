import json

import numpy as np

from db import dict_cursor


def get_indexed_ids(conn, user_id: int) -> set[str]:
    """The embedding itself is shared (a property of the posting, not per-user) —
    but the RESULT here is scoped to postings this user has a user_job_states row
    for, i.e. has actually collected/seen. Without this, any account could hit
    /unindexed or /all-indexed and trigger (and pay Voyage for) embedding every
    posting in the system, including ones collected only by other users on an
    invite code they'd never otherwise see. A user who *has* seen a shared
    posting still benefits from an embedding another user paid for — see
    test_embeddings_shared_across_users."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT je.job_id FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id WHERE ujs.user_id = %s",
        (user_id,),
    )
    return {r["job_id"] for r in cur.fetchall()}


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


def score_by_similarity(conn, ideal: list[float], job_ids: list[str]) -> dict[str, float]:
    """Cosine similarity of `ideal` against each job_id's vector, computed here
    instead of shipping raw vectors over HTTP for the caller to score itself.
    A 1024-dim vector serializes to ~22 KB of JSON — at a couple thousand jobs
    that's tens of MB shipped (and re-shipped on every retry) just so the
    caller could immediately reduce each one to a single float; this way only
    the {job_id: score} result crosses the wire.

    Vectorized as one matrix op instead of a per-row Python loop — at the
    ranking pool's 2000-job cap this is a single BLAS call over a 2000x1024
    matrix rather than 2000 separate dot-product-in-a-generator passes."""
    if not job_ids or not ideal:
        return {}
    vectors = get_vectors(conn, job_ids)
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


def get_decision_vectors(conn, user_id: int) -> dict:
    """Embedding vectors for this user's _DECISION_VECTOR_LIMIT most recent applied
    / rejected jobs — the basis for the 'ideal job' centroid used in semantic
    ranking. Capped and most-recent-first, not the full history: an unbounded,
    unweighted centroid means a decision from a year ago counts exactly as much
    as one from yesterday, so the centroid can never adapt if the candidate's
    search intent genuinely shifts (backend → platform, IC → lead) — old
    decisions just keep diluting new ones forever instead of aging out."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'applied'
           ORDER BY ujs.updated_at DESC LIMIT %s""",
        (user_id, _DECISION_VECTOR_LIMIT),
    )
    applied = [json.loads(r["embedding"]) for r in cur.fetchall()]
    cur.execute(
        """SELECT je.embedding FROM job_embeddings je JOIN user_job_states ujs ON ujs.job_id = je.job_id
           WHERE ujs.user_id = %s AND ujs.status = 'rejected'
           ORDER BY ujs.updated_at DESC LIMIT %s""",
        (user_id, _DECISION_VECTOR_LIMIT),
    )
    rejected = [json.loads(r["embedding"]) for r in cur.fetchall()]
    return {"applied": applied, "rejected": rejected}
