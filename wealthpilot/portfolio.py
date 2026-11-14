"""Multi-asset portfolio backtest with target weights and periodic rebalancing.

Generalizes BacktesterEngine.cpp from nicho-spekt/backtesting-engine (one asset,
all-in/all-out) to a portfolio of weights. Kept from the original: transaction
costs, and an execution delay so a decision taken with information available at
the close of day t is executed at the close of day t + delay.

Assumptions (all reported in ``PortfolioResult.assumptions``)
-------------------------------------------------------------
* Prices are adjusted closes (dividends reinvested), in one currency, on one
  calendar: use data.load_prices_cad().
* Fractional units are allowed (a simulation, not an order ticket).
* The initial allocation is bought at the first close.
* Rebalancing is decided on the last business day of each period and executed
  ``execution_delay`` days later, back to the target weights.
* ``transaction_cost`` is a fraction of the value traded (commission + spread).
* ``annual_fee`` is an extra portfolio-level fee (e.g. an advisory fee or a
  mutual fund wrapper). ETF expense ratios are already inside adjusted prices,
  so do not add them again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REBALANCE_PERIODS = {"monthly": "M", "quarterly": "Q", "annual": "Y", None: None, "never": None}
WEIGHT_TOLERANCE = 1e-6


@dataclass
class PortfolioResult:
    values: pd.Series
    units: pd.DataFrame
    weights: pd.DataFrame
    trades: pd.DataFrame
    total_costs: float
    total_fees: float
    target_weights: dict[str, float]
    assumptions: dict = field(default_factory=dict)

    @property
    def returns(self) -> pd.Series:
        return self.values.pct_change().iloc[1:]


def validate_weights(weights: dict[str, float], available: pd.Index) -> pd.Series:
    w = pd.Series(weights, dtype=float)
    w = w[w != 0]
    missing = [t for t in w.index if t not in available]
    if missing:
        raise KeyError(f"no prices for {missing}")
    if (w < 0).any():
        raise ValueError("short positions are not supported")
    if abs(w.sum() - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(f"weights must sum to 1, got {w.sum():.6f}")
    return w


def _decision_dates(index: pd.DatetimeIndex, period: str | None) -> pd.DatetimeIndex:
    if period is None:
        return pd.DatetimeIndex([])
    last = index.to_series().groupby(index.to_period(period)).max()
    return pd.DatetimeIndex(last.values)


def backtest(
    prices: pd.DataFrame,
    weights: dict[str, float],
    start=None,
    end=None,
    initial_capital: float = 100_000.0,
    rebalance: str | None = "quarterly",
    transaction_cost: float = 0.0,
    annual_fee: float = 0.0,
    execution_delay: int = 1,
    periods_per_year: int = 252,
) -> PortfolioResult:
    if rebalance not in REBALANCE_PERIODS:
        raise ValueError(f"rebalance must be one of {list(REBALANCE_PERIODS)}")
    if execution_delay < 0:
        raise ValueError("execution_delay must be >= 0")

    w = validate_weights(weights, prices.columns)
    px = prices.loc[start:end, list(w.index)]
    px = px.loc[px.notna().all(axis=1).idxmax():]  # first date where every asset has a price
    if px.isna().any().any():
        gaps = px.columns[px.isna().any()].tolist()
        raise ValueError(f"missing prices inside the window for {gaps}; widen the ffill or change the window")
    if len(px) < 2:
        raise ValueError("need at least two dates")

    p = px.to_numpy()
    tw = w.to_numpy()
    n = len(px)
    daily_fee = 1.0 - (1.0 - annual_fee) ** (1.0 / periods_per_year)

    decisions = _decision_dates(px.index, REBALANCE_PERIODS[rebalance])
    pos = px.index.get_indexer(decisions)
    executions = {int(i) + execution_delay: px.index[int(i)] for i in pos if 0 < i + execution_delay < n}

    units = np.zeros_like(p)
    values = np.zeros(n)
    trades, total_cost, total_fees = [], 0.0, 0.0

    cost0 = initial_capital * transaction_cost
    current = (initial_capital - cost0) * tw / p[0]
    total_cost += cost0
    trades.append({"decision_date": px.index[0], "execution_date": px.index[0],
                   "turnover": 1.0, "cost": cost0, "reason": "initial allocation"})

    for i in range(n):
        if i > 0 and daily_fee:
            fee = current @ p[i] * daily_fee
            current = current * (1.0 - daily_fee)
            total_fees += fee
        if i in executions:
            value = current @ p[i]
            target = value * tw / p[i]
            traded = np.abs(target - current) @ p[i]
            cost = traded * transaction_cost
            current = (value - cost) * tw / p[i]
            total_cost += cost
            trades.append({"decision_date": executions[i], "execution_date": px.index[i],
                           "turnover": traded / value, "cost": cost, "reason": f"{rebalance} rebalance"})
        units[i] = current
        values[i] = current @ p[i]

    holdings = units * p
    return PortfolioResult(
        values=pd.Series(values, index=px.index, name="value"),
        units=pd.DataFrame(units, index=px.index, columns=px.columns),
        weights=pd.DataFrame(holdings / values[:, None], index=px.index, columns=px.columns),
        trades=pd.DataFrame(trades),
        total_costs=total_cost,
        total_fees=total_fees,
        target_weights=w.to_dict(),
        assumptions={
            "start": str(px.index[0].date()),
            "end": str(px.index[-1].date()),
            "initial_capital": initial_capital,
            "rebalance": rebalance,
            "execution_delay_days": execution_delay,
            "transaction_cost": transaction_cost,
            "annual_fee": annual_fee,
            "fractional_units": True,
            "prices": "adjusted close (dividends reinvested), single currency, business-day calendar",
        },
    )


def compare(prices: pd.DataFrame, portfolios: dict[str, dict[str, float]], risk_free=0.0,
            **backtest_kwargs) -> tuple[dict[str, PortfolioResult], pd.DataFrame]:
    """Run several allocations over the same dates and tabulate their metrics.

    Mirrors ComparisonEngine from nicho-spekt/backtesting-engine: every
    portfolio starts on the latest common start date so the comparison is fair.
    """
    from .metrics import calculate_all

    tickers = sorted({t for w in portfolios.values() for t in w})
    common_start = prices[tickers].notna().all(axis=1).idxmax()
    start = max(pd.Timestamp(backtest_kwargs.pop("start", common_start) or common_start), common_start)

    results, rows = {}, []
    for name, w in portfolios.items():
        res = backtest(prices, w, start=start, **backtest_kwargs)
        results[name] = res
        m = calculate_all(res.values, backtest_kwargs.get("periods_per_year", 252), risk_free)
        rows.append({"portfolio": name, **m.to_dict(), "total_costs": res.total_costs, "total_fees": res.total_fees})
    return results, pd.DataFrame(rows).set_index("portfolio")
