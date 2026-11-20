import uuid

from apply_executor import validate_transition
from db import dict_cursor


def create_execution(
    conn,
    user_id: int,
    plan_id: int,
    *,
    autonomy_decision_id: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM application_plans WHERE id = %s AND user_id = %s",
        (plan_id, user_id),
    )
    if cur.fetchone() is None:
        raise ValueError(f"Plan {plan_id} not found or not owned by user {user_id}")

    key = idempotency_key or f"plan:{plan_id}:{uuid.uuid4().hex}"
    cur = dict_cursor(conn)
    cur.execute(
        """INSERT INTO application_executions (
               user_id, plan_id, autonomy_decision_id, idempotency_key
           )
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING *""",
        (user_id, plan_id, autonomy_decision_id, key),
    )
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "SELECT * FROM application_executions WHERE idempotency_key = %s",
            (key,),
        )
        row = cur.fetchone()
    return dict(row)


def get_execution(conn, user_id: int, execution_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM application_executions WHERE id = %s AND user_id = %s",
        (execution_id, user_id),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def list_executions_for_plan(conn, user_id: int, plan_id: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT * FROM application_executions
           WHERE user_id = %s AND plan_id = %s
           ORDER BY created_at DESC, id DESC""",
        (user_id, plan_id),
    )
    return [dict(row) for row in cur.fetchall()]


def update_status(
    conn,
    user_id: int,
    execution_id: int,
    new_status: str,
    *,
    last_error: str | None = None,
    external_application_id: str | None = None,
) -> dict:
    current = get_execution(conn, user_id, execution_id)
    if current is None:
        raise ValueError(
            f"Execution {execution_id} not found or not owned by user {user_id}"
        )

    validate_transition(current["status"], new_status)

    assignments = [
        "status = %s",
        "attempt_count = attempt_count + %s",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params: list[object] = [new_status, 1 if new_status == "in_progress" else 0]
    if last_error is not None:
        assignments.append("last_error = %s")
        params.append(last_error)
    if external_application_id is not None:
        assignments.append("external_application_id = %s")
        params.append(external_application_id)
    params.extend([execution_id, user_id])

    cur = dict_cursor(conn)
    cur.execute(
        f"""UPDATE application_executions
            SET {', '.join(assignments)}
            WHERE id = %s AND user_id = %s
            RETURNING *""",
        params,
    )
    return dict(cur.fetchone())


def get_queued_executions(conn, *, limit: int = 50) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT * FROM application_executions
           WHERE status = 'queued'
           ORDER BY created_at ASC, id ASC
           LIMIT %s""",
        (limit,),
    )
    return [dict(row) for row in cur.fetchall()]


def count_executions_today(conn, user_id: int) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM application_executions WHERE user_id = %s AND created_at::date = CURRENT_DATE",
        (user_id,),
    )
    return cur.fetchone()[0]
