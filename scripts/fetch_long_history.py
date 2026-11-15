"""Long daily price history for the assets with no financial statements and no planning assumption.

The starter dataset covers five years, too short to test a return forecast. This script downloads the full history
available on Yahoo Finance (yfinance) for gold (GLD, since 2004), Bitcoin (since 2014) and Ether (since 2017) into
data/external/long_prices.csv. Like the organizers' files, it is Yahoo-derived and not committed.

Usage: python scripts/fetch_long_history.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import forecast  # noqa: E402


def main() -> None:
    import yfinance as yf
    frames = []
    for t in forecast.ASSETS:
        h = yf.Ticker(t).history(period="max", auto_adjust=False)
        if h.empty:
            raise SystemExit(f"no data for {t}")
        h.index = h.index.tz_localize(None).normalize()
        frames.append(pd.DataFrame({"date": h.index.date, "ticker": t, "adj_close": h["Adj Close"].values,
                                    "close": h["Close"].values, "volume": h["Volume"].values}))
        print(f"{t}: {len(h)} days, {h.index.min().date()} to {h.index.max().date()}")
    out = pd.concat(frames, ignore_index=True)
    forecast.LONG_PRICES.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(forecast.LONG_PRICES, index=False)
    print(f"wrote {forecast.LONG_PRICES}")


if __name__ == "__main__":
    main()
