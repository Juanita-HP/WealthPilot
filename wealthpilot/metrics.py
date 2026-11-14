"""Performance and risk metrics.

The core functions are a NumPy port of MetricsEngine.cpp from
nicho-spekt/backtesting-engine, with the same definitions:

* cumulative return  = last value / first value - 1
* period volatility  = sample standard deviation (ddof=1) of period returns
* Sharpe ratio       = mean / std * sqrt(periods per year)
* max drawdown       = largest peak-to-trough fall, as a positive fraction

With ``risk_free=0`` the results match the C++ engine exactly (see
tests/test_metrics.py, which cross-checks both when the C++ module is
available). Additions: a risk-free rate in the Sharpe ratio, CAGR, Sortino,
Calmar, real (inflation-adjusted) return and drawdown dates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = {"1d": 252, "1wk": 52, "1mo": 12}
DAYS_PER_YEAR = 365.25


def _as_array(x) -> np.ndarray:
    a = np.asarray(x, dtype=float)
    if a.ndim != 1:
        raise ValueError("expected a one-dimensional series")
    return a


def cumulative_return(values) -> float:
    v = _as_array(values)
    if v.size == 0:
        raise ValueError("Portfolio values vector is empty.")
    return v[-1] / v[0] - 1.0


def period_volatility(returns) -> float:
    r = _as_array(returns)
    if r.size < 2:
        raise ValueError("At least two returns are required.")
    return float(np.std(r, ddof=1))


def annualized_volatility(returns, periods_per_year: int) -> float:
    if periods_per_year <= 0:
        raise ValueError("Periods per year must be positive.")
    return period_volatility(returns) * np.sqrt(periods_per_year)


def _excess(returns, risk_free) -> np.ndarray:
    r = _as_array(returns)
    rf = np.asarray(risk_free, dtype=float)
    if rf.ndim and rf.shape != r.shape:
        raise ValueError("risk_free must be a scalar or have the same length as returns")
    return r - rf


def sharpe_ratio(returns, periods_per_year: int, risk_free=0.0) -> float:
    """Annualized Sharpe ratio. ``risk_free`` is a per-period rate (scalar or series)."""
    if periods_per_year <= 0:
        raise ValueError("Periods per year must be positive.")
    ex = _excess(returns, risk_free)
    if ex.size < 2:
        raise ValueError("At least two returns are required.")
    sd = np.std(ex, ddof=1)
    if abs(sd) < 1e-12:
        return float("nan")
    return float(np.mean(ex) / sd * np.sqrt(periods_per_year))


def sortino_ratio(returns, periods_per_year: int, risk_free=0.0) -> float:
    """Like Sharpe, but only returns below the risk-free rate count as risk."""
    ex = _excess(returns, risk_free)
    if ex.size < 2:
        raise ValueError("At least two returns are required.")
    downside = np.sqrt(np.mean(np.minimum(ex, 0.0) ** 2))
    if downside < 1e-12:
        return float("nan")
    return float(np.mean(ex) / downside * np.sqrt(periods_per_year))


def max_drawdown(values) -> float:
    v = _as_array(values)
    if v.size == 0:
        raise ValueError("Portfolio values vector is empty.")
    peaks = np.maximum.accumulate(v)
    return float(np.max((peaks - v) / peaks))


def drawdown_series(values: pd.Series) -> pd.Series:
    """Drawdown at each date, as a negative fraction (0 at a new peak)."""
    return values / values.cummax() - 1.0


def drawdown_episode(values: pd.Series) -> dict:
    """Dates of the worst drawdown: previous peak, trough, and recovery (None if not recovered)."""
    dd = drawdown_series(values)
    trough = dd.idxmin()
    peak = values.loc[:trough].idxmax()
    after = values.loc[trough:]
    recovered = after[after >= values.loc[peak]]
    return {
        "peak_date": peak,
        "trough_date": trough,
        "recovery_date": recovered.index[0] if len(recovered) else None,
        "drawdown": float(dd.loc[trough]),
        "peak_value": float(values.loc[peak]),
        "trough_value": float(values.loc[trough]),
    }


def cagr(values: pd.Series) -> float:
    """Compound annual growth rate over the calendar span of the series."""
    years = (values.index[-1] - values.index[0]).days / DAYS_PER_YEAR
    if years <= 0:
        raise ValueError("series must span more than one day")
    return float((values.iloc[-1] / values.iloc[0]) ** (1.0 / years) - 1.0)


def real_return(nominal: float, inflation: float) -> float:
    """Fisher relation: (1 + nominal) / (1 + inflation) - 1, both as fractions over the same period."""
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


@dataclass(frozen=True)
class Metrics:
    start: str
    end: str
    periods_per_year: int
    starting_value: float
    ending_value: float
    cumulative_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    mean_risk_free_annual: float

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_all(values: pd.Series, periods_per_year: int = 252, risk_free=0.0) -> Metrics:
    """All metrics for a value series indexed by date.

    ``risk_free`` is a per-period rate: a scalar, or a Series aligned to ``values``
    (e.g. data.risk_free_per_period). The first period has no return and is dropped.
    """
    values = values.dropna()
    returns = values.pct_change().iloc[1:]
    if isinstance(risk_free, pd.Series):
        rf = risk_free.reindex(returns.index).ffill().bfill().to_numpy()
        rf_annual = float((1 + rf.mean()) ** periods_per_year - 1)
    else:
        rf = float(risk_free)
        rf_annual = (1 + rf) ** periods_per_year - 1
    g = cagr(values)
    mdd = max_drawdown(values)
    return Metrics(
        start=str(values.index[0].date()),
        end=str(values.index[-1].date()),
        periods_per_year=periods_per_year,
        starting_value=float(values.iloc[0]),
        ending_value=float(values.iloc[-1]),
        cumulative_return=cumulative_return(values),
        cagr=g,
        annualized_volatility=annualized_volatility(returns, periods_per_year),
        sharpe_ratio=sharpe_ratio(returns, periods_per_year, rf),
        sortino_ratio=sortino_ratio(returns, periods_per_year, rf),
        max_drawdown=mdd,
        calmar_ratio=g / mdd if mdd > 0 else float("nan"),
        mean_risk_free_annual=rf_annual,
    )
