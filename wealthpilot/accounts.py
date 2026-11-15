"""Demo accounts: sign up, log in, save the onboarding.

Two stores with the same functions:

* local SQLite file (default, for running the demo on a laptop);
* Amazon DynamoDB when ``WEALTHPILOT_USERS_TABLE`` is set (the hosted version on
  AWS Lambda, whose disk does not persist between containers).

Passwords are never stored: only a salted PBKDF2-SHA256 hash (200,000
iterations). This is a SIMULATION: users should create fictional accounts and
must not enter real banking data.
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


# ----------------------------------------------------------------------------- DynamoDB (hosted version)

_TABLE: dict = {}


def _table():
    """DynamoDB table with partition key ``pk`` (string), or None when running locally."""
    name = os.environ.get("WEALTHPILOT_USERS_TABLE")
    if not name:
        return None
    if name not in _TABLE:
        import boto3
        _TABLE[name] = boto3.resource("dynamodb").Table(name)
    return _TABLE[name]


def use_table(table) -> None:
    """Inject a table (tests use a fake one)."""
    _TABLE.clear()
    if table is not None:
        os.environ["WEALTHPILOT_USERS_TABLE"] = "injected"
        _TABLE["injected"] = table
    else:
        os.environ.pop("WEALTHPILOT_USERS_TABLE", None)


def _conditional_failed(e: Exception) -> bool:
    return getattr(e, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException"


def _bytes(v) -> bytes:
    return bytes(getattr(v, "value", v))  # boto3 returns Binary objects


def token_secret() -> bytes | None:
    """Signing key shared by every Lambda container (stored once in the table). None when running locally."""
    t = _table()
    if t is None:
        return None
    item = t.get_item(Key={"pk": "META#token_secret"}).get("Item")
    if item:
        return _bytes(item["secret"])
    try:
        t.put_item(Item={"pk": "META#token_secret", "secret": secrets.token_bytes(32)},
                   ConditionExpression="attribute_not_exists(pk)")
    except Exception as e:
        if not _conditional_failed(e):
            raise
    return _bytes(t.get_item(Key={"pk": "META#token_secret"})["Item"]["secret"])


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
    t = _table() if db is None else None
    if t is not None:
        try:
            t.put_item(Item={"pk": "USER#" + username.lower(), "salt": salt, "hash": _hash(password, salt),
                             "created": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                       ConditionExpression="attribute_not_exists(pk)")  # atomic: two sign-ups cannot share a name
        except Exception as e:
            if _conditional_failed(e):
                raise AccountError("This username is already taken.")
            raise
        return
    with _conn(db) as c:
        if c.execute("SELECT 1 FROM users WHERE username = ?", (username.lower(),)).fetchone():
            raise AccountError("This username is already taken.")
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username.lower(), salt, _hash(password, salt),
                                                             datetime.now(timezone.utc).isoformat(timespec="seconds")))


def authenticate(username: str, password: str, db: Path | None = None) -> bool:
    t = _table() if db is None else None
    if t is not None:
        item = t.get_item(Key={"pk": "USER#" + (username or "").lower()}).get("Item")
        row = (_bytes(item["salt"]), _bytes(item["hash"])) if item else None
    else:
        with _conn(db) as c:
            row = c.execute("SELECT salt, hash FROM users WHERE username = ?", ((username or "").lower(),)).fetchone()
    if row is None:
        _hash(password or "", b"0" * 16)  # same work either way, so timing does not reveal valid usernames
        return False
    return hmac.compare_digest(row[1], _hash(password or "", row[0]))


def save_profile(username: str, data: dict, db: Path | None = None) -> None:
    t = _table() if db is None else None
    if t is not None:  # stored as a JSON string: floats stay exact (no Decimal conversion)
        t.put_item(Item={"pk": "PROFILE#" + username.lower(), "data": json.dumps(data),
                         "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        return
    with _conn(db) as c:
        c.execute("INSERT OR REPLACE INTO profiles VALUES (?, ?, ?)",
                  (username.lower(), json.dumps(data), datetime.now(timezone.utc).isoformat(timespec="seconds")))


def load_profile(username: str, db: Path | None = None) -> dict | None:
    t = _table() if db is None else None
    if t is not None:
        item = t.get_item(Key={"pk": "PROFILE#" + username.lower()}).get("Item")
        return json.loads(item["data"]) if item else None
    with _conn(db) as c:
        row = c.execute("SELECT data FROM profiles WHERE username = ?", (username.lower(),)).fetchone()
    return json.loads(row[0]) if row else None


def delete_profile(username: str, db: Path | None = None) -> None:
    t = _table() if db is None else None
    if t is not None:
        t.delete_item(Key={"pk": "PROFILE#" + username.lower()})
        return
    with _conn(db) as c:
        c.execute("DELETE FROM profiles WHERE username = ?", (username.lower(),))
