"""Load and align the starter dataset.

Every function here is deterministic and documented so that the agents can
cite exactly how a number was produced (source file, calendar, currency).

Conventions
-----------
* Calendar: Monday-Friday business days. Prices are forward-filled for at most
  5 days to cover exchange holidays (TSX and U.S. holidays differ). Crypto
  trades 7 days a week; weekend rows are dropped and the Friday value is used,
  so all assets share one calendar.
* Currency: the base currency is CAD (the investor is Canadian). USD prices are
  converted with the Bank of Canada daily USD/CAD rate, forward-filled on
  Canadian holidays.
* Publication lag: a macro value is only usable once it was published.
  Monthly series (CPI, unemployment) are dated to the reference month and
  released weeks later, so we treat them as available on the first day of the
  second month after the reference month (conservative). Daily series are
  treated as available the next business day.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "starter"
BASE_CURRENCY = "CAD"
FFILL_LIMIT = 5
MONTHLY_SERIES = {"STATIC_TOTALCPICHANGE", "CPIAUCSL", "UNRATE"}


def _path(name: str, data_dir: Path | None) -> Path:
    p = (data_dir or DATA_DIR) / name
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found. Copy the organizers' starter files into data/starter/ "
            "or run scripts/build_dataset.py (see README)."
        )
    return p


def load_universe(data_dir: Path | None = None) -> pd.DataFrame:
    return pd.read_csv(_path("assets_universe.csv", data_dir)).set_index("ticker")


def load_prices(field: str = "adj_close", data_dir: Path | None = None) -> pd.DataFrame:
    """Wide table (date x ticker) of one price field, in listing currency, unaligned."""
    p = pd.read_csv(_path("prices_daily.csv", data_dir), parse_dates=["date"])
    return p.pivot(index="date", columns="ticker", values=field).sort_index()


def business_days(start, end) -> pd.DatetimeIndex:
    return pd.bdate_range(start, end, name="date")


def align(prices: pd.DataFrame, index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """Put every asset on the same business-day calendar (see module docstring)."""
    idx = index if index is not None else business_days(prices.index.min(), prices.index.max())
    return prices.reindex(prices.index.union(idx)).ffill(limit=FFILL_LIMIT).reindex(idx)


def load_fx(data_dir: Path | None = None, index: pd.DatetimeIndex | None = None) -> pd.Series:
    """USD/CAD (CAD per 1 USD) on business days, forward-filled on Canadian holidays."""
    fx = pd.read_csv(_path("fx_usdcad_daily.csv", data_dir), parse_dates=["date"]).set_index("date")["usdcad"]
    idx = index if index is not None else business_days(fx.index.min(), fx.index.max())
    return fx.reindex(fx.index.union(idx)).ffill().reindex(idx)


def to_base_currency(prices: pd.DataFrame, universe: pd.DataFrame, fx: pd.Series) -> pd.DataFrame:
    """Convert USD-listed columns to CAD. Prices must already be aligned to fx's index."""
    out = prices.copy()
    usd = [t for t in out.columns if universe.loc[t, "currency"] == "USD"]
    out[usd] = out[usd].mul(fx.reindex(out.index), axis=0)
    return out


def load_prices_cad(data_dir: Path | None = None) -> pd.DataFrame:
    """Adjusted closes (dividends + splits) in CAD on a common business-day calendar."""
    universe = load_universe(data_dir)
    px = align(load_prices("adj_close", data_dir))
    fx = load_fx(data_dir, index=px.index)
    return to_base_currency(px, universe, fx)


def load_macro(series_id: str, data_dir: Path | None = None, point_in_time: bool = True) -> pd.Series:
    """One macro series. With point_in_time=True the index is the date the value became usable."""
    m = pd.read_csv(_path("macro_rates.csv", data_dir), parse_dates=["date"])
    s = m.loc[m["series_id"] == series_id].set_index("date")["value"].sort_index()
    if s.empty:
        raise KeyError(f"unknown series_id {series_id!r}")
    if point_in_time:
        if series_id in MONTHLY_SERIES:
            s.index = s.index + pd.offsets.MonthBegin(2)
        else:
            s.index = s.index + pd.offsets.BDay(1)
    s.name = series_id
    return s


def risk_free_per_period(index: pd.DatetimeIndex, series_id: str = "V39079",
                         periods_per_year: int = 252, data_dir: Path | None = None) -> pd.Series:
    """Per-period risk-free return from an annual % rate (default: Bank of Canada overnight target)."""
    rate = load_macro(series_id, data_dir)
    rate = rate.reindex(rate.index.union(index)).ffill().reindex(index).bfill()
    return (1 + rate / 100.0) ** (1.0 / periods_per_year) - 1


def currency_exposure(weights: dict[str, float], universe: pd.DataFrame) -> pd.Series:
    """Share of the portfolio by listing currency."""
    w = pd.Series(weights, dtype=float)
    return w.groupby(universe.loc[w.index, "currency"]).sum().sort_values(ascending=False)


def exposure(weights: dict[str, float], universe: pd.DataFrame, by: str) -> pd.Series:
    """Share of the portfolio by any universe column (sector, asset_class, market, currency)."""
    w = pd.Series(weights, dtype=float)
    return w.groupby(universe.loc[w.index, by]).sum().sort_values(ascending=False)


__all__ = [
    "DATA_DIR", "BASE_CURRENCY", "load_universe", "load_prices", "align", "load_fx",
    "to_base_currency", "load_prices_cad", "load_macro", "risk_free_per_period",
    "currency_exposure", "exposure", "business_days",
]
