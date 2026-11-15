"""Markets overview for the search page: popular investments and today's biggest moves, each with its daily chart.

"Trending" is our own stated rule, not a popularity feed: the largest price moves of the latest trading day among a
fixed pool of widely held stocks, ETFs and crypto assets (POOL). Volume today vs the previous days is shown next to
it. It is information, never a recommendation.

Data: Yahoo Finance chart endpoint (5 days of 5-minute bars), the same source as the stock page.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from .coverage import fetch_chart

POPULAR = [("SPY", "S&P 500 (SPDR ETF)"), ("QQQ", "Nasdaq-100 (Invesco ETF)"), ("XIU.TO", "S&P/TSX 60 (iShares ETF)"),
           ("XEQT.TO", "iShares Core Equity ETF Portfolio"), ("BTC-USD", "Bitcoin"), ("ETH-USD", "Ether"),
           ("GLD", "Gold (SPDR Gold Shares)"), ("CAD=X", "U.S. dollar in Canadian dollars")]
POOL = ["RY.TO", "TD.TO", "BMO.TO", "BNS.TO", "CM.TO", "MFC.TO", "ENB.TO", "CNQ.TO", "SU.TO", "CNR.TO", "CP.TO",
        "TRI.TO", "SHOP.TO", "CSU.TO", "ATD.TO", "BCE.TO", "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
        "AVGO", "AMD", "NFLX", "PLTR", "COST", "JPM", "XOM", "SOL-USD", "XRP-USD", "DOGE-USD"]
TYPE = {"EQUITY": "Stock", "ETF": "ETF", "CRYPTOCURRENCY": "Crypto", "CURRENCY": "Currency", "MUTUALFUND": "Fund"}
MAX_POINTS = 80


def daily_card(symbol: str, payload: dict, name: str | None = None) -> dict | None:
    """Latest trading day's 5-minute path, its change from the previous day's last price, and volume vs before."""
    result = ((payload or {}).get("chart") or {}).get("result") or []
    if not result:
        return None
    r = result[0]
    meta = r.get("meta") or {}
    ts = r.get("timestamp") or []
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    df = pd.DataFrame({"close": q.get("close"), "volume": q.get("volume")},
                      index=pd.to_datetime(np.asarray(ts, dtype="int64") + int(meta.get("gmtoffset") or 0), unit="s"))
    df = df.apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])
    if df.empty:
        return None
    days = df.index.normalize()
    last_day = days.max()
    today, before = df[days == last_day], df[days < last_day]
    prev = float(before["close"].iloc[-1]) if len(before) else None
    price = meta.get("regularMarketPrice")
    price = float(price) if isinstance(price, (int, float)) else float(today["close"].iloc[-1])
    change = price / prev - 1 if prev else None
    vols = df["volume"].fillna(0).groupby(days).sum()
    rel_volume = None
    if len(vols) > 1 and vols.iloc[:-1].mean() > 0 and vols.iloc[-1] > 0:
        rel_volume = float(vols.iloc[-1] / vols.iloc[:-1].mean())
    path = today["close"]
    if len(path) > MAX_POINTS:
        path = path.iloc[np.linspace(0, len(path) - 1, MAX_POINTS).round().astype(int)]
    return {"symbol": symbol, "name": name or meta.get("longName") or meta.get("shortName") or symbol,
            "type": TYPE.get((meta.get("instrumentType") or "").upper(), "Other"), "currency": meta.get("currency"),
            "price": price, "previous": prev, "change": change, "relative_volume": rel_volume,
            "day": str(last_day.date()), "points": [round(float(x), 6) for x in path.values]}


def _card(item):
    symbol, name = item
    try:
        return daily_card(symbol, fetch_chart(symbol, "5d", "5m"), name)
    except Exception:
        return None


def overview(fetch=_card) -> dict:
    names = dict(POPULAR)
    symbols = [s for s, _ in POPULAR] + [s for s in POOL if s not in names]
    with ThreadPoolExecutor(max_workers=12) as ex:
        cards = dict(zip(symbols, ex.map(fetch, [(s, names.get(s)) for s in symbols])))
    popular = [cards[s] for s, _ in POPULAR if cards.get(s)]
    moved = [cards[s] for s in POOL if cards.get(s) and cards[s]["change"] is not None]
    trending = sorted(moved, key=lambda c: abs(c["change"]), reverse=True)[:8]
    return {"popular": popular, "trending": trending, "pool_size": len(POOL), "loaded": sum(1 for c in cards.values() if c),
            "rule": f"Largest price moves of the latest trading day among {len(POOL)} widely held Canadian and U.S. "
                    "stocks and crypto assets. Information, not a recommendation."}
