"""HTTP API used by the React interface: auth, profile, plan, scores, relay rules. Offline (no news, no Yahoo)."""

import pytest

from tests.conftest import requires_starter

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    from wealthpilot import accounts, api
    monkeypatch.setattr(accounts, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setenv("WEALTHPILOT_SECRET", "test-secret")
    monkeypatch.setattr(api, "macro_items", lambda: [])          # no network in tests
    monkeypatch.setattr(api, "headlines", lambda symbol: None)
    return TestClient(api.app)


def signup(c, name="alice"):
    r = c.post("/api/auth/signup", json={"username": name, "password": "motdepasse123"})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_auth_flow_and_errors_in_english(client):
    h = signup(client)
    assert client.get("/api/me", headers=h).json() == {"username": "alice", "has_profile": False}
    assert client.post("/api/auth/login", json={"username": "alice", "password": "wrong-pass"}).status_code == 401
    r = client.post("/api/auth/signup", json={"username": "alice", "password": "motdepasse123"})
    assert r.status_code == 400 and "already taken" in r.json()["detail"]
    assert client.get("/api/plan").status_code == 401
    assert client.get("/api/plan", headers={"Authorization": "Bearer forged.token"}).status_code == 401


def test_token_cannot_be_forged_for_another_user(client):
    from wealthpilot import api
    token = api.make_token("alice")
    payload, sig = token.split(".")
    import base64
    other = base64.urlsafe_b64encode(b"mallory|9999999999").decode()
    assert api.read_token(token) == "alice"
    assert api.read_token(other + "." + sig) is None


def test_meta_is_english_and_complete(client):
    m = client.get("/api/meta").json()
    assert {"employment", "goal_types", "questions", "themes", "personas", "blank"} <= set(m)
    labels = [o["label"] for o in m["employment"]] + [t["label"] for t in m["themes"]]
    assert all(not any(ch in label for ch in "éèàçÉ") for label in labels), labels


@requires_starter
def test_profile_plan_and_level_choice(client):
    h = signup(client)
    persona = client.get("/api/meta").json()["personas"]["Mateo"]
    assert client.get("/api/plan", headers=h).status_code == 409          # profile first
    pv = client.post("/api/onboarding/preview", json={"onboarding": persona}, headers=h).json()
    assert pv["profile"]["name"] == "Balanced"
    assert client.put("/api/profile", json={"onboarding": persona}, headers=h).status_code == 200
    plan = client.get("/api/plan", headers=h).json()
    assert plan["name"] == "Balanced" and len(plan["goals"]) == 3
    assert abs(sum(x["weight"] for x in plan["combined"]) - 1) < 1e-6
    assert {r["kind"] for r in plan["risks"]} == {"market", "credit", "liquidity", "currency", "concentration", "inflation"}
    client.put("/api/profile/level", json={"level": 1}, headers=h)
    assert client.get("/api/plan", headers=h).json()["level"] == 1
    prof = client.get("/api/profile", headers=h).json()
    assert prof["chosen_level"] == 1 and [lv["name"] for lv in prof["levels"]] == ["Conservative", "Moderate", "Balanced"]


@requires_starter
def test_scores_have_gauge_zones(client, monkeypatch):
    from wealthpilot import api, ticker
    monkeypatch.setattr(ticker, "auto_source", lambda: ticker.StarterSource())
    h = signup(client)
    client.put("/api/profile", json={"onboarding": client.get("/api/meta").json()["personas"]["Robert"]}, headers=h)
    r = client.get("/api/stocks/TSLA/insights", headers=h).json()
    assert [z["tone"] for z in r["fit"]["zones"]] == ["red", "yellow", "green"]
    assert r["fit"]["zones"][-1]["to"] == 100 and r["fit"]["sentence"]
    assert 0 <= r["fit"]["score"] <= 100
    fund = client.get("/api/stocks/XIU.TO/insights", headers=h).json()
    assert fund["potential"]["score"] is None and fund["potential"]["long_run_assumption"]


@requires_starter
def test_advocate_and_lab(client):
    h = signup(client)
    client.put("/api/profile", json={"onboarding": client.get("/api/meta").json()["personas"]["Robert"]}, headers=h)
    rv = client.post("/api/advocate", json={"symbol": "TSLA", "weight": 0.3}, headers=h).json()
    assert rv["verdict"]["tone"] == "red" and all(c["title"] and c["question"] for c in rv["challenges"])
    lab = client.post("/api/lab", json={"symbol": "SPY", "strategy": "ma_crossover"}, headers=h).json()
    assert {"rule", "hold", "findings", "table"} <= set(lab)
    assert client.post("/api/lab", json={"symbol": "SPY", "strategy": "nope"}, headers=h).status_code == 404


def test_yahoo_relay_only_allows_market_data_paths(client):
    assert client.get("/api/yahoo/q1/v10/finance/quoteSummary/AAPL").status_code == 404
    assert client.get("/api/yahoo/evil/v8/finance/chart/AAPL").status_code == 404


def test_agents_report_when_not_connected(client, monkeypatch):
    monkeypatch.delenv("WEALTHPILOT_LLM", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    h = signup(client)
    r = client.post("/api/ask", json={"question": "hi"}, headers=h)
    assert r.status_code == 503 and "WEALTHPILOT_LLM" in r.json()["detail"]


@requires_starter
def test_plan_includes_the_inflation_forecast_card(client):
    h = signup(client)
    client.put("/api/profile", json={"onboarding": client.get("/api/meta").json()["personas"]["Mateo"]}, headers=h)
    card = client.get("/api/plan", headers=h).json()["inflation"]
    if card is None:
        pytest.skip("inflation model or macro history not available")
    assert card["low"] < card["forecast"] < card["high"] and card["horizon_months"] == 12
    ml = card["ml"]
    assert len(ml["top"]) == 3 and abs(ml["top"][0]["contribution"]) >= abs(ml["top"][2]["contribution"])
    assert ml["low"] < ml["forecast"] < ml["high"] and ml["mae"] > 0
