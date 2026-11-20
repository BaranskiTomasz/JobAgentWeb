from dataclasses import asdict

from psycopg2.extras import Json

from autonomy_policy import AutonomyDecision, AutonomyInputs
from db import dict_cursor


def get_settings(conn, user_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute("SELECT * FROM automation_settings WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def upsert_settings(
    conn,
    user_id: int,
    *,
    max_daily_auto_sends=None,
    min_confidence_auto_send=None,
    allowed_auto_send_sources=None,
) -> dict:
    values_by_column = {
        "max_daily_auto_sends": max_daily_auto_sends,
        "min_confidence_auto_send": min_confidence_auto_send,
        "allowed_auto_send_sources": allowed_auto_send_sources,
    }
    supplied = {column: value for column, value in values_by_column.items() if value is not None}
    columns = ["user_id", *supplied]
    placeholders = ", ".join(["%s"] * len(columns))
    update_assignments = [f"{column} = EXCLUDED.{column}" for column in supplied]
    update_assignments.append("updated_at = CURRENT_TIMESTAMP")

    cur = dict_cursor(conn)
    cur.execute(
        f"""INSERT INTO automation_settings ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (user_id) DO UPDATE SET {', '.join(update_assignments)}
            RETURNING *""",
        (user_id, *supplied.values()),
    )
    return dict(cur.fetchone())


def record_decision(
    conn,
    user_id: int,
    job_id: str | None,
    decision: AutonomyDecision,
    inputs: AutonomyInputs,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO autonomy_decisions (user_id, job_id, level, reasons, inputs)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING id""",
        (user_id, job_id, decision.level, decision.reasons, Json(asdict(inputs))),
    )
    return cur.fetchone()[0]


def get_recent_decisions(conn, user_id: int, limit=50) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT * FROM autonomy_decisions
           WHERE user_id = %s
           ORDER BY decided_at DESC, id DESC
           LIMIT %s""",
        (user_id, limit),
    )
    return [dict(row) for row in cur.fetchall()]
