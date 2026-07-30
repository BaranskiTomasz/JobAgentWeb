import json

from db import dict_cursor


def get_latest(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM preference_profiles WHERE user_id = %s ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    result["signals"] = json.loads(result["content"]) if result.get("content_format") == "json" else []
    return result


def save(conn, user_id: int, signals: list[dict], applied_count: int, rejected_count: int, dismissed_count: int = 0) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO preference_profiles (user_id, content, content_format, applied_count, rejected_count, dismissed_count, updated_at)
           VALUES (%s, %s, 'json', %s, %s, %s, CURRENT_TIMESTAMP)""",
        (user_id, json.dumps(signals), applied_count, rejected_count, dismissed_count),
    )
