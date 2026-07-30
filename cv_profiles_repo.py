import json

from db import dict_cursor


def _deserialize(row) -> dict:
    d = dict(row)
    d["parsed"] = json.loads(d["parsed"]) if d["parsed"] else {}
    return d


def insert(conn, user_id: int, filename: str, raw_text: str, parsed: dict) -> int:
    """Insert a new CV profile, making it the active one for this user."""
    cur = conn.cursor()
    cur.execute("UPDATE cv_profiles SET is_active = 0 WHERE user_id = %s", (user_id,))
    cur.execute(
        "INSERT INTO cv_profiles (user_id, filename, raw_text, parsed, is_active) VALUES (%s, %s, %s, %s, 1) RETURNING id",
        (user_id, filename, raw_text, json.dumps(parsed, ensure_ascii=False)),
    )
    return cur.fetchone()[0]


def get_active(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM cv_profiles WHERE user_id = %s AND is_active = 1 ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    return _deserialize(row) if row else None


def list_all(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM cv_profiles WHERE user_id = %s ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return [_deserialize(r) for r in cur.fetchall()]


def set_active(conn, user_id: int, profile_id: int) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE cv_profiles SET is_active = 0 WHERE user_id = %s", (user_id,))
    cur.execute(
        "UPDATE cv_profiles SET is_active = 1 WHERE user_id = %s AND id = %s",
        (user_id, profile_id),
    )
