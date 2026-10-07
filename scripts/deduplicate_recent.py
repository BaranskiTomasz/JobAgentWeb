import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import _get_pool, dict_cursor
from dedup_repo import deduplicate_job, find_candidates
from jobs_repo import refresh_fingerprints


def recent_job_ids(conn, days: int) -> list[str]:
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT id FROM job_postings
           WHERE COALESCE(posted_at, created_at) >= CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
           ORDER BY COALESCE(posted_at, created_at) DESC, id""",
        (days,),
    )
    return [row["id"] for row in cur.fetchall()]


def run(conn, days: int = 21, apply: bool = False) -> dict:
    ids = recent_job_ids(conn, days)
    result = {"days": days, "jobs_scanned": 0, "auto_merged": 0, "candidates": 0}
    auto_pairs = set()
    candidate_pairs = set()
    for job_id in ids:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM job_postings WHERE id = %s", (job_id,))
        if cur.fetchone() is None:
            continue
        result["jobs_scanned"] += 1
        refresh_fingerprints(conn, job_id)
        if apply:
            decision = deduplicate_job(conn, job_id, window_days=days)
            result["auto_merged"] += len(decision["merges"])
            candidate_pairs.update(
                (match["job_id_low"], match["job_id_high"])
                for match in decision["candidates"]
            )
        else:
            matches = find_candidates(conn, job_id, window_days=days)
            auto_pairs.update(
                (match["job_id_low"], match["job_id_high"])
                for match in matches if match["auto_merge"]
            )
            candidate_pairs.update(
                (match["job_id_low"], match["job_id_high"])
                for match in matches if not match["auto_merge"]
            )
    result["candidates"] = len(candidate_pairs)
    if apply:
        conn.commit()
    else:
        conn.rollback()
        result["auto_merged"] = len(auto_pairs)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=21, choices=range(1, 91))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    conn = _get_pool().getconn()
    try:
        print(json.dumps(run(conn, days=args.days, apply=args.apply), ensure_ascii=False))
    except Exception:
        conn.rollback()
        raise
    finally:
        _get_pool().putconn(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
