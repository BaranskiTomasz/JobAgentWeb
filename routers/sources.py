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
    "justjoin":       "justjoin.it",
    "theprotocol":    "theprotocol.it",
    "itpracuj":       "it.pracuj.pl",
    "nofluffjobs":    "NoFluffJobs",
    "solidjobs":      "SOLID.Jobs",
}


@router.get("")
def list_sources(user: dict = Depends(get_current_user), conn=Depends(get_db)):
    """Distinct sources across this user's own jobs — scoped via user_job_states,
    not the whole shared pool, so the dropdown only ever offers something the user
    actually has."""
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
