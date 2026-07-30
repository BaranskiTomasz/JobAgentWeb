from db import dict_cursor


def get_by_username(conn, username: str) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_by_id(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def create(conn, username: str, password_hash: str) -> int:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
        (username, password_hash),
    )
    return cur.fetchone()[0]


def list_all(conn) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY created_at")
    return [dict(r) for r in cur.fetchall()]


def delete(conn, user_id: int) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
