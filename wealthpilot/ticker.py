"""Ticker dashboard backend: overview, chart series, growth score, profile-fit score.

Design rules
------------
* Every number carries its origin: computed from price history (with the
  window used), reported by the data provider (with retrieval time), or a
  third-party OPINION (analyst targets and estimates), never mixed up.
* Missing data stays missing. A score built on too few factors is not shown.
* Neither score predicts a price. The growth score describes the business's
  measured growth profile; the fit score says how well the asset suits one
  investor's profile and portfolio.

Data sources are pluggable: ``YFinanceSource`` (live, cached on disk),
``StarterSource`` (offline, the organizers' dataset, prices only) or any object
with the same four methods (used by the tests).
"""

from __future__ import annotations

import io
import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from . import metrics as m

# --------------------------------------------------------------------------- data sources

TIMEFRAMES = {  # label -> (yfinance period, interval)
    "1D": ("1d", "5m"),
    "5D": ("5d", "30m"),
    "1M": ("1mo", "1d"),
    "6M": ("6mo", "1d"),
    "YTD": ("ytd", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1wk"),
    "MAX": ("max", "1mo"),
}


class DataSource(Protocol):
    name: str

    def history(self, ticker: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame: ...
    def info(self, ticker: str) -> dict: ...
    def statements(self, ticker: str) -> dict[str, pd.DataFrame]: ...
    def dividends(self, ticker: str) -> pd.Series: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class YFinanceSource:
    """Yahoo Finance via yfinance, cached on disk with the retrieval time.

    Yahoo's terms limit redistribution; the cache is local and git-ignored.
    """

    name = "Yahoo Finance via yfinance"

    def __init__(self, cache_dir: Path | str = Path("data/cache"), ttl_hours: float = 12.0):
        self.cache_dir = Path(cache_dir)
        self.ttl = ttl_hours * 3600
        self.retrieved_at: dict[str, str] = {}

    def _cached(self, key: str, fetch, kind: str):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{key}.json"
        if path.exists() and time.time() - path.stat().st_mtime < self.ttl:
            blob = json.loads(path.read_text())
        else:
            blob = {"retrieved_at": _now(), "kind": kind, "data": fetch()}
            path.write_text(json.dumps(blob, default=str))
        self.retrieved_at[key] = blob["retrieved_at"]
        return blob["data"]

    @staticmethod
    def _yf(ticker):
        import yfinance as yf  # imported lazily: optional dependency
        return yf.Ticker(ticker)

    def history(self, ticker, period="5y", interval="1d"):
        def fetch():
            df = self._yf(ticker).history(period=period, interval=interval, auto_adjust=False, actions=False)
            return df.reset_index().to_json(orient="split", date_format="iso")
        raw = self._cached(f"{ticker}_hist_{period}_{interval}", fetch, "history")
        df = pd.read_json(io.StringIO(raw), orient="split")
        df = df.set_index(df.columns[0])
        df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
        return df

    def info(self, ticker):
        return self._cached(f"{ticker}_info", lambda: dict(self._yf(ticker).info or {}), "info")

    def statements(self, ticker):
        def fetch():
            t = self._yf(ticker)
            out = {}
            for name, frame in (("income", t.income_stmt), ("cashflow", t.cashflow), ("balance", t.balance_sheet)):
                out[name] = frame.to_json(orient="split", date_format="iso") if frame is not None and not frame.empty else None
            return out
        raw = self._cached(f"{ticker}_statements", fetch, "statements")
        out = {}
        for k, v in raw.items():
            if v is None:
                continue
            df = pd.read_json(io.StringIO(v), orient="split")
            df.columns = pd.to_datetime(df.columns)
            out[k] = df
        return out

    def dividends(self, ticker):
        raw = self._cached(f"{ticker}_dividends",
                           lambda: self._yf(ticker).dividends.to_json(orient="split", date_format="iso"), "dividends")
        s = pd.read_json(io.StringIO(raw), orient="split", typ="series")
        s.index = pd.to_datetime(s.index, utc=True).tz_convert(None)
        return s


class StarterSource:
    """Offline fallback: the organizers' dataset. Prices and identity only, no fundamentals."""

    name = "PolyFinances starter dataset (Yahoo Finance, retrieved 2026-11-13)"

    def __init__(self, data_dir=None):
        from . import data
        self._data = data
        self.data_dir = data_dir
        self._prices = pd.read_csv(data._path("prices_daily.csv", data_dir), parse_dates=["date"])
        self._universe = data.load_universe(data_dir)
        self._actions = pd.read_csv(data._path("corporate_actions.csv", data_dir), parse_dates=["ex_date"])

    def history(self, ticker, period="5y", interval="1d"):
        p = self._prices[self._prices["ticker"] == ticker].set_index("date").sort_index()
        if p.empty:
            raise KeyError(f"{ticker} is not in the starter dataset")
        df = p.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close",
                               "adj_close": "Adj Close", "volume": "Volume"})[
            ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
        rule = {"1wk": "W-FRI", "1mo": "ME"}.get(interval)
        if rule:
            df = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                        "Adj Close": "last", "Volume": "sum"}).dropna()
        return _slice_period(df, period)

    def info(self, ticker):
        if ticker not in self._universe.index:
            return {}
        u = self._universe.loc[ticker]
        quote = {"equity": "EQUITY", "crypto": "CRYPTOCURRENCY"}.get(u["asset_class"], "ETF")
        return {"longName": u["name"], "sector": u["sector"], "currency": u["currency"],
                "exchange": u["market"], "quoteType": quote, "assetClass": u["asset_class"]}

    def statements(self, ticker):
        return {}

    def dividends(self, ticker):
        a = self._actions[(self._actions["ticker"] == ticker) & (self._actions["action"] == "dividend")]
        return a.set_index("ex_date")["value"].sort_index()


def _slice_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty or period == "max":
        return df
    end = df.index[-1]
    if period == "ytd":
        start = pd.Timestamp(end.year, 1, 1)
    else:
        n, unit = int(period[:-2] if period.endswith("mo") else period[:-1]), period[-2:] if period.endswith("mo") else period[-1]
        start = end - {"d": pd.DateOffset(days=n), "mo": pd.DateOffset(months=n), "y": pd.DateOffset(years=n)}[unit]
    return df.loc[start:]


# --------------------------------------------------------------------------- facts with provenance


@dataclass(frozen=True)
class Fact:
    value: float | str | None
    source: str        # "computed" | "provider" | "opinion"
    detail: str        # window, field name or method

    def to_dict(self):
        return asdict(self)


def _f(x):
    """JSON-safe float (None for missing/NaN)."""
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _price_column(df: pd.DataFrame) -> pd.Series:
    col = "Adj Close" if "Adj Close" in df and df["Adj Close"].notna().any() else "Close"
    return df[col].dropna()


def _value_asof(s: pd.Series, when: pd.Timestamp) -> float | None:
    s = s.loc[:when]
    return float(s.iloc[-1]) if len(s) else None


def trailing_returns(prices: pd.Series) -> dict[str, Fact]:
    """Total returns (adjusted prices) over standard windows; 3Y and 5Y are annualized."""
    end = prices.index[-1]
    out = {}
    windows = {"1W": pd.DateOffset(weeks=1), "1M": pd.DateOffset(months=1), "3M": pd.DateOffset(months=3),
               "6M": pd.DateOffset(months=6), "1Y": pd.DateOffset(years=1), "3Y": pd.DateOffset(years=3),
               "5Y": pd.DateOffset(years=5)}
    for label, off in windows.items():
        start = end - off
        if prices.index[0] > start + pd.Timedelta(days=5):
            out[label] = Fact(None, "computed", f"history starts {prices.index[0].date()}, too short for {label}")
            continue
        # last price on or before the window start; if history starts a few days later, its first price
        v0 = _value_asof(prices, start)
        if v0 is None:
            v0 = float(prices.iloc[0])
        r = prices.iloc[-1] / v0 - 1
        if label in {"3Y", "5Y"}:
            r = (1 + r) ** (1 / int(label[0])) - 1
        out[label] = Fact(_f(r), "computed", f"{start.date()} to {end.date()}" + (", annualized" if label in {"3Y", "5Y"} else ""))
    prev_year_end = _value_asof(prices, pd.Timestamp(end.year - 1, 12, 31))
    out["YTD"] = Fact(_f(prices.iloc[-1] / prev_year_end - 1) if prev_year_end else None, "computed",
                      f"{end.year - 1}-12-31 to {end.date()}")
    return out


def risk_profile(prices: pd.Series, benchmark: pd.Series | None, risk_free_annual: float) -> dict[str, Fact]:
    """Risk statistics from daily adjusted prices (crypto uses 365 periods per year)."""
    window = f"{prices.index[0].date()} to {prices.index[-1].date()}"
    daily = prices.pct_change().dropna()
    ppy = 365 if (prices.index.dayofweek >= 5).any() else 252
    rf = (1 + risk_free_annual) ** (1 / ppy) - 1
    one_year = prices.loc[prices.index[-1] - pd.DateOffset(years=1):].pct_change().dropna()
    ep = m.drawdown_episode(prices)
    # Year-end to year-end returns; the current year counts year-to-date.
    yearly = prices.resample("YE").last().pct_change().dropna()
    out = {
        "volatility_1y": Fact(_f(m.annualized_volatility(one_year, ppy)) if len(one_year) > 20 else None,
                              "computed", "last 12 months, daily returns"),
        "volatility_full": Fact(_f(m.annualized_volatility(daily, ppy)), "computed", window),
        "sharpe_full": Fact(_f(m.sharpe_ratio(daily, ppy, rf)), "computed",
                            f"{window}, risk-free {risk_free_annual:.2%}/yr"),
        "max_drawdown": Fact(_f(-ep["drawdown"]), "computed",
                             f"peak {ep['peak_date'].date()}, trough {ep['trough_date'].date()}, "
                             + (f"recovered {ep['recovery_date'].date()}" if ep["recovery_date"] is not None else "not recovered")),
        "drawdown_days": Fact(_f(((ep["recovery_date"] or prices.index[-1]) - ep["peak_date"]).days), "computed",
                              "calendar days from peak to recovery (or to today if not recovered)"),
        "worst_calendar_year": Fact(_f(yearly.min()) if len(yearly) else None, "computed",
                                    f"{yearly.idxmin().year}" if len(yearly) else "no full calendar year"),
    }
    if benchmark is not None:
        wk = pd.concat([prices, benchmark], axis=1, join="inner").resample("W-FRI").last().pct_change().dropna()
        wk = wk.loc[wk.index[-1] - pd.DateOffset(years=3):]
        if len(wk) > 26:
            cov = np.cov(wk.iloc[:, 0], wk.iloc[:, 1], ddof=1)
            out["beta"] = Fact(_f(cov[0, 1] / cov[1, 1]), "computed", f"weekly returns, last 3 years, vs {benchmark.name}")
            out["correlation"] = Fact(_f(wk.iloc[:, 0].corr(wk.iloc[:, 1])), "computed",
                                      f"weekly returns, last 3 years, vs {benchmark.name}")
    return out


# --------------------------------------------------------------------------- fundamentals

ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue"),
    "operating_income": ("Operating Income", "EBIT"),
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "fcf": ("Free Cash Flow",),
    "debt": ("Total Debt",),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
}


def _row(statements: dict[str, pd.DataFrame], key: str) -> pd.Series | None:
    for frame in statements.values():
        if frame is None:
            continue
        for label in ROWS[key]:
            if label in frame.index:
                s = frame.loc[label].dropna()
                s.index = pd.to_datetime(s.index)
                return s.sort_index().astype(float) if len(s) else None
    return None


def _cagr_from(s: pd.Series | None) -> tuple[float | None, str]:
    if s is None or len(s) < 2:
        return None, "fewer than two annual statements"
    years = (s.index[-1] - s.index[0]).days / 365.25
    if s.iloc[0] <= 0 or s.iloc[-1] <= 0:
        return None, f"not meaningful: value is negative or zero ({s.index[0].year}: {s.iloc[0]:,.0f}, {s.index[-1].year}: {s.iloc[-1]:,.0f})"
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1, f"fiscal {s.index[0].year} to {s.index[-1].year}, annualized"


def fundamentals(info: dict, statements: dict[str, pd.DataFrame], dividends: pd.Series) -> dict[str, Fact]:
    out: dict[str, Fact] = {}
    for key, field_ in (("market_cap", "marketCap"), ("trailing_pe", "trailingPE"), ("forward_pe", "forwardPE"),
                        ("price_to_book", "priceToBook"), ("dividend_yield", "dividendYield"),
                        ("payout_ratio", "payoutRatio"), ("expense_ratio", "netExpenseRatio")):
        out[key] = Fact(_f(info.get(field_)), "provider", field_)

    rev, opi, ni, fcf = (_row(statements, k) for k in ("revenue", "operating_income", "net_income", "fcf"))
    debt, eq = _row(statements, "debt"), _row(statements, "equity")

    g, why = _cagr_from(rev)
    out["revenue_growth"] = Fact(_f(g), "computed", f"revenue, {why}")
    g, why = _cagr_from(ni)
    out["earnings_growth"] = Fact(_f(g), "computed", f"net income, {why}")
    if rev is not None and opi is not None:
        margin = (opi / rev).dropna()
        out["operating_margin"] = Fact(_f(margin.iloc[-1]) if len(margin) else None, "computed",
                                       f"fiscal {margin.index[-1].year}" if len(margin) else "n/a")
        out["margin_trend"] = Fact(_f(margin.iloc[-1] - margin.iloc[0]) if len(margin) > 1 else None, "computed",
                                   f"change in operating margin, fiscal {margin.index[0].year} to {margin.index[-1].year}"
                                   if len(margin) > 1 else "fewer than two years")
    else:
        out["operating_margin"] = out["margin_trend"] = Fact(None, "computed", "revenue or operating income missing")
    if rev is not None and fcf is not None:
        fm = (fcf / rev).dropna()
        out["fcf_margin"] = Fact(_f(fm.iloc[-1]) if len(fm) else None, "computed",
                                 f"free cash flow / revenue, fiscal {fm.index[-1].year}" if len(fm) else "n/a")
    else:
        out["fcf_margin"] = Fact(None, "computed", "free cash flow or revenue missing")
    if debt is not None and eq is not None and eq.iloc[-1] > 0:
        out["debt_to_equity"] = Fact(_f(debt.iloc[-1] / eq.iloc[-1]), "computed", f"fiscal {eq.index[-1].year}")
    else:
        out["debt_to_equity"] = Fact(None, "computed", "debt or positive equity missing")

    if dividends is not None and len(dividends):
        annual = dividends.groupby(dividends.index.year).sum()
        full = annual.iloc[:-1] if len(annual) > 1 else annual  # drop the current, incomplete year
        if len(full) >= 4 and full.iloc[0] > 0:
            n = full.index[-1] - full.index[0]
            out["dividend_growth"] = Fact(_f((full.iloc[-1] / full.iloc[0]) ** (1 / n) - 1), "computed",
                                          f"annual dividends per share, {full.index[0]} to {full.index[-1]}, annualized")
        else:
            out["dividend_growth"] = Fact(None, "computed", "fewer than four full years of dividends")
    else:
        out["dividend_growth"] = Fact(None, "computed", "no dividends in the data")

    # Third-party opinions: shown as such, never as facts.
    fe, te = _f(info.get("forwardEps")), _f(info.get("trailingEps"))
    out["analyst_eps_growth"] = Fact(_f(fe / te - 1) if fe and te and te > 0 else None, "opinion",
                                     "analyst forward EPS / trailing EPS (consensus estimate)")
    target, price = _f(info.get("targetMeanPrice")), _f(info.get("currentPrice") or info.get("regularMarketPrice"))
    out["analyst_target_upside"] = Fact(_f(target / price - 1) if target and price else None, "opinion",
                                        f"mean analyst target vs current price, {info.get('numberOfAnalystOpinions', '?')} analysts")
    out["analyst_recommendation"] = Fact(info.get("recommendationKey"), "opinion", "analyst consensus label")
    return out


# --------------------------------------------------------------------------- scoring


@dataclass
class Factor:
    name: str
    value: float | None
    score: float | None   # 0..1, None when the data is missing
    weight: float
    explanation: str
    source: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Score:
    name: str
    score: float | None   # 0..100, None when coverage is insufficient
    label: str
    coverage: float       # share of factor weight with data
    factors: list[Factor]
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


MIN_COVERAGE = 0.5


def lin(x: float | None, at_zero: float, at_one: float) -> float | None:
    """Linear map of x to [0, 1]; works for decreasing scales (at_zero > at_one)."""
    if x is None:
        return None
    t = (x - at_zero) / (at_one - at_zero)
    return float(min(1.0, max(0.0, t)))


def _combine(name: str, factors: list[Factor], labels: list[tuple[float, str]], notes=None) -> Score:
    have = [f for f in factors if f.score is not None]
    total_w = sum(f.weight for f in factors)
    cov = sum(f.weight for f in have) / total_w if total_w else 0.0
    notes = list(notes or [])
    if cov < MIN_COVERAGE:
        notes.append(f"Only {cov:.0%} of the factor weight has data (minimum {MIN_COVERAGE:.0%}): no score shown.")
        return Score(name, None, "Insufficient data", cov, factors, notes)
    s = 100 * sum(f.score * f.weight for f in have) / sum(f.weight for f in have)
    label = next(lbl for threshold, lbl in labels if s >= threshold)
    if cov < 1:
        notes.append(f"{cov:.0%} of the factor weight has data; missing factors are left out, not guessed.")
    return Score(name, round(s, 1), label, cov, factors, notes)


GROWTH_LABELS = [(70, "Strong measured growth"), (45, "Moderate measured growth"), (0, "Weak measured growth")]


FINANCIAL_SECTORS = {"Financials", "Financial Services"}


def growth_score(fund: dict[str, Fact], asset_class: str, sector: str | None = None,
                 include_opinions: bool = True) -> Score:
    """Growth profile of the BUSINESS from its statements; not a price forecast."""
    if asset_class not in {"equity", "EQUITY"}:
        return Score("growth_potential", None, "Not applicable", 0.0, [],
                     ["Growth scoring uses company financial statements, which funds and crypto assets do not have."])
    v = {k: fund[k].value for k in fund}
    factors = [
        Factor("revenue_growth", v["revenue_growth"], lin(v["revenue_growth"], 0.0, 0.20), 0.25,
               "Annualized revenue growth; 0% scores 0, 20%+ scores 1.", fund["revenue_growth"].detail),
        Factor("earnings_growth", v["earnings_growth"], lin(v["earnings_growth"], 0.0, 0.25), 0.15,
               "Annualized net income growth; 0% scores 0, 25%+ scores 1.", fund["earnings_growth"].detail),
        Factor("margin_trend", v["margin_trend"], lin(v["margin_trend"], -0.05, 0.05), 0.15,
               "Change in operating margin; -5 points scores 0, +5 points scores 1.", fund["margin_trend"].detail),
        Factor("fcf_margin", v["fcf_margin"], lin(v["fcf_margin"], 0.0, 0.25), 0.15,
               "Free cash flow margin, the cash available to fund growth; 0% scores 0, 25%+ scores 1.",
               fund["fcf_margin"].detail),
        Factor("debt_to_equity", v["debt_to_equity"],
               None if sector in FINANCIAL_SECTORS else lin(v["debt_to_equity"], 2.0, 0.0), 0.15,
               "Not scored for banks and insurers: deposits and policy liabilities count as debt."
               if sector in FINANCIAL_SECTORS else
               "Leverage limits room to invest; 2.0x or more scores 0, no debt scores 1.", fund["debt_to_equity"].detail),
    ]
    if include_opinions:
        factors.append(Factor("analyst_eps_growth", v["analyst_eps_growth"], lin(v["analyst_eps_growth"], 0.0, 0.25), 0.15,
                              "Analysts' expected EPS growth. OPINION of third parties, weighted lower than measured data.",
                              fund["analyst_eps_growth"].detail))
    notes = ["Describes measured business growth. It does not predict the share price."]
    if v.get("trailing_pe") and v["trailing_pe"] > 40:
        notes.append(f"Trailing P/E of {v['trailing_pe']:.0f}: the market already prices in high growth, "
                     "so a high growth score does not mean the shares are cheap.")
    return _combine("growth_potential", factors, GROWTH_LABELS, notes)


FIT_LABELS = [(70, "Good fit"), (40, "Possible, in a small position"), (0, "Poor fit")]
HORIZON_YEARS = {"lt3": 2, "3to5": 4, "5to10": 7.5, "10to15": 12.5, "gt15": 20}
# Volatility a single holding can have and still be reasonable at each level (design choice, stated).
SINGLE_HOLDING_VOL = {1: 0.15, 2: 0.20, 3: 0.25, 4: 0.35, 5: 0.50}


def fit_score(ticker: str, risk: dict[str, Fact], asset_class: str, sector: str | None, profile,
              portfolio: dict[str, float] | None = None, universe: pd.DataFrame | None = None,
              prices: pd.DataFrame | None = None) -> Score:
    """How well the asset suits one investor profile (and their current portfolio, if given)."""
    from .profile import check_allocation

    c = profile.constraints
    level = profile.level
    vol = risk["volatility_full"].value
    mdd = risk["max_drawdown"].value
    dd_days = risk["drawdown_days"].value
    horizon = HORIZON_YEARS[profile.answers["horizon"]]
    ref_vol = SINGLE_HOLDING_VOL[level]
    notes: list[str] = []
    is_crypto = asset_class in {"crypto", "CRYPTOCURRENCY"}
    is_single = asset_class in {"equity", "EQUITY"} or is_crypto

    factors = [
        Factor("volatility", vol, lin(vol, 2 * ref_vol, ref_vol), 0.30,
               f"Volatility vs {ref_vol:.0%} accepted for one holding at level {level}; double that scores 0.",
               risk["volatility_full"].detail),
        Factor("max_drawdown", mdd, lin(mdd, 3 * c.worst_year_accepted, 1.5 * c.worst_year_accepted), 0.30,
               f"Worst fall vs the {c.worst_year_accepted:.0%} one-year loss the investor accepted "
               f"(up to 1.5x scores 1, 3x or more scores 0).", risk["max_drawdown"].detail),
        Factor("recovery_vs_horizon", dd_days / 365.25 if dd_days is not None else None,
               lin(dd_days / 365.25 if dd_days is not None else None, horizon, horizon / 2), 0.20,
               f"Years from peak to recovery vs a {horizon:g}-year horizon; half the horizon or less scores 1.",
               risk["drawdown_days"].detail),
    ]

    hard_block = None
    if is_crypto and c.max_crypto == 0:
        hard_block = "The profile allows 0% crypto."
    if asset_class in {"equity", "EQUITY"} and sector in c.excluded_sectors:
        hard_block = f"{sector} is a sector the investor chose to exclude."
    themes = profile.preferences.themes
    pref_score = 0.0 if hard_block else 1.0
    factors.append(Factor("preferences", None, pref_score, 0.10,
                          hard_block or ("Matches a theme of interest." if sector in themes else "No conflict with stated preferences."),
                          "investor preferences"))

    if portfolio and universe is not None and prices is not None and ticker in universe.index:
        size = min(c.limits.max_single_security, 0.05) if is_single else 0.10
        scaled = {k: v * (1 - size) for k, v in portfolio.items() if k != ticker}
        trial = scaled | {ticker: size + portfolio.get(ticker, 0.0) * (1 - size)}
        before = {(x.code, x.message) for x in check_allocation(portfolio, profile, universe, prices) if x.severity == "warning"}
        after = [x for x in check_allocation(trial, profile, universe, prices) if x.severity == "warning"]
        new = [x for x in after if (x.code, x.message) not in before]
        cols = list(dict.fromkeys([t for t in portfolio if t in prices] + [ticker]))
        corr = prices[cols].resample("W-FRI").last().pct_change().corr()[ticker].drop(ticker)
        top = corr.idxmax() if len(corr) else None
        overlap = float(corr.max()) if len(corr) else None
        score = 1.0 if not new else 0.0
        if overlap is not None and overlap > 0.8:
            score = min(score, 0.5)
        factors.append(Factor("portfolio_impact", overlap, score, 0.10,
                              (f"Adding {size:.0%} creates: " + "; ".join(x.message for x in new)) if new else
                              f"Adding {size:.0%} keeps the portfolio within its limits"
                              + (f"; highest correlation is with {top} ({overlap:.2f})." if top else "."),
                              "check_allocation + weekly correlations"))
    else:
        notes.append("No current portfolio given: the impact on the portfolio is not assessed.")

    suggested = None
    if not hard_block and is_single and vol:
        cap = c.max_crypto if is_crypto else c.limits.max_single_security
        suggested = min(cap, cap * ref_vol / vol)
        notes.append(f"Suggested maximum position: {suggested:.1%} (limit {cap:.1%}, scaled down by volatility).")

    s = _combine("profile_fit", factors, FIT_LABELS, notes)
    if hard_block:
        s.score, s.label = 0.0, "Not suitable"
        s.notes.insert(0, hard_block)
    return s


# --------------------------------------------------------------------------- overview


FUND_BLOCK = {"XEF.TO": "international_equity", "XEC.TO": "emerging_equity",
              "XIU.TO": "canadian_equity", "SPY": "us_equity", "QQQ": "us_equity", "ESGV": "us_equity",
              "XBB.TO": "fixed_income", "AGG": "fixed_income", "TLT": "fixed_income", "ZST.TO": "short_term"}


def long_run_assumption(ticker: str) -> dict | None:
    """Planning assumption (FP Canada / IFP 2026) for broad funds; None where no assumption exists."""
    from . import assumptions
    block = FUND_BLOCK.get(ticker)
    if block is None:
        return None
    return {"block": block, "annual_return": assumptions.RETURNS[block], "source": assumptions.SOURCE["name"]}


def auto_source():
    """Live Yahoo data when yfinance is installed, else the offline starter dataset."""
    try:
        import yfinance  # noqa: F401
        return YFinanceSource()
    except ImportError:
        return StarterSource()


def default_benchmark(currency: str | None) -> str:
    return "XIU.TO" if currency == "CAD" else "SPY"


def chart(source: DataSource, ticker: str, timeframe: str = "1Y") -> dict:
    """Points for a price chart. Uses unadjusted closes, as quoted on the exchange."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {list(TIMEFRAMES)}")
    period, interval = TIMEFRAMES[timeframe]
    h = source.history(ticker, period=period, interval=interval)
    close = h["Close"].dropna()
    return {
        "ticker": ticker, "timeframe": timeframe, "interval": interval,
        "points": [{"t": i.isoformat(), "close": float(v)} for i, v in close.items()],
        "change": _f(close.iloc[-1] / close.iloc[0] - 1) if len(close) > 1 else None,
        "source": source.name,
    }


def overview(ticker: str, source: DataSource, profile=None, portfolio: dict[str, float] | None = None,
             universe: pd.DataFrame | None = None, prices_cad: pd.DataFrame | None = None,
             risk_free_annual: float = 0.025, benchmark: str | None = None) -> dict:
    """Everything the dashboard shows for one ticker, with provenance."""
    ticker = ticker.strip().upper()
    info = source.info(ticker) or {}
    hist = source.history(ticker, period="5y", interval="1d")
    if hist.empty:
        raise KeyError(f"no price history for {ticker}")
    px = _price_column(hist)
    px.name = ticker
    close = hist["Close"].dropna()

    asset_class = info.get("assetClass") or info.get("quoteType", "EQUITY")
    currency = info.get("currency")
    bench_t = benchmark or default_benchmark(currency)
    bench = None
    if bench_t != ticker:
        try:
            bench = _price_column(source.history(bench_t, period="5y", interval="1d"))
            bench.name = bench_t
        except Exception:  # benchmark is optional; say so instead of failing
            bench = None

    last_year = close.loc[close.index[-1] - pd.DateOffset(years=1):]
    price = {
        "last": Fact(_f(close.iloc[-1]), "provider", f"close on {close.index[-1].date()}"),
        "change_1d": Fact(_f(close.iloc[-1] / close.iloc[-2] - 1) if len(close) > 1 else None, "computed", "last two closes"),
        "high_52w": Fact(_f(last_year.max()), "computed", "max close, last 12 months"),
        "low_52w": Fact(_f(last_year.min()), "computed", "min close, last 12 months"),
        "from_52w_high": Fact(_f(close.iloc[-1] / last_year.max() - 1), "computed", "last close vs 12-month high"),
    }
    risk = risk_profile(px, bench, risk_free_annual)
    fund = fundamentals(info, source.statements(ticker), source.dividends(ticker))

    rel = None
    if bench is not None:
        j = pd.concat([px, bench], axis=1, join="inner").dropna()
        j = j.loc[j.index[-1] - pd.DateOffset(years=1):]
        rel = {"benchmark": bench_t,
               "asset_1y": _f(j.iloc[-1, 0] / j.iloc[0, 0] - 1), "benchmark_1y": _f(j.iloc[-1, 1] / j.iloc[0, 1] - 1),
               "note": "total return in each asset's listing currency"}

    result = {
        "ticker": ticker,
        "identity": {"name": info.get("longName") or info.get("shortName"), "sector": info.get("sector"),
                     "industry": info.get("industry"), "exchange": info.get("exchange"), "currency": currency,
                     "asset_class": asset_class, "country": info.get("country"),
                     "summary": (info.get("longBusinessSummary") or "")[:600] or None},
        "price": {k: v.to_dict() for k, v in price.items()},
        "returns": {k: v.to_dict() for k, v in trailing_returns(px).items()},
        "risk": {k: v.to_dict() for k, v in risk.items()},
        "fundamentals": {k: v.to_dict() for k, v in fund.items()},
        "vs_benchmark": rel,
        "growth_score": growth_score(fund, asset_class, info.get("sector")).to_dict(),
        # Unbiased potential: measured business data only (no analyst opinion, no news, no investor profile).
        "potential_score": growth_score(fund, asset_class, info.get("sector"), include_opinions=False).to_dict(),
        "long_run_assumption": long_run_assumption(ticker),
        "fit_score": None,
        "data": {"source": source.name,
                 "retrieved_at": getattr(source, "retrieved_at", {}).get(f"{ticker}_info"),
                 "price_basis": "adjusted close (dividends reinvested) for returns and risk; close for the chart",
                 "missing": sorted(k for k, v in fund.items() if v.value is None)},
        "disclaimer": "Simulation and education only. Not a recommendation to buy or sell.",
    }
    if profile is not None:
        result["fit_score"] = fit_score(ticker, risk, asset_class, info.get("sector"), profile,
                                        portfolio, universe, prices_cad).to_dict()
    return result
