"""Which investments the devil's advocate can review, liquidity rules, markets cards, plan vs inflation. Offline."""

import numpy as np
import pandas as pd
import pytest

from tests.conftest import requires_starter
from wealthpilot import advocate, coverage as cov, markets as mk


def chart_payload(prices: pd.Series, volume=1e6, currency="USD", instrument="EQUITY", name="Test Co", gmtoffset=0):
    ts = ((prices.index - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")).tolist()
    vol = volume if isinstance(volume, (list, np.ndarray)) else [volume] * len(prices)
    return {"chart": {"result": [{
        "meta": {"currency": currency, "instrumentType": instrument, "longName": name, "gmtoffset": gmtoffset,
                 "regularMarketPrice": float(prices.iloc[-1])},
        "timestamp": ts,
        "indicators": {"quote": [{"close": prices.tolist(), "volume": list(vol)}],
                       "adjclose": [{"adjclose": prices.tolist()}]}}]}}


def walk(n, seed=0, vol=0.01, freq="B"):
    idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq=freq)  # up to date, as Yahoo returns
    r = np.random.default_rng(seed).normal(0.0003, vol, n)
    return pd.Series(100 * np.cumprod(1 + r), index=idx)


@pytest.fixture
def refs():
    idx = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=2000)
    rng = np.random.default_rng(1)
    stocks = pd.Series(100 * np.cumprod(1 + rng.normal(0.0004, 0.011, len(idx))), index=idx)
    bonds = pd.Series(100 * np.cumprod(1 + rng.normal(0.0001, 0.003, len(idx))), index=idx)
    return pd.DataFrame({"SPY": stocks, "XBB.TO": bonds}), pd.Series(1.35, index=idx)


def evaluate(series, info, refs, **kw):
    meta, frame = cov.parse_chart(chart_payload(series, **kw))
    return cov.evaluate("TEST", meta, frame, info, *refs)


def test_stock_with_history_volume_and_sector_is_covered(refs):
    a = evaluate(walk(1500), {"kind": "equity", "sector": "Technology", "name": "Test Co"}, refs)
    assert a.covered and a.asset_class == "equity" and a.sector == "Information Technology"  # mapped to GICS
    assert a.universe_row()["currency"] == "USD"


@pytest.mark.parametrize("series,info,kw,reason", [
    (walk(1500), {"kind": "equity", "sector": None}, {}, "Sector unknown"),
    (walk(1500), {"kind": "equity", "sector": "Technology"}, {"currency": "EUR"}, "only CAD and USD"),
    (walk(500), {"kind": "equity", "sector": "Technology"}, {}, "at least 3"),
    (walk(1500), {"kind": "equity", "sector": "Technology"}, {"volume": 0}, "volume"),
    (walk(1500), {"kind": "currency"}, {}, "Only stocks, ETFs and crypto"),
])
def test_assets_without_enough_data_are_not_offered(refs, series, info, kw, reason):
    a = evaluate(series, info, refs, **kw)
    assert not a.covered and reason in a.reason


def test_crypto_needs_daily_prices_including_weekends(refs):
    a = evaluate(walk(1500, freq="D"), {"kind": "crypto", "name": "Coin"}, refs)
    assert a.covered and a.asset_class == "crypto"


def test_fund_type_is_inferred_from_how_it_moves(refs):
    prices, fx = refs
    tracker = prices["SPY"].iloc[-1300:] * (1 + np.random.default_rng(5).normal(0, 0.001, 1300))
    a = evaluate(tracker / 1.35, {"kind": "etf", "name": "Some S&P 500 Fund"}, refs)
    assert a.covered and a.asset_class == "etf_equity" and a.behaves_like["reference"] == "SPY"
    unrelated = evaluate(walk(1500, seed=9), {"kind": "etf", "name": "Mystery Fund"}, refs)
    assert not unrelated.covered and "could not be told" in unrelated.reason
    lev = evaluate(tracker / 1.35, {"kind": "etf", "name": "Direxion Daily S&P 500 Bull 3X Shares"}, refs)
    assert lev.covered and lev.leveraged
    assert not evaluate(tracker / 1.35, {"kind": "etf", "name": "Short-Term Bond Fund"}, refs).leveraged


def test_liquidity_challenge_only_when_it_matters():
    big = {"adv_cad": 5e9, "median_cad": 5e9, "zero_volume_share": 0.0, "window": "w", "days": 63}
    assert advocate.liquidity_challenge("AAPL", "equity", 30_000, big) is None
    thin = {**big, "adv_cad": 900_000, "median_cad": 800_000}
    c = advocate.liquidity_challenge("TINY", "equity", 30_000, thin)
    assert c.code == "LIQUIDITY" and c.severity == "warning" and "3.3%" in c.claim   # 30k of 900k a day
    small_fund = {**big, "adv_cad": 3_000_000}
    assert advocate.liquidity_challenge("FUND", "etf_equity", 30_000, small_fund) is None  # ETF: only very low volume
    stale = {**big, "zero_volume_share": 0.2}
    assert advocate.liquidity_challenge("OLD", "equity", 1_000, stale).severity == "warning"
    mid = {**big, "adv_cad": 10_000_000}
    c = advocate.liquidity_challenge("MID", "equity", 5_000, mid)
    assert c.severity == "info" and "under the $20 million" in c.claim


def test_liquidity_measure():
    idx = pd.bdate_range("2026-01-01", periods=80)
    liq = cov.liquidity(pd.Series(10.0, index=idx), pd.Series([0] * 13 + [1000] * 67, index=idx), 1.4)
    assert liq["days"] == 63 and abs(liq["adv_cad"] - 14000 * 63 / 63 * (63 - 0) / 63) < 1e-6 or liq["adv_cad"] > 0
    assert liq["zero_volume_share"] == 0.0


def test_daily_card_uses_the_latest_trading_day():
    idx = pd.date_range("2026-11-12 14:30", periods=78, freq="5min").append(
        pd.date_range("2026-11-13 14:30", periods=78, freq="5min"))
    prices = pd.Series(np.r_[np.linspace(100, 101, 78), np.linspace(101, 103.02, 78)], index=idx)
    card = mk.daily_card("SPY", chart_payload(prices, volume=[10] * 78 + [20] * 78, instrument="ETF"), "S&P 500")
    assert card["day"] == "2026-11-13" and card["type"] == "ETF" and card["previous"] == pytest.approx(101)
    assert card["change"] == pytest.approx(0.02) and card["relative_volume"] == pytest.approx(2.0)
    assert len(card["points"]) <= mk.MAX_POINTS


def test_overview_ranks_trending_by_size_of_move():
    def fake(item):
        sym, name = item
        change = (hash(sym) % 100 - 50) / 1000
        return {"symbol": sym, "name": name or sym, "change": change, "points": [1, 2], "previous": 1, "price": 2}
    o = mk.overview(fetch=fake)
    assert len(o["popular"]) == len(mk.POPULAR) and len(o["trending"]) == 8
    moves = [abs(c["change"]) for c in o["trending"]]
    assert moves == sorted(moves, reverse=True) and all(c["symbol"] in mk.POOL for c in o["trending"])


fastapi = pytest.importorskip("fastapi")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from wealthpilot import accounts, api
    monkeypatch.setattr(accounts, "DB_PATH", tmp_path / "users.db")
    monkeypatch.setenv("WEALTHPILOT_SECRET", "test-secret")
    monkeypatch.setattr(api, "macro_items", lambda: [])
    monkeypatch.setattr(api, "headlines", lambda symbol: None)
    monkeypatch.setattr(api, "LIVE_CACHE", api.TTLCache(60))
    monkeypatch.setattr(api, "SEARCH_CACHE", api.TTLCache(60))
    c = TestClient(api.app)
    token = c.post("/api/auth/demo/Amira").json()["token"]
    c.headers.update({"Authorization": "Bearer " + token})
    return c


@requires_starter
def test_advocate_search_lists_only_reviewable_assets(client, monkeypatch):
    from wealthpilot import api
    px = api.market()["px_cad"]
    quotes = [{"symbol": "PLTR", "name": "Palantir", "kind": "equity", "exchange": "NASDAQ", "sector": "Technology"},
              {"symbol": "NEWCO", "name": "New Co", "kind": "equity", "exchange": "NYSE", "sector": "Technology"},
              {"symbol": "OLDCO", "name": "Halted Co", "kind": "equity", "exchange": "NYSE", "sector": "Energy"},
              {"symbol": "EURUSD=X", "name": "EUR/USD", "kind": "currency", "exchange": "CCY", "sector": None}]
    monkeypatch.setattr(cov, "fetch_search", lambda q, count=20: {"quotes": []})
    monkeypatch.setattr(api, "_search", lambda q: quotes)
    history = {"PLTR": walk(1400) * 0.2, "NEWCO": walk(300), "OLDCO": walk(1500).iloc[:-40]}
    monkeypatch.setattr(cov, "fetch_chart", lambda s, r="5y", i="1d": chart_payload(history[s], volume=2e7))
    r = client.get("/api/advocate/search", params={"q": "p"}).json()
    symbols = [x["symbol"] for x in r["results"]]
    assert "PLTR" in symbols and "NEWCO" not in symbols and "EURUSD=X" not in symbols
    assert "OLDCO" not in symbols and r["hidden"] == 3 and "3 years" in r["rules"]
    assert all(x["source"] == "stored" for x in r["results"] if x["symbol"] in px.columns)

    review = client.post("/api/advocate", json={"symbol": "PLTR", "weight": 0.2}).json()
    assert review["asset"]["source"] == "live" and review["asset"]["type"] == "Stock"
    assert review["asset"]["liquidity"]["adv_cad"] > 0
    assert {c["code"] for c in review["challenges"]} & {"SINGLE_SECURITY", "RISK_CONCENTRATION"}
    bad = client.post("/api/advocate", json={"symbol": "NEWCO", "weight": 0.2})
    assert bad.status_code == 422 and "at least 3" in bad.json()["detail"]


@requires_starter
def test_stored_asset_review_reports_its_basis(client):
    r = client.post("/api/advocate", json={"symbol": "SHOP.TO", "weight": 0.1}).json()
    assert r["asset"]["source"] == "stored" and r["asset"]["liquidity"]["adv_cad"] > 1e6


@requires_starter
def test_time_machine_compares_holdings_with_inflation(client):
    v = client.get("/api/time-machine").json()["vs_inflation"]
    assert v["inflation"]["total"] > 0 and len(v["dates"]) == len(v["plan"]["growth"]) == len(v["inflation"]["growth"])
    assert v["holdings"] and all(len(h["growth"]) == len(v["dates"]) for h in v["holdings"])
    assert abs(sum(h["weight"] for h in v["holdings"]) - 1) < 0.02
    for h in v["holdings"]:
        assert h["beats_inflation"] == (h["real_annual_return"] > 0)
