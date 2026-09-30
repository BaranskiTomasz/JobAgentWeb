from fastapi import APIRouter, Depends

from db import dict_cursor, get_db
from deps import get_current_user

router = APIRouter(prefix="/api/sources", tags=["sources"])

_DISPLAY_NAMES = {
    "linkedin":       "LinkedIn",
    "remotive":       "Remotive.io",
    "remoteok":       "Remote OK",
    "workingnomads":  "Working Nomads",
    "weworkremotely": "We Work Remotely",
    "himalayas":      "Himalayas",
    "jobicy":         "Jobicy",
    "jobscollider":   "JobsCollider",
    "arbeitnow":      "Arbeitnow Europe",
    "arbeitnow_uk":   "Arbeitnow UK",
    "greenhouse":     "Greenhouse",
    "lever":          "Lever",
    "ashby":          "Ashby",
    "hackernews":     "HN Who's Hiring",
    "justjoin":       "justjoin.it",
    "theprotocol":    "theprotocol.it",
    "itpracuj":       "it.pracuj.pl",
    "nofluffjobs":    "NoFluffJobs",
    "solidjobs":      "SOLID.Jobs",
}


@router.get("")
def list_sources(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    # Scoped to this user's own jobs, not the whole shared pool, so the
    # dropdown only offers sources the user actually has.
    cur = dict_cursor(conn)
    cur.execute(
        """SELECT DISTINCT jp.source FROM job_postings jp
           JOIN user_job_states ujs ON ujs.job_id = jp.id
           WHERE ujs.user_id = %s AND jp.source IS NOT NULL
           ORDER BY jp.source""",
        (user["id"],),
    )
    ids = [r["source"] for r in cur.fetchall()]
    return [{"id": s, "name": _DISPLAY_NAMES.get(s, s)} for s in ids]
