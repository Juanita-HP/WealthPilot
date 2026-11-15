"""Which investments the devil's advocate can judge, and the data for those outside the stored universe.

The advocate's rules need, for any asset: daily prices over several years (drawdown, recovery time, past-year
return, recent vs usual swings, before/after backtest), traded volume (liquidity), the listing currency (conversion
to CAD with the Bank of Canada rate), and what the asset is (a company and its sector, a stock or bond fund, a
crypto asset). An asset is offered only when all of them are known; otherwise it is not listed at all, because a
review built on missing data would look more certain than it is.

Rules (stated, checked in tests):

* type: stock, ETF or crypto asset. Currency pairs are market context, not a holding of the plan: not reviewed.
* listing currency CAD or USD (the only rate in the audited dataset).
* at least MIN_YEARS of daily prices, with prices on at least MIN_DAYS_SHARE of the expected trading days.
* traded volume reported on recent days, and a price in the last STALE_DAYS days.
* stocks: a known sector (the ESG and sector rules would otherwise be blind).
* ETFs: what the fund holds is inferred from how it moves: correlation of weekly returns with the reference funds
  of the universe (stocks, bonds, gold). A fund that matches none clearly is not reviewed.

Prices outside the stored universe come from Yahoo Finance (chart endpoint, the same as the stock page), cached.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TYPES = {"EQUITY": "equity", "ETF": "etf", "CRYPTOCURRENCY": "crypto"}
TYPE_LABEL = {"equity": "Stock", "etf_equity": "ETF", "etf_bond": "ETF", "etf_commodity": "ETF", "etf": "ETF",
              "crypto": "Crypto", "currency": "Currency"}
CURRENCIES = {"CAD", "USD"}
MIN_YEARS = 3.0
MIN_DAYS_SHARE = 0.90
RECENT_DAYS = 63               # about three months of trading days, for liquidity
STALE_DAYS = 10                # last price older than this: not reviewed

# Yahoo sector names -> the GICS names used by the universe, the ESG exclusions and the sector limits.
SECTORS = {
    "Technology": "Information Technology", "Financial Services": "Financials", "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary", "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials", "Communication Services": "Communication Services", "Energy": "Energy",
    "Industrials": "Industrials", "Utilities": "Utilities", "Real Estate": "Real Estate",
}
GICS = set(SECTORS.values())

# Reference funds of the universe used to tell what an ETF holds (weekly return correlation over the overlap).
REFERENCE = {
    "etf_equity": {"SPY": "U.S. stocks", "QQQ": "U.S. growth stocks", "XIU.TO": "Canadian stocks",
                   "XEF.TO": "international stocks", "XEC.TO": "emerging-market stocks"},
    "etf_bond": {"XBB.TO": "Canadian bonds", "AGG": "U.S. bonds", "TLT": "long U.S. Treasuries",
                 "ZST.TO": "ultra short-term bonds"},
    "etf_commodity": {"GLD": "gold"},
}
MATCH = {"etf_equity": 0.70, "etf_bond": 0.60, "etf_commodity": 0.80}
LEVERAGED = re.compile(r"(?<![\w.])-?[2-5](?:\.\d)?x\b|\bultra(?:pro)?\b|\bleveraged\b|\binverse\b|\bbear\b|\bbull\b",
                       re.IGNORECASE)

YAHOO = "https://query1.finance.yahoo.com"


@dataclass
class Asset:
    """An asset outside the stored universe, with its coverage verdict."""
    symbol: str
    name: str
    kind: str                       # equity | etf | crypto (Yahoo type, before ETF classification)
    currency: str | None = None
    exchange: str = ""
    sector: str | None = None
    asset_class: str | None = None  # universe vocabulary once covered
    adj_close: pd.Series | None = None
    close: pd.Series | None = None
    volume: pd.Series | None = None
    covered: bool = False
    reason: str | None = None
    leveraged: bool = False
    behaves_like: dict | None = None
    checks: dict = field(default_factory=dict)

    def universe_row(self) -> dict:
        sector = self.sector
        if self.asset_class != "equity":
            sector = {"crypto": "Crypto asset", "etf_commodity": "Gold"}.get(
                self.asset_class, f"Fund ({self.behaves_like['label']})" if self.behaves_like else "Fund")
        return {"name": self.name, "asset_class": self.asset_class, "market": self.exchange or "",
                "currency": self.currency, "sector": sector, "currency_exposure": self.currency}


# ----------------------------------------------------------------------------- Yahoo (chart and search endpoints)


def _get_json(url: str, timeout: float = 15) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_chart(symbol: str, range_: str = "5y", interval: str = "1d") -> dict:
    q = urllib.parse.urlencode({"range": range_, "interval": interval, "includePrePost": "false", "events": "div,splits"})
    return _get_json(f"{YAHOO}/v8/finance/chart/{urllib.parse.quote(symbol)}?{q}")


def fetch_search(query: str, count: int = 20) -> dict:
    q = urllib.parse.urlencode({"q": query, "quotesCount": count, "newsCount": 0})
    return _get_json(f"{YAHOO}/v1/finance/search?{q}")


def search_quotes(payload: dict) -> list[dict]:
    """Yahoo search results reduced to what the coverage check needs (stocks, ETFs, crypto, currencies)."""
    out, seen = [], set()
    for x in payload.get("quotes") or []:
        sym, qt = (x.get("symbol") or "").upper(), x.get("quoteType")
        if not sym or sym in seen or qt not in (*TYPES, "CURRENCY"):
            continue
        seen.add(sym)
        out.append({"symbol": sym, "name": x.get("longname") or x.get("shortname") or sym,
                    "kind": TYPES.get(qt, "currency"), "exchange": x.get("exchDisp") or x.get("exchange") or "",
                    "sector": x.get("sector") or x.get("sectorDisp")})
    return out


def parse_chart(payload: dict) -> tuple[dict, pd.DataFrame]:
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("no chart data")
    r = result[0]
    meta = r.get("meta") or {}
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    adj = ((r.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    idx = pd.to_datetime(pd.Series(ts, dtype="int64"), unit="s").dt.normalize()
    frame = pd.DataFrame({"close": q.get("close"), "volume": q.get("volume"),
                          "adj_close": adj if adj is not None else q.get("close")}, index=pd.DatetimeIndex(idx))
    frame = frame.apply(pd.to_numeric, errors="coerce")
    frame = frame[~frame.index.duplicated(keep="last")].dropna(subset=["close"]).sort_index()
    return meta, frame


# ----------------------------------------------------------------------------- coverage rules


def _weekly(s: pd.Series) -> pd.Series:
    return s.resample("W-FRI").last().pct_change().dropna()


def classify_fund(adj_cad: pd.Series, reference_prices: pd.DataFrame) -> tuple[str | None, dict | None]:
    """Asset class of an ETF from how it moves: highest weekly correlation with the reference funds."""
    mine = _weekly(adj_cad)
    best = None
    for cls, refs in REFERENCE.items():
        for t, label in refs.items():
            if t not in reference_prices:
                continue
            both = pd.concat([mine, _weekly(reference_prices[t].dropna())], axis=1, sort=True).dropna()
            if len(both) < 52:
                continue
            c = float(both.iloc[:, 0].corr(both.iloc[:, 1]))
            if best is None or c > best["correlation"]:
                best = {"class": cls, "reference": t, "label": label, "correlation": c, "weeks": len(both)}
    if best is None or best["correlation"] < MATCH[best["class"]]:
        return None, best
    return best["class"], best


def evaluate(symbol: str, meta: dict, frame: pd.DataFrame, info: dict, reference_prices: pd.DataFrame,
             fx: pd.Series) -> Asset:
    """Apply the coverage rules to one asset's chart data. ``info``: its search result (type, name, sector)."""
    kind = info.get("kind") or TYPES.get((meta.get("instrumentType") or "").upper())
    a = Asset(symbol=symbol, name=info.get("name") or meta.get("longName") or meta.get("shortName") or symbol,
              kind=kind or "unknown", currency=(meta.get("currency") or "").upper() or None,
              exchange=info.get("exchange") or meta.get("fullExchangeName") or "")
    a.leveraged = bool(LEVERAGED.search(a.name)) and kind == "etf"

    def fail(reason: str) -> Asset:
        a.reason = reason
        return a

    if kind not in ("equity", "etf", "crypto"):
        return fail("Only stocks, ETFs and crypto assets are reviewed.")
    if a.currency not in CURRENCIES:
        return fail(f"Listed in {a.currency or 'an unknown currency'}: only CAD and USD can be converted with the audited rate.")
    if frame.empty:
        return fail("No price history.")
    years = (frame.index[-1] - frame.index[0]).days / 365.25
    expected = len(pd.bdate_range(frame.index[0], frame.index[-1])) if kind != "crypto" else \
        (frame.index[-1] - frame.index[0]).days + 1
    share = len(frame) / max(expected, 1)
    recent = frame.iloc[-RECENT_DAYS:]
    a.checks = {"years": round(years, 1), "days_share": round(min(share, 1.0), 3),
                "volume_days": int(recent["volume"].notna().sum())}
    stale_days = (pd.Timestamp.now().normalize() - frame.index[-1]).days
    if stale_days > STALE_DAYS:
        return fail(f"No price in the last {stale_days} days: trading may be halted.")
    if years < MIN_YEARS:
        return fail(f"Only {years:.1f} years of prices: at least {MIN_YEARS:g} are needed to judge falls and recoveries.")
    if share < MIN_DAYS_SHARE:
        return fail(f"Prices on only {share:.0%} of trading days: too many gaps.")
    if recent["volume"].notna().sum() < RECENT_DAYS * 0.8 or not (recent["volume"].fillna(0) > 0).any():
        return fail("No reliable traded volume: liquidity cannot be judged.")

    rate = pd.Series(1.0, index=frame.index) if a.currency == "CAD" else \
        fx.reindex(fx.index.union(frame.index)).ffill().reindex(frame.index)
    adj_cad = (frame["adj_close"] * rate).dropna()
    if kind == "equity":
        sector = SECTORS.get(info.get("sector") or "", info.get("sector") if info.get("sector") in GICS else None)
        if not sector:
            return fail("Sector unknown: the ESG and sector rules could not be applied.")
        a.sector, a.asset_class = sector, "equity"
    elif kind == "crypto":
        a.asset_class = "crypto"
    else:
        cls, best = classify_fund(adj_cad, reference_prices)
        a.behaves_like = best
        if cls is None:
            return fail("What this fund holds could not be told from its prices (no clear match with a stock, "
                        "bond or gold reference fund).")
        a.asset_class = cls
    a.adj_close, a.close, a.volume = frame["adj_close"], frame["close"], frame["volume"]
    a.checks["adj_cad"] = adj_cad
    a.covered = True
    return a


# ----------------------------------------------------------------------------- liquidity


def liquidity(close_local: pd.Series, volume: pd.Series, to_cad: float, days: int = RECENT_DAYS) -> dict | None:
    """Average daily traded value (CAD) and share of days without trades, over the last ``days`` trading days."""
    df = pd.concat([close_local, volume], axis=1, keys=["close", "volume"], sort=True).dropna().iloc[-days:]
    if len(df) < days * 0.5:
        return None
    traded = df["close"] * df["volume"] * to_cad
    return {"adv_cad": float(traded.mean()), "median_cad": float(traded.median()),
            "zero_volume_share": float((df["volume"] <= 0).mean()),
            "window": f"{df.index[0].date()} to {df.index[-1].date()}", "days": int(len(df))}


def merge_prices(prices_cad: pd.DataFrame, symbol: str, adj_cad: pd.Series) -> pd.DataFrame:
    """Add one asset to the CAD price table, on the table's calendar (forward-filled over at most 5 days)."""
    s = adj_cad[~adj_cad.index.duplicated(keep="last")]
    s = s.reindex(s.index.union(prices_cad.index)).ffill(limit=5).reindex(prices_cad.index)
    out = prices_cad.copy()
    out[symbol] = s
    return out


def to_cad_rate(currency: str | None, fx: pd.Series) -> float:
    return 1.0 if currency == "CAD" else float(np.asarray(fx.dropna())[-1])
