"""Hosted version: DynamoDB accounts, shared token key, and the FastAPI app behind the Lambda entry point."""

import base64
import json

import pytest

from tests.test_aws import FakeS3, needs_files
from wealthpilot import accounts


class ConditionalCheckFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeUsersTable:
    """In-memory stand-in for a DynamoDB table keyed by ``pk`` (only the calls accounts.py makes)."""

    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get(Key["pk"])
        return {"Item": dict(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None):
        if ConditionExpression == "attribute_not_exists(pk)" and Item["pk"] in self.items:
            raise ConditionalCheckFailed()
        self.items[Item["pk"]] = dict(Item)

    def delete_item(self, Key):
        self.items.pop(Key["pk"], None)


@pytest.fixture
def table(monkeypatch):
    t = FakeUsersTable()
    accounts.use_table(t)
    yield t
    accounts.use_table(None)


def test_dynamodb_accounts_round_trip(table):
    accounts.create_user("Alice", "motdepasse123")
    assert "USER#alice" in table.items and "motdepasse123" not in json.dumps({k: str(v) for k, v in table.items.items()})
    with pytest.raises(accounts.AccountError, match="already taken"):
        accounts.create_user("alice", "another-password")
    assert accounts.authenticate("ALICE", "motdepasse123")
    assert not accounts.authenticate("alice", "wrong-password")
    assert not accounts.authenticate("nobody", "motdepasse123")
    assert accounts.load_profile("alice") is None
    accounts.save_profile("alice", {"answers": {"age": 30}, "amount": 1234.56})
    assert accounts.load_profile("Alice") == {"answers": {"age": 30}, "amount": 1234.56}
    accounts.delete_profile("alice")
    assert accounts.load_profile("alice") is None


def test_token_key_is_created_once_and_shared(table):
    first = accounts.token_secret()
    assert len(first) == 32 and accounts.token_secret() == first  # every container reads the same key


def test_local_sqlite_still_used_without_a_table(tmp_path, monkeypatch):
    accounts.use_table(None)
    monkeypatch.setattr(accounts, "DB_PATH", tmp_path / "users.db")
    accounts.create_user("bob", "motdepasse123")
    assert accounts.authenticate("bob", "motdepasse123") and (tmp_path / "users.db").exists()
    assert accounts.token_secret() is None


def _url_event(method, path, body=None, token=None):
    """A Lambda Function URL (payload v2) event, as CloudFront forwards it."""
    headers = {"content-type": "application/json", "host": "abc.lambda-url.us-east-1.on.aws"}
    if token:
        headers["authorization"] = "Bearer " + token
    return {
        "version": "2.0", "routeKey": "$default", "rawPath": path, "rawQueryString": "", "headers": headers,
        "requestContext": {"http": {"method": method, "path": path, "protocol": "HTTP/1.1", "sourceIp": "1.2.3.4",
                                    "userAgent": "test"}, "domainName": "abc.lambda-url.us-east-1.on.aws",
                           "accountId": "anonymous", "apiId": "abc", "requestId": "r1", "routeKey": "$default",
                           "stage": "$default", "time": "15/Nov/2026:00:00:00 +0000", "timeEpoch": 0},
        "body": base64.b64encode(json.dumps(body).encode()).decode() if body is not None else None,
        "isBase64Encoded": body is not None,
    }


@needs_files
def test_lambda_entry_point_serves_the_api(table, tmp_path, monkeypatch):
    pytest.importorskip("mangum")
    from wealthpilot.aws import api_handler

    import os
    monkeypatch.setattr(os, "environ", os.environ.copy())  # the entry point sets paths for the whole process
    monkeypatch.setattr(api_handler, "ROOT", tmp_path / "root")
    monkeypatch.setattr(api_handler, "_state", {})
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    monkeypatch.delenv("WEALTHPILOT_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)
    s3 = FakeS3()
    real_prepare = api_handler._prepare
    monkeypatch.setattr(api_handler, "_prepare", lambda: real_prepare(s3))
    from wealthpilot import api
    monkeypatch.setattr(api, "_SHARED_KEY", [])

    r = api_handler.handler(_url_event("POST", "/api/auth/signup", {"username": "carol", "password": "motdepasse123"}),
                            None)
    assert r["statusCode"] == 200, r
    token = json.loads(r["body"])["token"]
    assert "META#token_secret" in table.items and "USER#carol" in table.items
    assert (tmp_path / "root" / "starter" / "prices_daily.csv").exists() and s3.downloads  # synced to /tmp

    r = api_handler.handler(_url_event("GET", "/api/me", token=token), None)
    assert r["statusCode"] == 200 and json.loads(r["body"]) == {"username": "carol", "has_profile": False}
    assert api_handler.handler(_url_event("GET", "/api/me"), None)["statusCode"] == 401
    r = api_handler.handler(_url_event("GET", "/api/meta"), None)
    assert r["statusCode"] == 200
