import os

import bcrypt

# Overridable so the test suite can use a cheap cost factor; production
# relies on the bcrypt default (12) by leaving this unset.
_BCRYPT_ROUNDS = int(os.environ.get("BCRYPT_ROUNDS", "12"))


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# Checked against on a login attempt for a username that doesn't exist, so the
# bcrypt cost runs either way and the timing doesn't reveal which usernames exist.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"not-a-real-account", bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode()
