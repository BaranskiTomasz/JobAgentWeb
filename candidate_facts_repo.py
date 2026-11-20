from db import dict_cursor

VALID_FACT_TYPES = {
    "work_experience",
    "education",
    "skill",
    "certification",
    "project",
    "language",
    "achievement",
    "other",
}

VALID_SOURCES = {
    "cv_upload",
    "questionnaire_free_text",
    "manual",
}


def _validate_fact_type_and_source(fact_type: str, source: str) -> None:
    if fact_type not in VALID_FACT_TYPES:
        raise ValueError(f"Invalid fact_type: {fact_type!r}. Must be one of {VALID_FACT_TYPES}")
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source: {source!r}. Must be one of {VALID_SOURCES}")


def get_all(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM candidate_facts WHERE user_id = %s ORDER BY fact_type, created_at",
        (user_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def get_active(conn, user_id: int, fact_type: str | None = None) -> list[dict]:
    cur = dict_cursor(conn)
    if fact_type is None:
        cur.execute(
            "SELECT * FROM candidate_facts WHERE user_id = %s AND is_active = 1 ORDER BY fact_type, created_at",
            (user_id,),
        )
    else:
        cur.execute(
            "SELECT * FROM candidate_facts WHERE user_id = %s AND is_active = 1 AND fact_type = %s ORDER BY fact_type, created_at",
            (user_id, fact_type),
        )
    return [dict(r) for r in cur.fetchall()]


def insert(
    conn,
    user_id: int,
    fact_type: str,
    value: str,
    *,
    source: str,
    source_quote: str | None = None,
    source_ref: int | None = None,
) -> int:
    _validate_fact_type_and_source(fact_type, source)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO candidate_facts (user_id, fact_type, value, source_quote, source, source_ref)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING id""",
        (user_id, fact_type, value, source_quote, source, source_ref),
    )
    return cur.fetchone()[0]


def bulk_insert(conn, user_id: int, facts: list[dict]) -> list[int]:
    for item in facts:
        _validate_fact_type_and_source(item["fact_type"], item["source"])

    ids: list[int] = []
    cur = conn.cursor()
    for item in facts:
        cur.execute(
            """INSERT INTO candidate_facts (user_id, fact_type, value, source_quote, source, source_ref)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                user_id,
                item["fact_type"],
                item["value"],
                item.get("source_quote"),
                item["source"],
                item.get("source_ref"),
            ),
        )
        ids.append(cur.fetchone()[0])
    return ids


def deactivate(conn, user_id: int, fact_id: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        "UPDATE candidate_facts SET is_active = 0 WHERE user_id = %s AND id = %s",
        (user_id, fact_id),
    )
    return cur.rowcount > 0


def deactivate_by_source(conn, user_id: int, source: str, source_ref: int | None) -> int:
    cur = conn.cursor()
    if source_ref is None:
        cur.execute(
            "UPDATE candidate_facts SET is_active = 0 WHERE user_id = %s AND source = %s AND source_ref IS NULL",
            (user_id, source),
        )
    else:
        cur.execute(
            "UPDATE candidate_facts SET is_active = 0 WHERE user_id = %s AND source = %s AND source_ref = %s",
            (user_id, source, source_ref),
        )
    return cur.rowcount


def delete(conn, user_id: int, fact_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("DELETE FROM candidate_facts WHERE user_id = %s AND id = %s", (user_id, fact_id))
    return cur.rowcount > 0
