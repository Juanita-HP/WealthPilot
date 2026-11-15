"""Demo accounts: sign up, log in, save the onboarding.

Local SQLite store for the prototype. Passwords are never stored: only a salted
PBKDF2-SHA256 hash (200,000 iterations). This is a SIMULATION: users should
create fictional accounts and must not enter real banking data. In the AWS
deployment, Amazon Cognito would handle identities and DynamoDB the profiles
(see docs/aws.md).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("WEALTHPILOT_USERS_DB",
                              Path(__file__).resolve().parent.parent / "data" / "users" / "wealthpilot.db"))
ITERATIONS = 200_000
USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


class AccountError(ValueError):
    pass


@contextmanager
def _conn(db: Path | None = None):
    """Connection that commits on success, rolls back on error and is always closed."""
    path = Path(db or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    try:
        c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, salt BLOB, hash BLOB, created TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS profiles (username TEXT PRIMARY KEY, data TEXT, updated TEXT)")
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)


def create_user(username: str, password: str, db: Path | None = None) -> None:
    if not USERNAME.match(username or ""):
        raise AccountError("Username: 3 to 32 characters (letters, digits, . _ -).")
    if len(password or "") < 8:
        raise AccountError("Password: at least 8 characters.")
    salt = secrets.token_bytes(16)
    with _conn(db) as c:
        if c.execute("SELECT 1 FROM users WHERE username = ?", (username.lower(),)).fetchone():
            raise AccountError("This username is already taken.")
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username.lower(), salt, _hash(password, salt),
                                                             datetime.now(timezone.utc).isoformat(timespec="seconds")))


def authenticate(username: str, password: str, db: Path | None = None) -> bool:
    with _conn(db) as c:
        row = c.execute("SELECT salt, hash FROM users WHERE username = ?", ((username or "").lower(),)).fetchone()
    if row is None:
        _hash(password or "", b"0" * 16)  # same work either way, so timing does not reveal valid usernames
        return False
    return hmac.compare_digest(row[1], _hash(password or "", row[0]))


def save_profile(username: str, data: dict, db: Path | None = None) -> None:
    with _conn(db) as c:
        c.execute("INSERT OR REPLACE INTO profiles VALUES (?, ?, ?)",
                  (username.lower(), json.dumps(data), datetime.now(timezone.utc).isoformat(timespec="seconds")))


def load_profile(username: str, db: Path | None = None) -> dict | None:
    with _conn(db) as c:
        row = c.execute("SELECT data FROM profiles WHERE username = ?", (username.lower(),)).fetchone()
    return json.loads(row[0]) if row else None


def delete_profile(username: str, db: Path | None = None) -> None:
    with _conn(db) as c:
        c.execute("DELETE FROM profiles WHERE username = ?", (username.lower(),))
