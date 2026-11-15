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


@requires_starter
def test_one_click_demo_personas_and_enriched_receipts(client, monkeypatch):
    from wealthpilot import api, ticker
    from wealthpilot.agents import llm as llm_mod
    from wealthpilot.agents.llm import ScriptedLLM

    monkeypatch.setattr(ticker, "auto_source", lambda: ticker.StarterSource())

    # 1-click demo login for Amira
    r = client.post("/api/auth/demo/Amira")
    assert r.status_code == 200 and r.json()["persona"] == "Amira"
    h = {"Authorization": "Bearer " + r.json()["token"]}
    assert client.get("/api/me", headers=h).json()["has_profile"] is True
    prof_amira = client.get("/api/profile", headers=h).json()
    assert prof_amira["profile"]["name"] == "Growth" and prof_amira["persona"] == "Amira"
    fit_amira = client.get("/api/stocks/TSLA/insights", headers=h).json()["fit"]["score"]
    assert client.post("/api/auth/demo/UnknownPersona").status_code == 404

    # 1-click persona switch to Robert must invalidate INSIGHT_CACHE and update persona
    sw = client.post("/api/profile/persona/robert", headers=h)
    assert sw.status_code == 200 and sw.json()["persona"] == "Robert"
    prof_robert = client.get("/api/profile", headers=h).json()
    assert prof_robert["financials"]["age"] == 59 and prof_robert["persona"] == "Robert"
    fit_robert = client.get("/api/stocks/TSLA/insights", headers=h).json()["fit"]["score"]
    assert fit_robert != fit_amira

    # Ask endpoint with enriched R1 investor_context (age, financials, goal horizons, S&P 500 index skip)
    monkeypatch.setenv("WEALTHPILOT_LLM", "scripted")
    monkeypatch.delenv("TRACE_TABLE", raising=False)
    monkeypatch.delenv("WEALTHPILOT_TRACE_TABLE", raising=False)
    scripted = ScriptedLLM([
        "At age 59 with $140,000 income [R1], your Retirement in 4 years goal has a $600,000 target and holds S&P 500 and S&P/TSX 60 index funds [R1].",
        "No major objection for a 4-year horizon [R1].",
    ])
    monkeypatch.setattr(llm_mod, "from_env", lambda: scripted)
    ans = client.post("/api/ask", json={"question": "What is my retirement horizon?"}, headers=h).json()
    assert ans["report"]["passed"] is True
    r1 = ans["receipts"][0]
    assert r1["id"] == "R1" and r1["tool"] == "investor_context"
    assert r1["output"]["age"] == 59 and r1["output"]["financials"]["annual_income"] == 140_000
    assert len(r1["output"]["goals"]) == 2 and len(r1["output"]["current_portfolio_holdings"]) >= 1
    assert r1["plain_title"] and r1["plain_summary"] and len(r1["key_facts"]) >= 2

    # Check _summarize_receipt covers stress_test, strategy_lab, compare_allocations, plan_goals
    s_stress = api._summarize_receipt({
        "id": "R2", "tool": "stress_test", "agent": "advisor", "inputs": {},
        "output": {"scenarios": [{"label": "2008 Crash", "portfolio_return": -0.22, "dollars": -112200}]},
    })
    assert "Stress Tests" in s_stress["plain_title"] and len(s_stress["key_facts"]) == 1
    s_lab = api._summarize_receipt({
        "id": "R3", "tool": "strategy_lab", "agent": "advisor", "inputs": {"symbol": "SPY", "strategy": "rsi"},
        "output": {"result": {"symbol": "SPY", "strategy": "rsi", "out_of_sample": {"total_return": 0.12, "sharpe": 0.5},
                              "buy_hold_out_of_sample": {"total_return": 0.25, "sharpe": 0.9}}},
    })
    assert "Strategy Lab" in s_lab["plain_title"] and len(s_lab["key_facts"]) == 2

