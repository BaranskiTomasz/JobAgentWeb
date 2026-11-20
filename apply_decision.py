import application_plan_repo
import apply_execution_repo
import autonomy_repo
import jobs_repo
from autonomy_policy import autonomy_inputs_from_plan, evaluate_autonomy


def decide_and_queue(conn, user_id: int, plan_id: int) -> dict:
    plan = application_plan_repo.get_plan(conn, user_id, plan_id)
    if plan is None:
        raise ValueError("Plan not found")
    if not plan["fields"]:
        raise ValueError("Plan has no fields yet")

    job = (
        jobs_repo.get_by_id(conn, user_id, plan["job_id"])
        if plan["job_id"] is not None
        else None
    )
    match_confidence = (
        job["score"] / 10.0 if job and job.get("score") is not None else 0.0
    )
    employer_known = bool(job and job.get("company_applied_count", 0) > 0)
    source = job["source"] if job else "unknown"
    applications_sent_today = apply_execution_repo.count_executions_today(conn, user_id)
    inputs = autonomy_inputs_from_plan(
        plan["fields"],
        match_confidence=match_confidence,
        employer_known=employer_known,
        source=source,
        applications_sent_today=applications_sent_today,
    )

    settings_row = autonomy_repo.get_settings(conn, user_id)
    settings_dict = settings_row or {
        "max_daily_auto_sends": 0,
        "min_confidence_auto_send": 0.9,
        "allowed_auto_send_sources": [],
    }
    decision = evaluate_autonomy(inputs, settings_dict)
    decision_id = autonomy_repo.record_decision(
        conn, user_id, plan["job_id"], decision, inputs
    )
    execution = apply_execution_repo.create_execution(
        conn, user_id, plan_id, autonomy_decision_id=decision_id
    )
    apply_execution_repo.update_status(
        conn, user_id, execution["id"], "in_progress"
    )
    apply_execution_repo.update_status(
        conn,
        user_id,
        execution["id"],
        "pending_manual_action",
        last_error="No automated ATS submission exists yet; review this plan and apply manually.",
    )
    return {
        "decision_id": decision_id,
        "level": decision.level,
        "reasons": decision.reasons,
        "execution_id": execution["id"],
        "execution_status": "pending_manual_action",
    }
