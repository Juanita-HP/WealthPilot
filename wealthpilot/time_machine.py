"""Time machine: replay an allocation through real past periods, in the investor's own dollars.

Two kinds of results, never mixed:

* HISTORICAL: the allocation replayed on actual prices (CAD, dividends
  reinvested, rebalanced, with costs). Facts about the past, not forecasts.
* HYPOTHETICAL: stylized shocks applied to asset groups, to test situations the
  five-year sample does not contain. Clearly labeled as assumptions.

The comparison with the loss the investor said they would accept turns a
volatility number into a concrete question: "would you have held on?"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from . import metrics as m
from .portfolio import backtest
from .profile import ASSET_GROUP, InvestorProfile

TRADING_DAYS_YEAR = 252


@dataclass
class Replay:
    amount: float
    start: str
    end: str
    final_value: float
    final_value_real: float | None
    cagr: float
    worst_drawdown: dict
    worst_12_months: dict
    calendar_years: dict[int, float]
    accepted_loss: float
    exceeded_accepted_loss: bool
    question: str
    assumptions: dict
    path: pd.DataFrame

    def to_dict(self, include_path: bool = False) -> dict:
        d = asdict(self)
        d["path"] = self.path.reset_index().to_dict(orient="list") if include_path else None
        return d


def deflator(cpi_index: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """CPI level on each date (monthly index carried forward), rebased to 1 on the first date.

    Uses the realized CPI of each reference month. That is right for measuring what money
    WAS worth; it is not point-in-time data and must not be used for decisions in a backtest.
    """
    cpi = cpi_index.sort_index()
    cpi = cpi.reindex(cpi.index.union(index)).ffill().reindex(index)
    return cpi / cpi.iloc[0]


def worst_rolling(values: pd.Series, days: int = TRADING_DAYS_YEAR) -> dict:
    r = values / values.shift(days) - 1
    end = r.idxmin()
    start = values.index[values.index.get_loc(end) - days]
    return {"return": float(r.min()), "start": str(start.date()), "end": str(end.date()),
            "value_start": float(values.loc[start]), "value_end": float(values.loc[end])}


def replay(weights: dict[str, float], prices: pd.DataFrame, profile: InvestorProfile, amount: float,
           start=None, end=None, cpi_index: pd.Series | None = None, rebalance: str = "quarterly",
           transaction_cost: float = 0.001) -> Replay:
    res = backtest(prices, weights, start=start, end=end, initial_capital=amount,
                   rebalance=rebalance, transaction_cost=transaction_cost)
    v = res.values
    ep = m.drawdown_episode(v)
    w12 = worst_rolling(v)
    years = v.resample("YE").last()
    first = v.iloc[0]
    yearly = pd.concat([pd.Series([first], index=[v.index[0]]), years]).pct_change().dropna()
    calendar = {int(d.year): float(r) for d, r in yearly.items()}

    path = pd.DataFrame({"value": v, "drawdown": m.drawdown_series(v)})
    real_final = None
    if cpi_index is not None:
        d = deflator(cpi_index, v.index)
        path["value_real"] = v / d
        real_final = float(path["value_real"].iloc[-1])

    accepted = profile.constraints.worst_year_accepted
    worst_loss = -w12["return"]
    exceeded = worst_loss > accepted
    trough_dollars = ep["trough_value"]
    question = (
        f"On {ep['trough_date'].date()}, your {amount:,.0f} $ would have been worth {trough_dollars:,.0f} $ "
        f"after peaking at {ep['peak_value']:,.0f} $ on {ep['peak_date'].date()}. "
        f"The worst 12 months ({w12['start']} to {w12['end']}) lost {worst_loss:.1%}; you said you could accept "
        f"{accepted:.0%} in a bad year. Would you have held on?"
    )
    return Replay(
        amount=amount, start=res.assumptions["start"], end=res.assumptions["end"],
        final_value=float(v.iloc[-1]), final_value_real=real_final, cagr=m.cagr(v),
        worst_drawdown={"drawdown": ep["drawdown"], "peak_date": str(ep["peak_date"].date()),
                        "trough_date": str(ep["trough_date"].date()),
                        "recovery_date": str(ep["recovery_date"].date()) if ep["recovery_date"] is not None else None,
                        "peak_value": ep["peak_value"], "trough_value": ep["trough_value"],
                        "dollars_lost": ep["peak_value"] - ep["trough_value"]},
        worst_12_months=w12, calendar_years=calendar, accepted_loss=accepted,
        exceeded_accepted_loss=exceeded, question=question,
        assumptions={**res.assumptions, "kind": "historical",
                     "real_terms": "Canadian CPI (Bank of Canada series V41690973)" if cpi_index is not None else None},
        path=path,
    )


# ----------------------------------------------------------------------------- hypothetical shocks

# Stylized, rounded one-off shocks by asset group. HYPOTHESES for sensitivity testing,
# not forecasts and not exact replicas of past events.
SHOCKS = {
    "equity_crash": {
        "label": "Severe equity crash (hypothetical, in the spirit of 2008-09)",
        "basis": "The S&P 500 fell by more than half from its 2007 peak to its 2009 low.",
        "moves": {"equity": -0.50, "bond": 0.05, "gold": 0.05, "crypto": -0.70},
    },
    "stocks_and_bonds_down": {
        "label": "Stocks and bonds fall together (hypothetical, 2022-like but deeper)",
        "basis": "In 2022 the S&P 500 and U.S. aggregate bonds both fell; see the historical replay.",
        "moves": {"equity": -0.25, "bond": -0.15, "gold": 0.0, "crypto": -0.65},
    },
    "crypto_winter": {
        "label": "Crypto collapse only (hypothetical)",
        "basis": "Bitcoin fell about 76% peak to trough in the 2021-2026 sample.",
        "moves": {"equity": 0.0, "bond": 0.0, "gold": 0.0, "crypto": -0.80},
    },
}


def shock(weights: dict[str, float], universe: pd.DataFrame, amount: float, scenario: str) -> dict:
    """Instant loss of an allocation under one hypothetical shock."""
    s = SHOCKS[scenario]
    w = pd.Series(weights, dtype=float)
    groups = universe.loc[w.index, "asset_class"].map(ASSET_GROUP)
    moves = groups.map(s["moves"]).fillna(0.0)
    ret = float((w * moves).sum())
    by_group = (w * moves).groupby(groups).sum().to_dict()
    return {"scenario": scenario, "label": s["label"], "basis": s["basis"], "kind": "hypothetical",
            "portfolio_return": ret, "dollars": amount * ret,
            "contribution_by_group": {k: float(v) for k, v in by_group.items()},
            "moves_assumed": s["moves"]}


def inflation_erosion(amount: float, years: float, rates=(0.021, 0.03, 0.04)) -> list[dict]:
    """Purchasing power of a fixed amount after ``years`` at several inflation rates (hypotheses)."""
    return [{"inflation": r, "years": years, "real_value": amount / (1 + r) ** years,
             "lost": amount - amount / (1 + r) ** years} for r in rates]


def revise_tolerance(answers: dict[str, str], would_hold: bool) -> dict[str, str]:
    """If the investor would NOT have held on, move their accepted range one step down.

    The stated tolerance is replaced by the one revealed by the replay; the profile is then
    rebuilt with profile.build_profile. Returns new answers (unchanged if would_hold).
    """
    if would_hold:
        return dict(answers)
    order = ["A", "B", "C", "D"]
    i = order.index(answers["range_choice"])
    return dict(answers, range_choice=order[max(0, i - 1)])
