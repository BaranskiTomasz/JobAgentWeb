"""Issue, list, or revoke per-user JobAgent automation keys.

Usage:
    POSTGRES_PASSWORD=... python scripts/issue_automation_key.py --username maryna --label maryna-laptop
    POSTGRES_PASSWORD=... python scripts/issue_automation_key.py --username tobiasz --label tobiasz-laptop --can-access-catalog
    POSTGRES_PASSWORD=... python scripts/issue_automation_key.py --list
    POSTGRES_PASSWORD=... python scripts/issue_automation_key.py --revoke 1
"""
import argparse
import os
import sys

import psycopg2
from psycopg2.extensions import connection as PgConnection

import automation_keys_repo
import users_repo
from config import POSTGRES


def _connect() -> PgConnection:
    password = os.environ.get("POSTGRES_PASSWORD") or POSTGRES["password"]
    if not password:
        raise RuntimeError("Set POSTGRES_PASSWORD in the environment before running this script.")
    return psycopg2.connect(
        host=POSTGRES["host"],
        port=POSTGRES["port"],
        dbname=POSTGRES["dbname"],
        user=POSTGRES["user"],
        password=password,
    )


def _issue(
    conn: PgConnection,
    username: str,
    label: str,
    *,
    can_access_catalog: bool = False,
) -> int:
    user = users_repo.get_by_username(conn, username)
    if user is None:
        print(f"Unknown user: {username}", file=sys.stderr)
        return 1
    _, raw_key = automation_keys_repo.create(
        conn,
        user["id"],
        label,
        can_access_catalog=can_access_catalog,
    )
    conn.commit()
    print("Store this key now; it cannot be retrieved again.", file=sys.stderr)
    print(raw_key)
    return 0


def _list(conn: PgConnection) -> int:
    for key in automation_keys_repo.list_all(conn):
        print(
            f"{key['id']}\t{key['username']}\t{key['label']}\t"
            f"can_access_catalog={key['can_access_catalog']}\t{key['created_at']}"
        )
    return 0


def _revoke(conn: PgConnection, key_id: int) -> int:
    if not automation_keys_repo.delete(conn, key_id):
        print(f"Unknown automation key id: {key_id}", file=sys.stderr)
        return 1
    conn.commit()
    print(f"Revoked automation key {key_id}.", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage JobAgent automation keys")
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument("--list", action="store_true", help="List issued keys")
    operations.add_argument("--revoke", type=int, metavar="KEY_ID", help="Revoke a key")
    parser.add_argument("--username", help="User receiving the key")
    parser.add_argument("--label", help="Human-readable key label")
    parser.add_argument(
        "--can-access-catalog",
        action="store_true",
        help="Allow access to shared catalog automation routes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    is_issue = bool(args.username or args.label or args.can_access_catalog)
    if not args.list and args.revoke is None and not is_issue:
        parser.print_usage(sys.stderr)
        return 2
    if is_issue and (not args.username or not args.label):
        print("Issuing a key requires both --username and --label.", file=sys.stderr)
        return 2
    if is_issue and (args.list or args.revoke is not None):
        print("Choose exactly one operation.", file=sys.stderr)
        return 2

    try:
        conn = _connect()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    try:
        if args.list:
            return _list(conn)
        if args.revoke is not None:
            return _revoke(conn, args.revoke)
        return _issue(
            conn,
            args.username,
            args.label,
            can_access_catalog=args.can_access_catalog,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
