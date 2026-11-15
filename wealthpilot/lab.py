"""Strategy lab: test a trading idea honestly on one asset.

Adapted from nicho-spekt/backtesting-engine (strategies, BacktesterEngine.cpp,
ParameterOptimizer, OptimizationPipeline, WalkForwardValidator). What changed,
and why:

* Indicators are written in pandas with the same formulas as the ``ta`` library
  (tests check they match), so the lab has no extra dependency on AWS.
* Every result shows buy-and-hold on the same dates and the OUT-OF-SAMPLE
  period. A strategy is never shown with only its optimized, in-sample numbers.
* Costs are on by default (commission per trade and slippage).
* The optimizer reports how many combinations it tried and how far the best
  in-sample Sharpe fell out of sample: the main symptom of overfitting.
* The lab answers "what would have happened?", never "buy now". It does not
  output a current signal.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from itertools import product

import numpy as np
import pandas as pd

from . import metrics as m

# --------------------------------------------------------------------------- indicators (ta-compatible)


def rsi(close: pd.Series, window: int) -> pd.Series:
    diff = close.diff()
    up = diff.where(diff > 0, 0.0)
    down = -diff.where(diff < 0, 0.0)
    ema_up = up.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    ema_down = down.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    rs = ema_up / ema_down
    return pd.Series(np.where(ema_down == 0, 100, 100 - 100 / (1 + rs)), index=close.index).where(ema_up.notna())


def bollinger(close: pd.Series, window: int, dev: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(window, min_periods=window).mean()
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    return mid - dev * sd, mid, mid + dev * sd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, min_periods=span, adjust=False).mean()


def macd(close: pd.Series, fast: int, slow: int, signal: int) -> tuple[pd.Series, pd.Series]:
    line = ema(close, fast) - ema(close, slow)
    return line, ema(line, signal)


# --------------------------------------------------------------------------- strategies -> position (0/1)


def _hold_until(enter: pd.Series, exit_: pd.Series) -> pd.Series:
    sig = pd.Series(np.nan, index=enter.index)
    sig[enter] = 1.0
    sig[exit_] = 0.0
    return sig.ffill().fillna(0).astype(int)


def sig_buy_hold(close):
    return pd.Series(1, index=close.index)


def sig_ma_crossover(close, fast, slow):
    a, b = close.rolling(fast).mean(), close.rolling(slow).mean()
    return (a > b).astype(int).where(b.notna(), 0)


def sig_rsi(close, window, lower, upper):
    r = rsi(close, window)
    return _hold_until(r < lower, r > upper)


def sig_bollinger(close, window, dev):
    lo, mid, _ = bollinger(close, window, dev)
    return _hold_until(close < lo, close > mid)


def sig_macd(close, fast, slow, signal):
    line, sl = macd(close, fast, slow, signal)
    return (line > sl).astype(int).where(sl.notna(), 0)


def sig_breakout(close, high, low):
    hi = close.rolling(high).max().shift(1)
    lo = close.rolling(low).min().shift(1)
    return _hold_until(close > hi, close < lo)


@dataclass(frozen=True)
class StrategySpec:
    name: str
    description: str
    func: callable
    defaults: dict
    grid: dict
    valid: callable = lambda p: True


def _rng(a, b, step):
    return list(range(a, b + 1, step))


STRATEGIES = {
    "buy_hold": StrategySpec("buy_hold", "Buy on the first day and hold.", sig_buy_hold, {}, {}),
    "ma_crossover": StrategySpec(
        "ma_crossover", "Invested while the fast moving average is above the slow one (trend following).",
        sig_ma_crossover, {"fast": 50, "slow": 200},
        {"fast": _rng(5, 50, 5), "slow": _rng(50, 250, 10)}, lambda p: p["fast"] < p["slow"]),
    "rsi": StrategySpec(
        "rsi", "Buy when RSI falls below 'lower' (oversold), sell when it rises above 'upper' (mean reversion).",
        sig_rsi, {"window": 14, "lower": 30, "upper": 70},
        {"window": _rng(2, 30, 2), "lower": _rng(15, 40, 5), "upper": _rng(55, 85, 5)},
        lambda p: p["lower"] < p["upper"]),
    "bollinger": StrategySpec(
        "bollinger", "Buy below the lower Bollinger band, sell above the middle band (mean reversion).",
        sig_bollinger, {"window": 20, "dev": 2.0},
        {"window": _rng(10, 50, 5), "dev": [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]}),
    "macd": StrategySpec(
        "macd", "Invested while the MACD line is above its signal line (momentum).",
        sig_macd, {"fast": 12, "slow": 26, "signal": 9},
        {"fast": _rng(5, 20, 3), "slow": _rng(20, 60, 5), "signal": _rng(5, 15, 2)}, lambda p: p["fast"] < p["slow"]),
    "breakout": StrategySpec(
        "breakout", "Buy on a new N-day high, sell on a new M-day low (breakout momentum).",
        sig_breakout, {"high": 50, "low": 20},
        {"high": _rng(20, 100, 10), "low": _rng(5, 50, 5)}, lambda p: p["low"] < p["high"]),
}


def combinations(spec: StrategySpec):
    keys = list(spec.grid)
    for values in product(*(spec.grid[k] for k in keys)):
        p = dict(zip(keys, values))
        if spec.valid(p):
            yield p


# --------------------------------------------------------------------------- backtest (port of BacktesterEngine.cpp)


@dataclass
class Costs:
    commission: float = 5.0     # dollars per trade
    slippage: float = 0.0005    # 5 basis points against us on each fill


def run(close: pd.Series, position: pd.Series, capital: float = 10_000.0, costs: Costs = Costs(),
        execution_delay: int = 1) -> pd.DataFrame:
    """All-in / all-out, whole shares, as in BacktesterEngine.cpp.

    ``position`` is the desired state after day t's close; trades execute at the close of
    t + execution_delay.
    """
    pos = position.reindex(close.index).fillna(0).astype(int)
    trades = (pos - pos.shift(fill_value=0)).shift(execution_delay, fill_value=0).to_numpy()
    p = close.to_numpy(dtype=float)
    cash, shares = capital, 0
    n_trades, cost_paid = 0, 0.0
    total = np.empty(len(p))
    held = np.empty(len(p), dtype=int)
    for i, (price, t) in enumerate(zip(p, trades)):
        if t == 1:
            exec_price = price * (1 + costs.slippage)
            qty = int((cash - costs.commission) / exec_price)
            if qty > 0:
                cash -= qty * exec_price + costs.commission
                cost_paid += qty * price * costs.slippage + costs.commission
                shares += qty
                n_trades += 1
        elif t == -1 and shares > 0:
            exec_price = price * (1 - costs.slippage)
            cash += shares * exec_price - costs.commission
            cost_paid += shares * price * costs.slippage + costs.commission
            shares = 0
            n_trades += 1
        total[i] = cash + shares * price
        held[i] = shares
    out = pd.DataFrame({"value": total, "shares": held}, index=close.index)
    out.attrs.update(trades=n_trades, costs=cost_paid)
    return out


def periods_per_year(index: pd.DatetimeIndex) -> int:
    return 365 if (index.dayofweek >= 5).any() else 252


def summarize(bt: pd.DataFrame, risk_free_annual: float = 0.0) -> dict:
    v = bt["value"]
    ppy = periods_per_year(v.index)
    rf = (1 + risk_free_annual) ** (1 / ppy) - 1
    r = v.pct_change().dropna()
    years = (v.index[-1] - v.index[0]).days / 365.25
    sharpe = m.sharpe_ratio(r, ppy, rf) if len(r) > 2 else float("nan")
    return {"start": str(v.index[0].date()), "end": str(v.index[-1].date()),
            "total_return": float(v.iloc[-1] / v.iloc[0] - 1), "cagr": m.cagr(v),
            "volatility": m.annualized_volatility(r, ppy) if len(r) > 2 else float("nan"),
            "sharpe": sharpe, "max_drawdown": m.max_drawdown(v), "trades": bt.attrs.get("trades", 0),
            "trades_per_year": bt.attrs.get("trades", 0) / years if years > 0 else float("nan"),
            "time_invested": float((bt["shares"] > 0).mean()), "costs_paid": bt.attrs.get("costs", 0.0)}


# --------------------------------------------------------------------------- honest evaluation


@dataclass
class LabResult:
    ticker: str
    strategy: str
    description: str
    mode: str
    params: dict
    combinations_tested: int
    split_date: str
    in_sample: dict
    out_of_sample: dict
    buy_hold_in_sample: dict
    buy_hold_out_of_sample: dict
    share_of_combos_beating_buy_hold_in_sample: float | None
    findings: list[dict] = field(default_factory=list)
    assumptions: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def lab_mode(profile) -> str:
    """'full' (optimization allowed) for intermediate/advanced investors, else 'guided' (default parameters)."""
    return "full" if profile is not None and profile.experience in {"intermediate", "advanced"} else "guided"


def evaluate(close: pd.Series, strategy: str, ticker: str = "", params: dict | None = None,
             optimize: bool = True, split: float = 0.7, capital: float = 10_000.0, costs: Costs = Costs(),
             risk_free_annual: float = 0.0, profile=None) -> LabResult:
    """Optimize on the first ``split`` of the history (if allowed), then test on the rest."""
    spec = STRATEGIES[strategy]
    close = close.dropna()
    mode = lab_mode(profile) if profile is not None else ("full" if optimize else "guided")
    optimize = optimize and mode == "full" and bool(spec.grid) and params is None
    cut = close.index[int(len(close) * split)]
    ins, oos = close.loc[:cut], close.loc[cut:]

    def backtest_on(segment, p):
        # Signals use the full history up to each date (indicators are causal); trading starts with
        # fresh capital at the start of the segment.
        pos = spec.func(close.loc[:segment.index[-1]], **p).loc[segment.index[0]:]
        delay = 0 if strategy == "buy_hold" else 1
        return run(segment, pos, capital, costs, delay)

    bh_in = summarize(run(ins, sig_buy_hold(ins), capital, costs, 0), risk_free_annual)
    bh_out = summarize(run(oos, sig_buy_hold(oos), capital, costs, 0), risk_free_annual)

    tested, beat = 0, 0
    chosen = dict(params or spec.defaults)
    if optimize:
        best = -math.inf
        for p in combinations(spec):
            s = summarize(backtest_on(ins, p), risk_free_annual)["sharpe"]
            tested += 1
            if not math.isfinite(s):
                continue
            beat += s > bh_in["sharpe"]
            if s > best:
                best, chosen = s, p
    res_in = summarize(backtest_on(ins, chosen), risk_free_annual)
    res_out = summarize(backtest_on(oos, chosen), risk_free_annual)

    findings = []
    if not math.isfinite(res_out["sharpe"]):
        # No variation in value (never invested): compare what was actually earned.
        findings.append({"code": "NO_POSITION_OOS" if res_out["trades"] == 0 else "LOSES_TO_BUY_HOLD_OOS",
                         "severity": "warning",
                         "message": f"Out of sample the rule {'never bought' if res_out['trades'] == 0 else 'barely traded'}: "
                                    f"return {res_out['total_return']:.1%} vs {bh_out['total_return']:.1%} for buy-and-hold."})
    elif res_out["sharpe"] < bh_out["sharpe"]:
        findings.append({"code": "LOSES_TO_BUY_HOLD_OOS", "severity": "warning",
                         "message": f"Out of sample, Sharpe {res_out['sharpe']:.2f} vs {bh_out['sharpe']:.2f} for buy-and-hold."})
    else:
        findings.append({"code": "BEATS_BUY_HOLD_OOS", "severity": "info",
                         "message": f"Out of sample, Sharpe {res_out['sharpe']:.2f} vs {bh_out['sharpe']:.2f} for buy-and-hold. "
                                    "One period is weak evidence; see the walk-forward test."})
    if optimize and math.isfinite(res_in["sharpe"]) and math.isfinite(res_out["sharpe"]) \
            and res_in["sharpe"] - res_out["sharpe"] > 0.5:
        findings.append({"code": "OVERFITTING_SIGN", "severity": "warning",
                         "message": f"The best of {tested} parameter sets had Sharpe {res_in['sharpe']:.2f} in sample but "
                                    f"{res_out['sharpe']:.2f} out of sample. Picking the best of many tries finds luck as "
                                    "well as skill."})
    if res_out["trades"] < 4:
        findings.append({"code": "TOO_FEW_TRADES", "severity": "info",
                         "message": f"Only {res_out['trades']} trades out of sample: too few to judge the rule."})
    if res_out["time_invested"] < 0.5 and res_out["total_return"] < bh_out["total_return"]:
        findings.append({"code": "OUT_OF_MARKET", "severity": "info",
                         "message": f"Invested {res_out['time_invested']:.0%} of the time; missing up days explains part of the gap."})
    if res_out["costs_paid"] > 0.01 * capital:
        findings.append({"code": "COSTS_MATTER", "severity": "info",
                         "message": f"Trading costs were ${res_out['costs_paid']:,.0f} out of sample "
                                    f"({res_out['costs_paid'] / capital:.1%} of starting capital)."})

    return LabResult(
        ticker=ticker, strategy=strategy, description=spec.description, mode=mode, params=chosen,
        combinations_tested=tested, split_date=str(cut.date()), in_sample=res_in, out_of_sample=res_out,
        buy_hold_in_sample=bh_in, buy_hold_out_of_sample=bh_out,
        share_of_combos_beating_buy_hold_in_sample=(beat / tested) if tested else None, findings=findings,
        assumptions={"capital": capital, "commission_per_trade": costs.commission, "slippage": costs.slippage,
                     "execution": "next close after the signal", "shares": "whole shares, all-in / all-out",
                     "prices": "adjusted closes (dividends reinvested)", "split": f"{split:.0%} in sample",
                     "risk_free_annual": risk_free_annual, "current_signal": "not provided (simulation only)"},
    )


def walk_forward(close: pd.Series, strategy: str, folds: int = 5, capital: float = 10_000.0,
                 costs: Costs = Costs(), risk_free_annual: float = 0.0) -> dict:
    """Expanding walk-forward like WalkForwardValidator: optimize on folds 1..k, test on fold k+1."""
    close = close.dropna()
    spec = STRATEGIES[strategy]
    edges = [close.index[int(len(close) * i / folds)] for i in range(folds)] + [close.index[-1]]
    rows = []
    for k in range(1, folds):
        train = close.loc[: edges[k]]
        test = close.loc[edges[k]: edges[k + 1]]
        if len(test) < 20:
            continue
        sub = evaluate(pd.concat([train, test.iloc[1:]]), strategy, split=len(train) / (len(train) + len(test) - 1),
                       capital=capital, costs=costs, risk_free_annual=risk_free_annual, optimize=bool(spec.grid))
        rows.append({"fold": k, "test_start": sub.split_date, "test_end": str(test.index[-1].date()),
                     "params": sub.params, "strategy_return": sub.out_of_sample["total_return"],
                     "buy_hold_return": sub.buy_hold_out_of_sample["total_return"],
                     "strategy_sharpe": sub.out_of_sample["sharpe"], "buy_hold_sharpe": sub.buy_hold_out_of_sample["sharpe"]})
    df = pd.DataFrame(rows)
    return {"folds": rows, "folds_beating_buy_hold": int((df["strategy_return"] > df["buy_hold_return"]).sum()) if len(df) else 0,
            "n_folds": len(df),
            "parameters_changed_between_folds": bool(len({str(r["params"]) for r in rows}) > 1)}
