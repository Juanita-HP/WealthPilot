"""Daily OHLCV history for the market-timing check (QQQ, VGT, SPY, XIU.TO and the VIX), from Yahoo Finance.

Writes data/external/timing_prices.csv (adjusted prices; Yahoo-derived, not committed).
Usage: python scripts/fetch_timing_history.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import timing  # noqa: E402


def main() -> None:
    import yfinance as yf
    frames = []
    for t in [*timing.ASSETS, timing.VIX]:
        h = yf.Ticker(t).history(start="2004-01-01", auto_adjust=True)
        if h.empty:
            raise SystemExit(f"no data for {t}")
        h.index = h.index.tz_localize(None).normalize()
        frames.append(pd.DataFrame({"date": h.index.date, "ticker": t, "open": h["Open"].values, "high": h["High"].values,
                                    "low": h["Low"].values, "close": h["Close"].values, "volume": h["Volume"].values}))
        print(f"{t}: {len(h)} days, {h.index.min().date()} to {h.index.max().date()}")
    out = pd.concat(frames, ignore_index=True)
    timing.PRICES.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(timing.PRICES, index=False)
    print(f"wrote {timing.PRICES}")


if __name__ == "__main__":
    main()
