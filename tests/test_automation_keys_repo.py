import automation_keys_repo
from security import hash_automation_key


def test_create_stores_only_hash_and_lookup_omits_it(db_conn, user):
    key_id, raw_key = automation_keys_repo.create(db_conn, user["id"], "laptop")
    db_conn.commit()
    cur = db_conn.cursor()
    cur.execute("SELECT key_hash FROM automation_keys WHERE id = %s", (key_id,))
    stored_hash = cur.fetchone()[0]
    assert stored_hash == hash_automation_key(raw_key)
    assert stored_hash != raw_key
    found = automation_keys_repo.get_by_raw_key(db_conn, raw_key)
    assert found is not None
    assert "key_hash" not in found
