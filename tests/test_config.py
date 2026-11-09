import os
import subprocess
import sys


def test_non_integer_legacy_key_user_id_fails_at_import():
    environment = os.environ.copy()
    environment["SECRET_KEY"] = "test-secret"
    environment["JOBAGENT_API_KEY_USER_ID"] = "not-an-integer"
    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert result.returncode != 0
    assert "JOBAGENT_API_KEY_USER_ID must be an integer" in result.stderr
