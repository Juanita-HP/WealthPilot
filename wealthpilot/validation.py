"""Validation of the strategist, out of sample where estimation is involved.

1. ``level_ladder``: do the five risk levels actually deliver increasing risk on
   real data? If level 4 were less volatile than level 3, the level design
   would be wrong. Checked on realized volatility, drawdown and worst 12 months.

2. ``walk_forward_sleeves``: does estimating weights from past data (inverse
   volatility) beat the fixed policy rules on the NEXT period? Expanding
   walk-forward, as in WalkForwardValidator from nicho-spekt/backtesting-engine:
   estimate on data up to t, hold until the next rebalance, measure, roll.
"""

from __future__ import annotations

import pandas as pd

from . import metrics as m
from .portfolio import backtest
from .profile import QUESTIONS, InvestorProfile, Preferences, build_profile
from .strategist import inverse_vol_allocation, policy_allocation
from .time_machine import worst_rolling


def profile_at_level(level: int, preferences: Preferences = Preferences()) -> InvestorProfile:
    """A synthetic profile whose answers all sit at the score of the requested level."""
    target = (level - 0.5) / 5
    answers = {q.id: min(q.options, key=lambda o: abs(o.score - target)).code for q in QUESTIONS}
    p = build_profile(answers, preferences)
    if p.level != level:
        raise RuntimeError(f"could not build a level-{level} profile (got {p.level})")
    return p


def level_ladder(prices: pd.DataFrame, risk_free=0.0, amount: float = 100_000.0) -> pd.DataFrame:
    rows = []
    for level in range(1, 6):
        prof = profile_at_level(level)
        w = policy_allocation(prof, prices).weights
        res = backtest(prices, w, initial_capital=amount, rebalance="quarterly", transaction_cost=0.001)
        met = m.calculate_all(res.values, 252, risk_free)
        rows.append({"level": level, "name": prof.level_name, "equity_share": prof.constraints.equity_min / 2
                     + prof.constraints.equity_max / 2, "cagr": met.cagr,
                     "volatility": met.annualized_volatility, "max_drawdown": met.max_drawdown,
                     "worst_12_months": worst_rolling(res.values)["return"], "sharpe": met.sharpe_ratio})
    return pd.DataFrame(rows).set_index("level")


def walk_forward_sleeves(profile: InvestorProfile, prices: pd.DataFrame, lookback_years: int = 1,
                         first_test_year: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Calendar-year test periods; weights for year Y use only data up to the end of Y-1."""
    years = sorted({d.year for d in prices.index})
    first = first_test_year or years[0] + lookback_years + 1
    rows = []
    policy_w = policy_allocation(profile).weights
    for y in [yr for yr in years if yr >= first]:
        est_end = prices.loc[: f"{y - 1}-12-31"].index[-1]
        test = prices.loc[f"{y}-01-01": f"{y}-12-31"]
        if len(test) < 20:
            continue
        test = prices.loc[est_end:test.index[-1]]
        iv_w = inverse_vol_allocation(profile, prices, end=est_end, lookback_years=lookback_years).weights
        r = {}
        for name, w in (("policy", policy_w), ("inverse_vol", iv_w)):
            v = backtest(test, w, rebalance=None).values
            r[f"{name}_return"] = float(v.iloc[-1] / v.iloc[0] - 1)
            r[f"{name}_vol"] = m.annualized_volatility(v.pct_change().dropna(), 252)
        rows.append({"year": y, "estimated_to": str(est_end.date()), **r})
    df = pd.DataFrame(rows).set_index("year")
    summary = {
        "test_years": len(df),
        "inverse_vol_better_return_years": int((df["inverse_vol_return"] > df["policy_return"]).sum()),
        "mean_return_difference": float((df["inverse_vol_return"] - df["policy_return"]).mean()),
        "mean_vol_difference": float((df["inverse_vol_vol"] - df["policy_vol"]).mean()),
        "lookback_years": lookback_years,
    }
    return df, summary
