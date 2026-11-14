import numpy as np
import pandas as pd
import pytest

from tests.conftest import requires_starter
from tests.test_profile import AMIRA, MATEO, ROBERT
from wealthpilot import profile as pf
from wealthpilot import ticker as tk

END = pd.Timestamp("2026-11-12")


def make_history(seed, mu, sigma, start=100.0, days=1300):
    idx = pd.bdate_range(end=END, periods=days)
    rng = np.random.default_rng(seed)
    close = start * np.cumprod(1 + rng.normal(mu, sigma, days))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close,
                         "Adj Close": close, "Volume": 1_000}, index=idx)


def statements(revenue, op_income, net_income, fcf, debt, equity):
    cols = pd.to_datetime(["2022-12-31", "2023-12-31", "2024-12-31", "2025-12-31"])
    income = pd.DataFrame([revenue, op_income, net_income], index=["Total Revenue", "Operating Income", "Net Income"],
                          columns=cols)
    cash = pd.DataFrame([fcf], index=["Free Cash Flow"], columns=cols)
    bal = pd.DataFrame([debt, equity], index=["Total Debt", "Stockholders Equity"], columns=cols)
    return {"income": income[cols[::-1]], "cashflow": cash, "balance": bal}  # provider order is newest first


class FakeSource:
    name = "fake"

    def __init__(self):
        self.hist = {
            "GRO": make_history(1, 0.0012, 0.035),   # fast grower, very volatile
            "STEADY": make_history(2, 0.0004, 0.010),
            "SPY": make_history(3, 0.0004, 0.011),
            "XIU.TO": make_history(4, 0.0003, 0.009),
        }
        self.inf = {
            "GRO": {"longName": "Growth Co", "sector": "Information Technology", "currency": "USD",
                    "quoteType": "EQUITY", "forwardEps": 3.0, "trailingEps": 2.0, "trailingPE": 80,
                    "targetMeanPrice": 150, "currentPrice": 120, "numberOfAnalystOpinions": 30,
                    "recommendationKey": "buy"},
            "STEADY": {"longName": "Steady Utility", "sector": "Utilities", "currency": "CAD", "quoteType": "EQUITY",
                       "dividendYield": 0.04},
            "OILCO": {"longName": "Oil Co", "sector": "Energy", "currency": "CAD", "quoteType": "EQUITY"},
            "FUND": {"longName": "Index Fund", "currency": "USD", "quoteType": "ETF"},
        }
        self.hist["OILCO"] = make_history(5, 0.0004, 0.015)
        self.hist["FUND"] = make_history(6, 0.0004, 0.011)
        self.stm = {
            "GRO": statements([100, 130, 170, 220], [10, 18, 30, 45], [5, 10, 20, 32], [8, 15, 30, 50],
                              [20, 20, 20, 20], [100, 120, 150, 190]),
            "STEADY": statements([100, 102, 104, 105], [20, 20, 19, 19], [10, 9, -2, 8], [5, 5, 4, 4],
                                 [300, 310, 320, 330], [150, 150, 150, 150]),
        }

    def history(self, ticker, period="5y", interval="1d"):
        if ticker not in self.hist:
            raise KeyError(ticker)
        return tk._slice_period(self.hist[ticker], period)

    def info(self, ticker):
        return self.inf.get(ticker, {})

    def statements(self, ticker):
        return self.stm.get(ticker, {})

    def dividends(self, ticker):
        if ticker != "STEADY":
            return pd.Series(dtype=float)
        idx = pd.to_datetime([f"{y}-06-01" for y in range(2021, 2027)])
        return pd.Series([1.00, 1.05, 1.10, 1.16, 1.22, 0.64], index=idx)


@pytest.fixture
def src():
    return FakeSource()


def test_trailing_returns_on_known_series():
    idx = pd.bdate_range("2021-01-01", "2026-11-12")
    s = pd.Series(100 * 1.10 ** ((idx - idx[0]).days / 365.25), index=idx)
    r = tk.trailing_returns(s)
    assert r["1Y"].value == pytest.approx(0.10, abs=0.002)
    assert r["5Y"].value == pytest.approx(0.10, abs=0.002)  # annualized
    assert "annualized" in r["3Y"].detail


def test_fundamentals_values_and_provenance(src):
    f = tk.fundamentals(src.info("GRO"), src.statements("GRO"), src.dividends("GRO"))
    assert f["revenue_growth"].value == pytest.approx((220 / 100) ** (1 / 3.0) - 1, rel=1e-3)
    assert f["margin_trend"].value == pytest.approx(45 / 220 - 10 / 100)
    assert f["debt_to_equity"].value == pytest.approx(20 / 190)
    assert f["analyst_eps_growth"].source == "opinion"
    assert f["analyst_target_upside"].value == pytest.approx(0.25)


def test_negative_base_earnings_growth_is_left_missing(src):
    stm = src.statements("STEADY")
    stm["income"].loc["Net Income"] = [8, -2, 9, -10]  # newest first
    f = tk.fundamentals({}, stm, pd.Series(dtype=float))
    assert f["earnings_growth"].value is None and "not meaningful" in f["earnings_growth"].detail


def test_dividend_growth_excludes_incomplete_year(src):
    f = tk.fundamentals({}, {}, src.dividends("STEADY"))
    assert f["dividend_growth"].value == pytest.approx((1.22 / 1.00) ** (1 / 4) - 1)


def test_growth_score_ranks_grower_above_steady(src):
    g = tk.overview("GRO", src)["growth_score"]
    s = tk.overview("STEADY", src)["growth_score"]
    assert g["score"] > s["score"]
    assert any("P/E" in n for n in g["notes"])  # high valuation caveat


def test_growth_score_not_applicable_to_funds(src):
    assert tk.overview("FUND", src)["growth_score"]["label"] == "Not applicable"


def test_growth_score_withheld_without_statements(src):
    s = tk.growth_score(tk.fundamentals({}, {}, pd.Series(dtype=float)), "equity")
    assert s.score is None and s.label == "Insufficient data"


def test_fit_differs_by_profile(src):
    robert = pf.build_profile(ROBERT)
    amira = pf.build_profile(AMIRA, pf.Preferences(crypto="open", themes=("Information Technology",)))
    fr = tk.overview("GRO", src, profile=robert)["fit_score"]
    fa = tk.overview("GRO", src, profile=amira)["fit_score"]
    assert fr["score"] < fa["score"]
    assert fr["label"] == "Poor fit"


def test_excluded_sector_is_not_suitable(src):
    mateo = pf.build_profile(MATEO, pf.Preferences(esg="exclude", excluded_sectors=("Energy",)))
    f = tk.overview("OILCO", src, profile=mateo)["fit_score"]
    assert f["score"] == 0 and f["label"] == "Not suitable"


def test_overview_structure(src):
    o = tk.overview("gro ", src, profile=pf.build_profile(MATEO))
    assert o["ticker"] == "GRO"
    assert o["vs_benchmark"]["benchmark"] == "SPY"
    assert set(o["returns"]) >= {"1W", "1M", "YTD", "1Y", "5Y"}
    assert "beta" in o["risk"]
    assert "Not a recommendation" in o["disclaimer"]


def test_chart_timeframes(src):
    c = tk.chart(src, "STEADY", "1M")
    assert 18 <= len(c["points"]) <= 24
    with pytest.raises(ValueError):
        tk.chart(src, "STEADY", "2W")


def test_yfinance_cache_round_trip(tmp_path, monkeypatch, src):
    calls = {"n": 0}

    class FakeYf:
        def __init__(self, t):
            self.t = t

        def history(self, period, interval, auto_adjust, actions):
            calls["n"] += 1
            return src.history(self.t, period, interval)

        @property
        def info(self):
            return src.info(self.t)

        @property
        def income_stmt(self):
            return src.statements(self.t).get("income")

        @property
        def cashflow(self):
            return src.statements(self.t).get("cashflow")

        @property
        def balance_sheet(self):
            return src.statements(self.t).get("balance")

        @property
        def dividends(self):
            return src.dividends(self.t)

    monkeypatch.setattr(tk.YFinanceSource, "_yf", staticmethod(lambda t: FakeYf(t)))
    y = tk.YFinanceSource(cache_dir=tmp_path)
    h1 = y.history("GRO", "1y", "1d")
    h2 = y.history("GRO", "1y", "1d")
    assert calls["n"] == 1, "second call served from cache"
    pd.testing.assert_series_equal(h1["Close"], h2["Close"])
    assert np.allclose(h1["Close"].to_numpy(), src.history("GRO", "1y")["Close"].to_numpy())
    f = tk.fundamentals(y.info("GRO"), y.statements("GRO"), y.dividends("GRO"))
    assert f["revenue_growth"].value == pytest.approx((220 / 100) ** (1 / 3.0) - 1, rel=1e-3)
    assert y.retrieved_at["GRO_info"]


@requires_starter
def test_offline_starter_source_scores_for_robert():
    from wealthpilot import data
    s = tk.StarterSource()
    u, px = data.load_universe(), data.load_prices_cad()
    robert = pf.build_profile(ROBERT)
    portfolio = {"XIU.TO": 0.20, "SPY": 0.15, "XBB.TO": 0.30, "ZST.TO": 0.20, "GLD": 0.05, "RY.TO": 0.05, "JNJ": 0.05}
    tsla = tk.overview("TSLA", s, profile=robert, portfolio=portfolio, universe=u, prices_cad=px)
    ry = tk.overview("RY.TO", s, profile=robert, portfolio=portfolio, universe=u, prices_cad=px)
    assert tsla["fit_score"]["label"] == "Poor fit"
    assert ry["fit_score"]["score"] > tsla["fit_score"]["score"]
    assert tsla["growth_score"]["label"] == "Insufficient data"  # no statements offline: said, not guessed
    assert tsla["risk"]["max_drawdown"]["value"] == pytest.approx(0.73, abs=0.01)
    btc = tk.overview("BTC-USD", s, profile=robert)
    assert btc["fit_score"]["label"] == "Not suitable"
