import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


# A fixed, valid-format bcrypt hash with no known matching password — never used to
# authenticate anyone. Callers check a login attempt against this when the username
# doesn't exist, so bcrypt's ~100-300ms cost runs either way: without it, an unknown
# username short-circuits before ever calling verify_password, and the timing
# difference alone reveals which usernames exist on an invite-only, meant-to-be-
# private system.
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"not-a-real-account", bcrypt.gensalt()).decode()
