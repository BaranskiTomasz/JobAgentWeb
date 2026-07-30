def test_no_profile_yet(logged_in_client):
    resp = logged_in_client.get("/api/preference-profile")
    assert resp.status_code == 200
    assert resp.json()["profile"] is None


def test_save_and_get_latest(logged_in_client):
    signals = [{"type": "ACCEPT", "dim": "remote", "value": "yes"}]
    logged_in_client.post("/api/preference-profile", json={
        "signals": signals, "applied_count": 3, "rejected_count": 5,
    })
    profile = logged_in_client.get("/api/preference-profile").json()["profile"]
    assert profile["signals"] == signals
    assert profile["applied_count"] == 3
    assert profile["rejected_count"] == 5


def test_isolated_per_user(logged_in_client, other_logged_in_client):
    logged_in_client.post("/api/preference-profile", json={
        "signals": [], "applied_count": 1, "rejected_count": 1,
    })
    assert other_logged_in_client.get("/api/preference-profile").json()["profile"] is None


def test_legacy_text_format_returns_empty_signals(user, logged_in_client, db_conn):
    """Rows written before the JSON-signals format (content_format='text', from
    before the distillation pipeline switched formats) must not break get_latest()
    — real production rows in this shape still exist. No API ever writes this
    shape anymore (save() always writes 'json'), so it's set up directly here."""
    cur = db_conn.cursor()
    cur.execute(
        "INSERT INTO preference_profiles (user_id, content, content_format, applied_count, rejected_count) "
        "VALUES (%s, %s, 'text', %s, %s)",
        (user["id"], "ACCEPT[rate=explicit; conf=HIGH]", 1, 0),
    )
    db_conn.commit()

    profile = logged_in_client.get("/api/preference-profile").json()["profile"]
    assert profile["content_format"] == "text"
    assert profile["signals"] == []
