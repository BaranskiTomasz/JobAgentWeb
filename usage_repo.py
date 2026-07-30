import json

from db import dict_cursor


def log_usage(conn, user_id: int, model: str, module: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    """Cost is computed client-side (JobAgent knows the Anthropic/Voyage pricing
    table; this service doesn't call those APIs itself) and passed in already
    calculated — this just stores it."""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO usage_log (user_id, model, module, input_tokens, output_tokens, cost_usd) VALUES (%s,%s,%s,%s,%s,%s)",
        (user_id, model, module, input_tokens, output_tokens, cost_usd),
    )


def get_summary(conn, user_id: int) -> dict:
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS cost, COALESCE(SUM(input_tokens+output_tokens),0) AS tokens "
        "FROM usage_log WHERE user_id = %s AND created_at::date = CURRENT_DATE",
        (user_id,),
    )
    today = cur.fetchone()
    cur.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS cost, COALESCE(SUM(input_tokens+output_tokens),0) AS tokens "
        "FROM usage_log WHERE user_id = %s",
        (user_id,),
    )
    total = cur.fetchone()
    return {
        "today_cost_usd":   round(today["cost"], 4),
        "today_tokens":     today["tokens"],
        "total_cost_usd":   round(total["cost"], 4),
        "total_tokens":     total["tokens"],
        "cost_per_100_usd": get_cost_per_100(conn, user_id),
    }


def record_run_summary(conn, user_id: int, run_label: str, started_at: str) -> None:
    """Snapshot everything logged to usage_log since `started_at` (a pipeline run's
    start time) into a durable, per-run record. Deliberately never touches or
    depends on job_postings/user_job_states, so deleting jobs later can't corrupt
    historical cost figures."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT model, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
        "SUM(cost_usd) AS cost_usd FROM usage_log WHERE user_id = %s AND created_at >= %s GROUP BY model",
        (user_id, started_at),
    )
    rows = cur.fetchall()
    if not rows:
        return

    breakdown = {
        r["model"]: {
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cost_usd": round(r["cost_usd"], 6),
        }
        for r in rows
    }
    total_cost = sum(r["cost_usd"] for r in rows)

    cur.execute(
        "SELECT COUNT(*) AS n FROM usage_log WHERE user_id = %s AND created_at >= %s AND module = 'scorer'",
        (user_id, started_at),
    )
    jobs_evaluated = cur.fetchone()["n"]
    cost_per_100 = round(total_cost / jobs_evaluated * 100, 4) if jobs_evaluated else None

    cur.execute(
        "INSERT INTO cost_summaries (user_id, run_label, started_at, jobs_evaluated, total_cost_usd, cost_per_100_usd, breakdown) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (user_id, run_label, started_at, jobs_evaluated, round(total_cost, 6), cost_per_100, json.dumps(breakdown)),
    )


def get_history(conn, user_id: int) -> list[dict]:
    """Every recorded run summary for this user, most recent first — the raw
    per-run breakdown behind get_summary()'s aggregate numbers."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT * FROM cost_summaries WHERE user_id = %s ORDER BY started_at DESC",
        (user_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["breakdown"] = json.loads(r["breakdown"])
    return rows


def get_cost_per_100(conn, user_id: int) -> float | None:
    """Rolling average cost-per-100-jobs-scored across every recorded run for
    this user — never a function of how many jobs currently exist."""
    cur = dict_cursor(conn)
    cur.execute(
        "SELECT COALESCE(SUM(total_cost_usd),0) AS cost, COALESCE(SUM(jobs_evaluated),0) AS n "
        "FROM cost_summaries WHERE user_id = %s AND jobs_evaluated > 0",
        (user_id,),
    )
    row = cur.fetchone()
    return round(row["cost"] / row["n"] * 100, 4) if row["n"] else None
