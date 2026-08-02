from datetime import datetime, timedelta

from db import dict_cursor
from scripts.prune_old_records import _prune_sessions, _prune_preference_profiles


class TestPruneSessions:
    def test_prunes_old_finished_session_with_no_search_stats(self, user, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s)",
            (user["id"], datetime.utcnow() - timedelta(days=100)),
        )
        db_conn.commit()

        deleted = _prune_sessions(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 1

    def test_never_prunes_a_running_session_regardless_of_age(self, user, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO sessions (user_id, status, started_at) VALUES (%s, 'running', %s)",
            (user["id"], datetime.utcnow() - timedelta(days=100)),
        )
        db_conn.commit()

        deleted = _prune_sessions(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 0

    def test_never_prunes_a_recently_finished_session(self, user, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s)",
            (user["id"], datetime.utcnow() - timedelta(days=1)),
        )
        db_conn.commit()

        deleted = _prune_sessions(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 0

    def test_skips_an_old_session_with_search_stats_attached(self, user, db_conn):
        # Regression guard: search_stats.session_id is ON DELETE RESTRICT, and
        # search_stats itself is deliberately never pruned (it's an all-time
        # aggregate) — a session with search_stats attached must survive.
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO sessions (user_id, status, finished_at) VALUES (%s, 'done', %s) RETURNING id",
            (user["id"], datetime.utcnow() - timedelta(days=100)),
        )
        session_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO search_stats (user_id, session_id, source, search_query, location, cards_found, new_found)
               VALUES (%s, %s, 'linkedin', 'PHP', 'Poland', 5, 2)""",
            (user["id"], session_id),
        )
        db_conn.commit()

        deleted = _prune_sessions(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 0


class TestPrunePreferenceProfiles:
    def test_keeps_only_the_newest_n_per_user(self, user, db_conn):
        from scripts.prune_old_records import _PREFERENCE_PROFILES_KEEP_PER_USER
        cur = db_conn.cursor()
        total = _PREFERENCE_PROFILES_KEEP_PER_USER + 3
        for i in range(total):
            cur.execute(
                "INSERT INTO preference_profiles (user_id, content, content_format) VALUES (%s, %s, 'json')",
                (user["id"], f'[{{"signal": {i}}}]'),
            )
        db_conn.commit()

        deleted = _prune_preference_profiles(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 3

        cur.execute("SELECT COUNT(*) FROM preference_profiles WHERE user_id = %s", (user["id"],))
        assert cur.fetchone()[0] == _PREFERENCE_PROFILES_KEEP_PER_USER

    def test_does_not_prune_a_user_at_or_under_the_keep_limit(self, user, db_conn):
        from scripts.prune_old_records import _PREFERENCE_PROFILES_KEEP_PER_USER
        cur = db_conn.cursor()
        for i in range(_PREFERENCE_PROFILES_KEEP_PER_USER):
            cur.execute(
                "INSERT INTO preference_profiles (user_id, content, content_format) VALUES (%s, %s, 'json')",
                (user["id"], f'[{{"signal": {i}}}]'),
            )
        db_conn.commit()

        deleted = _prune_preference_profiles(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()
        assert deleted == 0

    def test_keeps_the_get_latest_row_after_pruning(self, user, db_conn):
        import preference_profiles_repo
        from scripts.prune_old_records import _PREFERENCE_PROFILES_KEEP_PER_USER
        cur = db_conn.cursor()
        total = _PREFERENCE_PROFILES_KEEP_PER_USER + 2
        for i in range(total):
            cur.execute(
                "INSERT INTO preference_profiles (user_id, content, content_format) VALUES (%s, %s, 'json')",
                (user["id"], f'[{{"signal": {i}}}]'),
            )
        db_conn.commit()

        _prune_preference_profiles(dict_cursor(db_conn), confirm_yes=True)
        db_conn.commit()

        latest = preference_profiles_repo.get_latest(db_conn, user["id"])
        assert latest["signals"] == [{"signal": total - 1}]
