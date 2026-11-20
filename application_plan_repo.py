from db import dict_cursor


def create_plan(conn, user_id: int, job_id: str | None) -> int:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO application_plans (user_id, job_id, status)
           VALUES (%s, %s, 'draft')
           RETURNING id""",
        (user_id, job_id),
    )
    return cur.fetchone()[0]


def upsert_field(
    conn,
    user_id: int,
    plan_id: int,
    field_name: str,
    value: str,
    *,
    fact_ids: list[int] = (),
    confidence: float | None = None,
    is_negotiable_or_irreversible: bool = False,
) -> int:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM application_plans WHERE id = %s AND user_id = %s",
        (plan_id, user_id),
    )
    if cur.fetchone() is None:
        raise ValueError(f"Plan {plan_id} not found or not owned by user {user_id}")

    if fact_ids:
        unique_fact_ids = set(fact_ids)
        cur.execute(
            "SELECT id FROM candidate_facts WHERE id = ANY(%s) AND user_id = %s",
            (list(unique_fact_ids), user_id),
        )
        owned_fact_ids = {row[0] for row in cur.fetchall()}
        if owned_fact_ids != unique_fact_ids:
            raise ValueError(
                f"fact_ids {sorted(unique_fact_ids - owned_fact_ids)} not found or not owned by user {user_id}"
            )

    is_grounded = 1 if bool(fact_ids) else 0
    neg_irr = 1 if is_negotiable_or_irreversible else 0

    cur.execute(
        """INSERT INTO application_plan_fields (
               plan_id, field_name, value, is_grounded, confidence, is_negotiable_or_irreversible
           )
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (plan_id, field_name) DO UPDATE SET
               value = EXCLUDED.value,
               is_grounded = EXCLUDED.is_grounded,
               confidence = EXCLUDED.confidence,
               is_negotiable_or_irreversible = EXCLUDED.is_negotiable_or_irreversible
           RETURNING id""",
        (plan_id, field_name, value, is_grounded, confidence, neg_irr),
    )
    field_id = cur.fetchone()[0]

    cur.execute(
        "DELETE FROM application_plan_field_facts WHERE field_id = %s",
        (field_id,),
    )
    if fact_ids:
        cur.executemany(
            "INSERT INTO application_plan_field_facts (field_id, fact_id) VALUES (%s, %s)",
            [(field_id, fid) for fid in fact_ids],
        )

    return field_id


def get_plan(conn, user_id: int, plan_id: int) -> dict | None:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, job_id, status, created_at, updated_at
           FROM application_plans
           WHERE id = %s AND user_id = %s""",
        (plan_id, user_id),
    )
    plan_row = cur.fetchone()
    if not plan_row:
        return None

    plan = dict(plan_row)
    cur.execute(
        """SELECT id, field_name, value, is_grounded, confidence, is_negotiable_or_irreversible
           FROM application_plan_fields
           WHERE plan_id = %s
           ORDER BY id""",
        (plan_id,),
    )
    fields_rows = cur.fetchall()

    fields: list[dict] = []
    if fields_rows:
        field_ids = [r["id"] for r in fields_rows]
        cur.execute(
            """SELECT field_id, fact_id
               FROM application_plan_field_facts
               WHERE field_id = ANY(%s)
               ORDER BY field_id, fact_id""",
            (field_ids,),
        )
        facts_map: dict[int, list[int]] = {fid: [] for fid in field_ids}
        for r in cur.fetchall():
            facts_map[r["field_id"]].append(r["fact_id"])

        for r in fields_rows:
            f_dict = dict(r)
            f_dict["is_grounded"] = bool(f_dict["is_grounded"])
            f_dict["is_negotiable_or_irreversible"] = bool(f_dict["is_negotiable_or_irreversible"])
            f_dict["fact_ids"] = facts_map.get(r["id"], [])
            fields.append(f_dict)

    plan["fields"] = fields
    return plan


def list_plans_for_job(conn, user_id: int, job_id: str) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, job_id, status, created_at, updated_at
           FROM application_plans
           WHERE user_id = %s AND job_id = %s
           ORDER BY created_at DESC, id DESC""",
        (user_id, job_id),
    )
    return [dict(r) for r in cur.fetchall()]


def mark_ready(conn, user_id: int, plan_id: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        "UPDATE application_plans SET status = 'ready' WHERE id = %s AND user_id = %s AND status = 'draft'",
        (plan_id, user_id),
    )
    return cur.rowcount > 0


def supersede_plan(conn, user_id: int, plan_id: int) -> bool:
    cur = conn.cursor()
    cur.execute(
        "UPDATE application_plans SET status = 'superseded' WHERE id = %s AND user_id = %s",
        (plan_id, user_id),
    )
    return cur.rowcount > 0
