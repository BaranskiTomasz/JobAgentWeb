import automation_keys_repo
from scripts import issue_automation_key


def test_issue_prints_only_raw_key_to_stdout(db_conn, user, capsys):
    result = issue_automation_key._issue(db_conn, user["username"], "laptop")
    captured = capsys.readouterr()
    raw_key = captured.out.strip()
    assert result == 0
    assert captured.out.count("\n") == 1
    assert "cannot be retrieved again" in captured.err
    assert automation_keys_repo.get_by_raw_key(db_conn, raw_key) is not None


def test_list_never_prints_key_or_hash(db_conn, user, capsys):
    _, raw_key = automation_keys_repo.create(db_conn, user["id"], "private-label")
    db_conn.commit()
    cur = db_conn.cursor()
    cur.execute("SELECT key_hash FROM automation_keys")
    key_hash = cur.fetchone()[0]
    assert issue_automation_key._list(db_conn) == 0
    output = capsys.readouterr().out
    assert user["username"] in output
    assert "private-label" in output
    assert "can_access_catalog=False" in output
    assert raw_key not in output
    assert key_hash not in output


def test_issue_scope_flag_and_revoke(db_conn, user, capsys):
    assert issue_automation_key._issue(
        db_conn,
        user["username"],
        "catalog",
        can_access_catalog=True,
    ) == 0
    catalog_key = capsys.readouterr().out.strip()
    assert issue_automation_key._issue(db_conn, user["username"], "plain") == 0
    plain_key = capsys.readouterr().out.strip()
    catalog_row = automation_keys_repo.get_by_raw_key(db_conn, catalog_key)
    plain_row = automation_keys_repo.get_by_raw_key(db_conn, plain_key)
    assert catalog_row["can_access_catalog"] is True
    assert plain_row["can_access_catalog"] is False
    assert issue_automation_key._revoke(db_conn, catalog_row["id"]) == 0
    assert automation_keys_repo.get_by_raw_key(db_conn, catalog_key) is None
    assert issue_automation_key._revoke(db_conn, catalog_row["id"]) != 0


def test_main_rejects_no_operation(capsys):
    assert issue_automation_key.main([]) != 0
    assert capsys.readouterr().out == ""


def test_main_rejects_unknown_user(db_conn, monkeypatch, capsys):
    class ConnectionProxy:
        def __getattr__(self, name):
            return getattr(db_conn, name)

        def close(self):
            pass

    monkeypatch.setattr(issue_automation_key, "_connect", ConnectionProxy)
    assert issue_automation_key.main(["--username", "nope", "--label", "x"]) != 0
    assert capsys.readouterr().out == ""
