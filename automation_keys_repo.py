import secrets
from datetime import datetime
from typing import TypedDict

from psycopg2.extensions import connection as PgConnection

from db import dict_cursor
from security import hash_automation_key


class AutomationKey(TypedDict):
    id: int
    user_id: int
    label: str
    can_access_catalog: bool


class AutomationKeyListing(TypedDict):
    id: int
    user_id: int
    username: str
    label: str
    can_access_catalog: bool
    created_at: datetime


def get_by_raw_key(conn: PgConnection, raw_key: str) -> AutomationKey | None:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, user_id, label, can_access_catalog
           FROM automation_keys WHERE key_hash = %s""",
        (hash_automation_key(raw_key),),
    )
    row = cur.fetchone()
    return AutomationKey(**dict(row)) if row else None


def create(
    conn: PgConnection,
    user_id: int,
    label: str,
    *,
    can_access_catalog: bool = False,
) -> tuple[int, str]:
    raw_key = secrets.token_urlsafe(32)
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO automation_keys (user_id, key_hash, label, can_access_catalog)
           VALUES (%s, %s, %s, %s) RETURNING id""",
        (user_id, hash_automation_key(raw_key), label, can_access_catalog),
    )
    return cur.fetchone()[0], raw_key


def list_all(conn: PgConnection) -> list[AutomationKeyListing]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT ak.id, ak.user_id, u.username, ak.label,
                  ak.can_access_catalog, ak.created_at
           FROM automation_keys ak
           JOIN users u ON u.id = ak.user_id
           ORDER BY ak.created_at, ak.id"""
    )
    return [AutomationKeyListing(**dict(row)) for row in cur.fetchall()]


def delete(conn: PgConnection, key_id: int) -> bool:
    cur = conn.cursor()
    cur.execute("DELETE FROM automation_keys WHERE id = %s", (key_id,))
    return cur.rowcount > 0
