from db import dict_cursor

VALID_TYPES = {"title", "location", "required", "preferred", "rejected", "search_query"}


def get_all(conn, user_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("SELECT * FROM criteria WHERE user_id = %s ORDER BY type, value", (user_id,))
    return [dict(r) for r in cur.fetchall()]


def get_active(conn, user_id: int, type_: str) -> list[str]:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT value FROM criteria WHERE user_id = %s AND type = %s AND is_active = 1",
        (user_id, type_),
    )
    return [r["value"] for r in cur.fetchall()]


def get_active_dict(conn, user_id: int) -> dict:
    return {
        "search_queries": get_active(conn, user_id, "search_query"),
        "titles":         get_active(conn, user_id, "title"),
        "locations":      get_active(conn, user_id, "location"),
        "required":       get_active(conn, user_id, "required"),
        "preferred":      get_active(conn, user_id, "preferred"),
        "rejected":       get_active(conn, user_id, "rejected"),
    }


def insert(conn, user_id: int, type_: str, value: str) -> None:
    if type_ not in VALID_TYPES:
        raise ValueError(f"Invalid criteria type: {type_!r}. Must be one of {VALID_TYPES}")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO criteria (user_id, type, value) VALUES (%s, %s, %s) ON CONFLICT (user_id, type, value) DO NOTHING",
        (user_id, type_, value.strip()),
    )


def toggle(conn, user_id: int, criteria_id: int, is_active: bool) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE criteria SET is_active = %s WHERE user_id = %s AND id = %s",
        (1 if is_active else 0, user_id, criteria_id),
    )


def delete(conn, user_id: int, criteria_id: int) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM criteria WHERE user_id = %s AND id = %s", (user_id, criteria_id))


def delete_by_type(conn, user_id: int, type_: str) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM criteria WHERE user_id = %s AND type = %s", (user_id, type_))
    return cur.rowcount
