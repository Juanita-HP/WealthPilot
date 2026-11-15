"""Add international stock funds to the simulation universe.

The organizers' universe only holds Canadian and U.S. assets. A global investor also needs the rest of the world:

* XEF.TO  iShares Core MSCI EAFE IMI Index ETF (developed markets outside North America: Europe, Japan, Australia)
* XEC.TO  iShares Core MSCI Emerging Markets IMI Index ETF (China, India, Taiwan, Brazil, ...)

Both trade on the TSX in CAD (no conversion needed) and hold foreign currencies unhedged. Their metadata is committed
in data/external/assets_universe_extra.csv; the prices come from Yahoo Finance (yfinance) and, like the organizers'
files, are not committed (data/external/extra_prices.csv is git-ignored). The date range matches the starter prices.

Usage: python scripts/fetch_international.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import data  # noqa: E402

TICKERS = ["XEF.TO", "XEC.TO"]


def main() -> None:
    import yfinance as yf
    try:
        starter = pd.read_csv(data.DATA_DIR / "prices_daily.csv", usecols=["date"], parse_dates=["date"])
        start, end = starter["date"].min(), starter["date"].max()
    except FileNotFoundError:
        end = pd.Timestamp.today().normalize()
        start = end - pd.DateOffset(years=5)
    frames = []
    for t in TICKERS:
        h = yf.Ticker(t).history(start=start.date().isoformat(), end=(end + pd.Timedelta(days=1)).date().isoformat(),
                                 auto_adjust=False)
        if h.empty:
            raise SystemExit(f"no data for {t}")
        h.index = h.index.tz_localize(None).normalize()
        frames.append(pd.DataFrame({"date": h.index.date, "ticker": t, "open": h["Open"].values, "high": h["High"].values,
                                    "low": h["Low"].values, "close": h["Close"].values, "adj_close": h["Adj Close"].values,
                                    "volume": h["Volume"].values, "currency": "CAD"}))
        print(f"{t}: {len(h)} days, {h.index.min().date()} to {h.index.max().date()}")
    out = pd.concat(frames, ignore_index=True)
    data.EXTRA_PRICES.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(data.EXTRA_PRICES, index=False)
    print(f"wrote {data.EXTRA_PRICES}")


if __name__ == "__main__":
    main()
