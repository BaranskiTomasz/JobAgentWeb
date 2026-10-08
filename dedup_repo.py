"""Cross-source job matching and transactional posting consolidation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db import dict_cursor
from jobs_repo import (
    _description_similarity,
    _locations_compatible,
    content_fingerprint,
    identity_fingerprint,
)
from source_identity import company_alias, source_identity, title_aliases

DEFAULT_WINDOW_DAYS = 21
AUTO_MERGE_CONFIDENCE = 0.95

_ATS_SOURCES = {
    "ashby", "bamboohr", "breezy", "greenhouse", "jobvite", "lever",
    "personio", "pinpointhq", "recruitee", "smartrecruiters", "teamtailor",
    "workable", "workday", "icims", "successfactors",
}
_LINKEDIN_SOURCES = {"linkedin", "linkedin.com", "linkedin_jobs"}


def _pair(left: str, right: str) -> tuple[str, str]:
    if left == right:
        raise ValueError("a posting cannot be matched with itself")
    return (left, right) if left < right else (right, left)


def _source_priority(source: str | None) -> int:
    value = (source or "").strip().lower()
    if value in _ATS_SOURCES or any(name in value for name in _ATS_SOURCES):
        return 3
    if value in _LINKEDIN_SOURCES or "linkedin" in value:
        return 1
    return 2


def _survivor(rows: list[dict]) -> dict:
    return max(
        rows,
        key=lambda row: (
            _source_priority(row.get("source")),
            bool(row.get("description")),
            len(row.get("description") or ""),
            bool(row.get("source_id")),
            -(row.get("created_at") or datetime.max).timestamp(),
            str(row.get("id")),
        ),
    )


def _match_score(left: dict, right: dict) -> tuple[str, float, dict] | None:
    left_source_identity = source_identity(left)
    right_source_identity = source_identity(right)
    if left_source_identity and left_source_identity == right_source_identity:
        return "source_requisition", 1.0, {
            "source_identity": left_source_identity,
            "left_source": left.get("source"),
            "right_source": right.get("source"),
        }
    if (left.get("source") or "").lower() == (right.get("source") or "").lower():
        return None
    if not _locations_compatible(left.get("location"), right.get("location")):
        return None

    left_identity = left.get("identity_fingerprint") or identity_fingerprint(left)
    right_identity = right.get("identity_fingerprint") or identity_fingerprint(right)
    alias_identity_equal = bool(
        company_alias(left.get("company"))
        and company_alias(left.get("company")) == company_alias(right.get("company"))
        and title_aliases(left.get("title")) & title_aliases(right.get("title"))
    )
    left_content = left.get("content_fingerprint") or content_fingerprint(left)
    right_content = right.get("content_fingerprint") or content_fingerprint(right)
    evidence: dict[str, Any] = {
        "identity_equal": bool(left_identity and left_identity == right_identity),
        "alias_identity_equal": alias_identity_equal,
        "locations_compatible": True,
        "left_source": left.get("source"),
        "right_source": right.get("source"),
        "left_source_id": left.get("source_id"),
        "right_source_id": right.get("source_id"),
        "left_title": left.get("title"),
        "right_title": right.get("title"),
        "left_company": left.get("company"),
        "right_company": right.get("company"),
        "left_location": left.get("location"),
        "right_location": right.get("location"),
    }
    if left_content and left_content == right_content:
        evidence["content_fingerprint_equal"] = True
        return "exact_content", 0.94, evidence
    if not alias_identity_equal and (not left_identity or left_identity != right_identity):
        return None

    similarity = _description_similarity(left.get("description"), right.get("description"))
    evidence["description_similarity"] = similarity
    if similarity >= 0.94:
        return "identity_description", 0.94, evidence
    if similarity >= 0.82:
        return "identity_description_candidate", 0.90, evidence
    return "identity_only", 0.60, evidence


def _candidate_rows(conn, job_id: str, window_days: int) -> list[dict]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, title, company, location, description, source, source_id, url,
                      canonical_url, identity_fingerprint, content_fingerprint,
                      created_at, posted_at
                 FROM job_postings
                WHERE id <> %s
                  AND COALESCE(posted_at, created_at) >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
                  AND EXISTS (
                        SELECT 1 FROM job_postings target
                         WHERE target.id = %s
                           AND COALESCE(target.posted_at, target.created_at) >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
                  )
                ORDER BY created_at DESC""",
        (job_id, window_days, job_id, window_days),
    )
    return [dict(row) for row in cur.fetchall()]


def find_candidates(conn, job_id: str, window_days: int = DEFAULT_WINDOW_DAYS) -> list[dict]:
    """Return scored cross-source candidates within the rolling 21-day window."""
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id, title, company, location, description, source, source_id, url,
                      canonical_url, identity_fingerprint, content_fingerprint,
                      created_at, posted_at
                 FROM job_postings WHERE id = %s""",
        (job_id,),
    )
    row = cur.fetchone()
    if not row:
        raise KeyError(f"unknown job posting: {job_id}")
    source = dict(row)
    result = []
    for candidate in _candidate_rows(conn, job_id, max(0, int(window_days))):
        scored = _match_score(source, candidate)
        if not scored:
            continue
        method, confidence, evidence = scored
        low, high = _pair(job_id, candidate["id"])
        result.append({
            "job_id": job_id,
            "candidate_job_id": candidate["id"],
            "job_id_low": low,
            "job_id_high": high,
            "match_method": method,
            "confidence": confidence,
            "evidence": evidence,
            "auto_merge": confidence >= AUTO_MERGE_CONFIDENCE,
            "candidate": candidate,
        })
    return result


def record_match(conn, match: dict) -> dict:
    """Upsert a match without overwriting a human or completed decision."""
    low, high = _pair(match["job_id_low"], match["job_id_high"])
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO job_dedup_matches
                   (job_id_low, job_id_high, match_method, confidence, evidence)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (job_id_low, job_id_high) DO UPDATE SET
               match_method = EXCLUDED.match_method,
               confidence = EXCLUDED.confidence,
               evidence = EXCLUDED.evidence,
               status = CASE WHEN job_dedup_matches.status IN
                                      ('rejected', 'merged', 'auto_merged')
                                  THEN job_dedup_matches.status ELSE 'candidate' END
           RETURNING id, status""",
        (low, high, match["match_method"], match["confidence"],
         json.dumps(match.get("evidence") or {}, ensure_ascii=False)),
    )
    row = cur.fetchone()
    return {"id": row[0], "status": row[1]}


def _merge_json(left: Any, right: Any) -> Any:
    if isinstance(left, dict) and isinstance(right, dict):
        return {
            key: _merge_json(left.get(key), right.get(key))
            for key in left.keys() | right.keys()
        }
    if isinstance(left, list) and isinstance(right, list):
        merged = list(left)
        seen = {json.dumps(item, sort_keys=True, default=str) for item in merged}
        for item in right:
            marker = json.dumps(item, sort_keys=True, default=str)
            if marker not in seen:
                merged.append(item)
                seen.add(marker)
        return merged
    return right if left in (None, "", [], {}) else left


def _state_rank(status: str | None) -> int:
    return {"new": 0, "reviewed": 1, "rejected": 2, "auto_rejected": 2, "applied": 3}.get(status or "new", 0)


def _merge_user_states(cur, survivor_id: str, loser_id: str) -> set[int]:
    cur.execute("SELECT * FROM user_job_states WHERE job_id IN (%s, %s) FOR UPDATE", (survivor_id, loser_id))
    rows = [dict(row) for row in cur.fetchall()]
    fields = (
        "score", "score_fingerprint", "score_reason", "score_breakdown", "rejection_reason",
        "embedding_score", "rerank_score", "listwise_rank", "rank_reason", "debate_flag",
        "debate_note", "ranking_fingerprint", "would_apply", "would_apply_reason",
    )
    by_user: dict[int, dict[str, dict]] = {}
    overlapping_users = set()
    for row in rows:
        by_user.setdefault(row["user_id"], {})[row["job_id"]] = row
    for user_id, pair in by_user.items():
        old = pair.get(loser_id)
        if not old:
            continue
        current = pair.get(survivor_id)
        if not current:
            cur.execute("UPDATE user_job_states SET job_id = %s WHERE id = %s", (survivor_id, old["id"]))
            continue
        overlapping_users.add(user_id)
        values = [survivor_id]
        assignments = ["job_id = %s"]
        primary, secondary = (
            (current, old) if current["updated_at"] >= old["updated_at"] else (old, current)
        )
        for field in fields:
            value = primary.get(field) if primary.get(field) is not None else secondary.get(field)
            assignments.append(f"{field} = %s")
            values.append(value)
        status = current["status"] if _state_rank(current["status"]) >= _state_rank(old["status"]) else old["status"]
        assignments.append("status = %s")
        values.append(status)
        assignments.append("created_at = LEAST(created_at, %s)")
        values.append(old["created_at"])
        assignments.append("updated_at = GREATEST(updated_at, %s)")
        values.append(old["updated_at"])
        values.extend([user_id, current["id"]])
        cur.execute(
            f"UPDATE user_job_states SET {', '.join(assignments)} WHERE user_id = %s AND id = %s",
            values,
        )
        cur.execute("DELETE FROM user_job_states WHERE id = %s", (old["id"],))
    return overlapping_users


def _merge_aliases(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("SELECT url, canonical_url, source, source_id, metadata FROM job_posting_aliases WHERE job_id = %s FOR UPDATE", (loser_id,))
    aliases = [dict(row) for row in cur.fetchall()]
    for alias in aliases:
        cur.execute(
            """SELECT id FROM job_posting_aliases
                WHERE job_id = %s AND url = %s AND source IS NOT DISTINCT FROM %s
                LIMIT 1 FOR UPDATE""",
            (survivor_id, alias["url"], alias["source"]),
        )
        existing = cur.fetchone()
        if existing:
            cur.execute(
                """UPDATE job_posting_aliases
                      SET source_id = COALESCE(source_id, %s),
                          metadata = COALESCE(metadata, '{}'::jsonb)
                                     || jsonb_strip_nulls(COALESCE(%s::jsonb, '{}'::jsonb))
                    WHERE id = %s""",
                (alias["source_id"],
                 json.dumps(alias["metadata"], ensure_ascii=False) if isinstance(alias["metadata"], (dict, list)) else alias["metadata"],
                 existing[0]),
            )
        else:
            cur.execute(
                """INSERT INTO job_posting_aliases
                         (job_id, url, canonical_url, source, source_id, metadata)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (survivor_id, alias["url"], alias["canonical_url"], alias["source"], alias["source_id"],
                 json.dumps(alias["metadata"], ensure_ascii=False) if isinstance(alias["metadata"], (dict, list)) else alias["metadata"]),
            )
    cur.execute("DELETE FROM job_posting_aliases WHERE job_id = %s", (loser_id,))


def _merge_catalog(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("SELECT * FROM job_catalog_metadata WHERE job_id IN (%s, %s) FOR UPDATE", (survivor_id, loser_id))
    rows = {row["job_id"]: dict(row) for row in cur.fetchall()}
    old, current = rows.get(loser_id), rows.get(survivor_id)
    if not old:
        return
    if not current:
        cur.execute("UPDATE job_catalog_metadata SET job_id = %s WHERE job_id = %s", (survivor_id, loser_id))
        return
    technologies = sorted(set((current.get("technologies") or []) + (old.get("technologies") or [])))
    role_families = sorted(set((current.get("role_families") or []) + (old.get("role_families") or [])))
    countries = sorted(set((current.get("work_countries") or []) + (old.get("work_countries") or [])))
    confidence_order = {"unknown": 0, "medium": 1, "high": 2}
    confidence = max(
        (current.get("eligibility_confidence") or "unknown", old.get("eligibility_confidence") or "unknown"),
        key=lambda value: confidence_order.get(value, 0),
    )
    public = bool(current.get("is_public")) or bool(old.get("is_public"))
    version = max(current.get("classifier_version") or 0, old.get("classifier_version") or 0)
    cur.execute(
        """UPDATE job_catalog_metadata SET technologies = %s, role_families = %s, work_countries = %s,
               eligibility_confidence = %s, is_public = %s, classifier_version = %s,
               updated_at = GREATEST(updated_at, %s) WHERE job_id = %s""",
        (technologies, role_families, countries, confidence, public, version, old["updated_at"], survivor_id),
    )
    cur.execute("DELETE FROM job_catalog_metadata WHERE job_id = %s", (loser_id,))


def _merge_facts(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("SELECT * FROM job_fact_extractions WHERE job_id IN (%s, %s) FOR UPDATE", (survivor_id, loser_id))
    rows = {row["job_id"]: dict(row) for row in cur.fetchall()}
    old, current = rows.get(loser_id), rows.get(survivor_id)
    if not old:
        return
    if not current:
        cur.execute("UPDATE job_fact_extractions SET job_id = %s WHERE job_id = %s", (survivor_id, loser_id))
        return
    scalar = ["schema_version", "model", "content_hash", "role_family", "seniority_min", "seniority_max", "remote", "timezone_requirement", "working_language", "company_type", "product_vs_outsourcing"]
    values = [_merge_json(current.get("facts"), old.get("facts")), _merge_json(current.get("provenance"), old.get("provenance"))]
    assignments = ["facts = %s", "provenance = %s"]
    for field in scalar:
        assignments.append(f"{field} = COALESCE({field}, %s)")
        values.append(current.get(field) if current.get(field) is not None else old.get(field))
    values.append(survivor_id)
    cur.execute(f"UPDATE job_fact_extractions SET {', '.join(assignments)} WHERE job_id = %s", [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in values])
    cur.execute("DELETE FROM job_fact_extractions WHERE job_id = %s", (loser_id,))


def _merge_embeddings(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("SELECT * FROM job_embeddings WHERE job_id IN (%s, %s) FOR UPDATE", (survivor_id, loser_id))
    rows = {row["job_id"]: dict(row) for row in cur.fetchall()}
    old, current = rows.get(loser_id), rows.get(survivor_id)
    if not old:
        return
    if not current:
        cur.execute("UPDATE job_embeddings SET job_id = %s WHERE job_id = %s", (survivor_id, loser_id))
    else:
        if (old.get("created_at") or datetime.min) > (current.get("created_at") or datetime.min):
            cur.execute(
                """UPDATE job_embeddings
                      SET embedding = %s, model = %s, text_hash = %s, created_at = %s
                    WHERE job_id = %s""",
                (old.get("embedding"), old.get("model"), old.get("text_hash"),
                 old.get("created_at"), survivor_id),
            )
        cur.execute("DELETE FROM job_embeddings WHERE job_id = %s", (loser_id,))


def _merge_compensation(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("UPDATE job_compensation_bands SET job_id = %s WHERE job_id = %s", (survivor_id, loser_id))


def _merge_skills(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("""INSERT INTO job_skills (job_id, canonical_name, original_name, requirement, importance, min_years, confidence, evidence)
                     SELECT %s, canonical_name, original_name, requirement, importance, min_years, confidence, evidence
                       FROM job_skills WHERE job_id = %s
                     ON CONFLICT (job_id, canonical_name, requirement) DO UPDATE SET
                       original_name = COALESCE(job_skills.original_name, EXCLUDED.original_name),
                       importance = COALESCE(job_skills.importance, EXCLUDED.importance),
                       min_years = COALESCE(job_skills.min_years, EXCLUDED.min_years),
                       confidence = GREATEST(job_skills.confidence, EXCLUDED.confidence),
                       evidence = COALESCE(job_skills.evidence, EXCLUDED.evidence)""", (survivor_id, loser_id))
    cur.execute("DELETE FROM job_skills WHERE job_id = %s", (loser_id,))


def _merge_eligibility(cur, survivor_id: str, loser_id: str) -> None:
    cur.execute("SELECT * FROM job_eligibility WHERE job_id = %s FOR UPDATE", (loser_id,))
    for old in [dict(row) for row in cur.fetchall()]:
        cur.execute("SELECT * FROM job_eligibility WHERE job_id = %s AND country_code = %s FOR UPDATE", (survivor_id, old["country_code"]))
        current = cur.fetchone()
        if not current:
            cur.execute("UPDATE job_eligibility SET job_id = %s WHERE job_id = %s AND country_code = %s", (survivor_id, loser_id, old["country_code"]))
            continue
        current = dict(current)
        modes = sorted(set((current.get("engagement_modes") or []) + (old.get("engagement_modes") or [])))
        eligible = current.get("eligible") if current.get("eligible") is not None else old.get("eligible")
        confidence = max(current.get("confidence") or 0, old.get("confidence") or 0)
        evidence = current.get("evidence") or old.get("evidence")
        cur.execute("UPDATE job_eligibility SET eligible = %s, confidence = %s, engagement_modes = %s, evidence = %s WHERE job_id = %s AND country_code = %s", (eligible, confidence, modes, evidence, survivor_id, old["country_code"]))
        cur.execute("DELETE FROM job_eligibility WHERE job_id = %s AND country_code = %s", (loser_id, old["country_code"]))


def merge_jobs(conn, left_job_id: str, right_job_id: str, *, survivor_job_id: str | None = None, match_id: int | None = None, match_method: str = "manual_merge", confidence: float = 1.0, evidence: dict | None = None) -> dict:
    low, high = _pair(left_job_id, right_job_id)
    cur = dict_cursor(conn)
    cur.execute("SELECT * FROM job_postings WHERE id IN (%s, %s) ORDER BY id FOR UPDATE", (low, high))
    rows = [dict(row) for row in cur.fetchall()]
    if len(rows) != 2:
        raise KeyError("both postings must exist before merging")
    chosen = survivor_job_id or _survivor(rows)["id"]
    if chosen not in {low, high}:
        raise ValueError("survivor must be one of the merged postings")
    loser = high if chosen == low else low
    winner = next(row for row in rows if row["id"] == chosen)
    old = next(row for row in rows if row["id"] == loser)

    merged_structured = _merge_json(winner.get("structured_data"), old.get("structured_data"))
    merged_source_data = _merge_json(winner.get("source_structured_data"), old.get("source_structured_data"))
    merged_job = {
        **winner,
        "company": winner.get("company") or old.get("company"),
        "location": winner.get("location") or old.get("location"),
        "description": winner.get("description") or old.get("description"),
    }
    merged_identity = identity_fingerprint(merged_job)
    merged_content = content_fingerprint(merged_job)
    cur.execute(
        """UPDATE job_postings SET company = COALESCE(company, %s), location = COALESCE(location, %s),
               description = CASE WHEN COALESCE(description, '') = '' THEN %s ELSE description END,
               source_id = COALESCE(source_id, %s), search_query = COALESCE(search_query, %s),
               posted_at = COALESCE(posted_at, %s), identity_fingerprint = %s,
               content_fingerprint = %s, structured_data = %s, source_structured_data = %s,
               updated_at = CURRENT_TIMESTAMP WHERE id = %s""",
        (old.get("company"), old.get("location"), old.get("description"), old.get("source_id"),
         old.get("search_query"), old.get("posted_at"), merged_identity, merged_content,
         json.dumps(merged_structured, ensure_ascii=False) if merged_structured is not None else None,
         json.dumps(merged_source_data, ensure_ascii=False) if merged_source_data is not None else None, chosen),
    )
    _merge_aliases(cur, chosen, loser)
    overlapping_users = _merge_user_states(cur, chosen, loser)
    _merge_catalog(cur, chosen, loser)
    _merge_facts(cur, chosen, loser)
    _merge_skills(cur, chosen, loser)
    _merge_eligibility(cur, chosen, loser)
    _merge_compensation(cur, chosen, loser)
    _merge_embeddings(cur, chosen, loser)
    cur.execute("UPDATE dismissed_score_items SET job_id = %s WHERE job_id = %s", (chosen, loser))

    cur.execute("DELETE FROM job_postings WHERE id = %s", (loser,))
    audit_evidence = evidence or {"survivor_preference": _source_priority(winner.get("source"))}
    cur.execute(
        """INSERT INTO job_dedup_matches
                   (job_id_low, job_id_high, match_method, confidence, evidence, status, survivor_job_id, resolved_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT (job_id_low, job_id_high) DO UPDATE SET
                   match_method = EXCLUDED.match_method, confidence = EXCLUDED.confidence,
                   evidence = EXCLUDED.evidence, status = EXCLUDED.status,
                   survivor_job_id = EXCLUDED.survivor_job_id, resolved_at = EXCLUDED.resolved_at""",
        (low, high, match_method, confidence, json.dumps(audit_evidence, ensure_ascii=False),
         "auto_merged" if confidence >= AUTO_MERGE_CONFIDENCE and match_method != "manual_merge" else "merged", chosen),
    )
    return {
        "survivor_job_id": chosen,
        "merged_job_id": loser,
        "match_id": match_id,
        "overlapping_user_ids": sorted(overlapping_users),
    }


def deduplicate_job(conn, job_id: str, *, window_days: int = DEFAULT_WINDOW_DAYS, auto_merge: bool = True) -> dict:
    survivor_id = job_id
    merges = []
    recorded = []
    while True:
        candidates = find_candidates(conn, survivor_id, window_days=window_days)
        automatic = sorted(
            (candidate for candidate in candidates if candidate["auto_merge"]),
            key=lambda candidate: candidate["confidence"],
            reverse=True,
        )
        selected = None
        if auto_merge:
            for candidate in automatic:
                match = record_match(conn, candidate)
                if match["status"] == "rejected":
                    recorded.append({"match_id": match["id"], **candidate})
                    continue
                selected = (candidate, match)
                break
        if selected:
            candidate, match = selected
            result = merge_jobs(
                conn, survivor_id, candidate["candidate_job_id"], match_id=match["id"],
                match_method=candidate["match_method"], confidence=candidate["confidence"],
                evidence=candidate["evidence"],
            )
            merges.append(result)
            survivor_id = result["survivor_job_id"]
            continue
        for candidate in candidates:
            match = record_match(conn, candidate)
            recorded.append({"match_id": match["id"], **candidate})
        break
    return {"survivor_job_id": survivor_id, "merges": merges, "candidates": recorded}


def reject_match(conn, match_id: int) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE job_dedup_matches SET status = 'rejected', resolved_at = CURRENT_TIMESTAMP WHERE id = %s AND status = 'candidate'", (match_id,))
