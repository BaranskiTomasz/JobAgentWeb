import application_plan_repo
import ats.greenhouse_schema
import cv_profiles_repo
import jobs_repo


def build_plan_for_job(conn, user_id: int, job_id: str) -> dict:
    job = jobs_repo.get_by_id(conn, user_id, job_id)
    if job is None:
        raise ValueError("Job not found")

    if job["source"] != "greenhouse":
        raise ValueError(f"No ATS adapter for source {job['source']!r}")

    source_id = job.get("source_id")
    if not source_id or ":" not in source_id:
        raise ValueError("Job has no usable Greenhouse source_id")
    slug, gh_job_id = source_id.split(":", 1)

    schema = ats.greenhouse_schema.fetch_job_schema(slug, gh_job_id)

    cur = conn.cursor()
    cur.execute("SAVEPOINT build_application_plan")
    plan_id = application_plan_repo.create_plan(conn, user_id, job_id)

    if any(field.field_id == "resume_text" for field in schema):
        cv = cv_profiles_repo.get_active(conn, user_id)
        if cv is None:
            cur.execute("ROLLBACK TO SAVEPOINT build_application_plan")
            cur.execute("RELEASE SAVEPOINT build_application_plan")
            raise ValueError("No active CV profile to populate resume_text from")
        application_plan_repo.upsert_field(
            conn,
            user_id,
            plan_id,
            "resume_text",
            cv["raw_text"],
            fact_ids=[],
            confidence=None,
            is_negotiable_or_irreversible=False,
        )

    plan = application_plan_repo.get_plan(conn, user_id, plan_id)
    mapping = ats.greenhouse_schema.map_plan_to_schema(plan["fields"], schema)
    missing = ats.greenhouse_schema.missing_required_fields(mapping)
    cur.execute("RELEASE SAVEPOINT build_application_plan")

    return {
        "plan_id": plan_id,
        "missing_required_fields": missing,
        "field_count": len(schema),
        "filled_count": len(plan["fields"]),
    }
