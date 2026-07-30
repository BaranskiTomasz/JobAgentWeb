import json

from db import dict_cursor

# List-valued fields, stored as JSON text — matches the convention already used by
# job_postings.structured_data and cv_profiles.parsed.
_JSON_FIELDS = {
    "work_mode", "remote_countries", "hybrid_cities", "seniority_levels", "role_types",
    "preferred_company_types", "excluded_company_types", "preferred_industries",
    "excluded_industries", "extra_tech", "avoided_tech", "languages",
}
_SCALAR_FIELDS = {
    "salary_min", "salary_max", "salary_currency", "show_jobs_without_salary", "open_notes",
}
_VALID_FIELDS = _JSON_FIELDS | _SCALAR_FIELDS


def _serialize(fields: dict) -> dict:
    out = {}
    for key, value in fields.items():
        if key not in _VALID_FIELDS:
            raise ValueError(f"Invalid candidate_preferences field: {key!r}. Must be one of {sorted(_VALID_FIELDS)}")
        out[key] = json.dumps(value, ensure_ascii=False) if key in _JSON_FIELDS and value is not None else value
    return out


def _deserialize(row) -> dict:
    d = dict(row)
    for key in _JSON_FIELDS:
        if d.get(key):
            d[key] = json.loads(d[key])
    return d


def insert(conn, user_id: int, cv_profile_id: int | None, fields: dict | None = None) -> int:
    """Create a new active preferences snapshot for this user, deactivating any
    previous one. `fields` may include any subset of the known columns — every
    question is optional, so an empty dict (or omitting it) creates a blank snapshot."""
    data = _serialize(fields or {})
    data["user_id"] = user_id
    data["cv_profile_id"] = cv_profile_id

    cur = conn.cursor()
    cur.execute("UPDATE candidate_preferences SET is_active = 0 WHERE user_id = %s", (user_id,))
    columns = list(data.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    column_list = ", ".join(columns)
    cur.execute(
        f"INSERT INTO candidate_preferences ({column_list}, is_active) VALUES ({placeholders}, 1) RETURNING id",
        list(data.values()),
    )
    return cur.fetchone()[0]


def get_active(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM candidate_preferences WHERE user_id = %s AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    return _deserialize(row) if row else None


def list_all(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM candidate_preferences WHERE user_id = %s ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return [_deserialize(r) for r in cur.fetchall()]


def set_active(conn, user_id: int, pref_id: int) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE candidate_preferences SET is_active = 0 WHERE user_id = %s", (user_id,))
    cur.execute(
        "UPDATE candidate_preferences SET is_active = 1 WHERE user_id = %s AND id = %s",
        (user_id, pref_id),
    )


def update(conn, user_id: int, pref_id: int, fields: dict) -> None:
    if not fields:
        return
    data = _serialize(fields)
    set_clause = ", ".join(f"{k} = %s" for k in data)
    cur = conn.cursor()
    cur.execute(
        f"UPDATE candidate_preferences SET {set_clause} WHERE user_id = %s AND id = %s",
        [*data.values(), user_id, pref_id],
    )


def delete(conn, user_id: int, pref_id: int) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM candidate_preferences WHERE user_id = %s AND id = %s", (user_id, pref_id))
