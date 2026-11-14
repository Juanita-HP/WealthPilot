"""Risk map: the six kinds of risk from the BNC finance workshop, measured for one allocation.

market, credit, liquidity, currency, concentration, inflation. Each gets a level
(low / moderate / high), the number behind it, and a plain-language reason, so
the explanation can say WHICH risks a portfolio carries, not only "how risky".
Thresholds are design choices, stated in THRESHOLDS.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from . import assumptions
from .exposure import covariance, diversification_stats, exposure, risk_decomposition
from .profile import ASSET_GROUP

THRESHOLDS = {
    "market_vol": (0.06, 0.12),          # annualized volatility of the allocation
    "credit_bond_share": (0.30, 0.60),   # share in bond funds (investment-grade aggregates here)
    "liquidity_illiquid_share": (0.05, 0.15),
    "currency_foreign_share": (0.30, 0.60),
    "concentration_top_risk": (0.25, 0.45),
    "inflation_real_return": (0.01, 0.0),  # real return below 1%: moderate; below 0: high
}
MIN_DOLLAR_VOLUME = 20_000_000  # average daily traded value under this counts as less liquid


@dataclass
class RiskItem:
    kind: str
    level: str
    value: float
    metric: str
    reason: str

    def to_dict(self):
        return asdict(self)


def _level(x: float, lo: float, hi: float, reverse: bool = False) -> str:
    if reverse:
        return "low" if x >= lo else ("moderate" if x >= hi else "high")
    return "low" if x < lo else ("moderate" if x < hi else "high")


def risk_map(weights: dict[str, float], universe: pd.DataFrame, prices_cad: pd.DataFrame,
             dollar_volume: pd.Series | None = None, inflation: float = assumptions.INFLATION,
             expected_nominal: float | None = None) -> list[RiskItem]:
    w = pd.Series(weights, dtype=float)
    w = w[w > 0]
    groups = universe.loc[w.index, "asset_class"].map(ASSET_GROUP)
    cov = covariance(prices_cad, w.index)
    stats = diversification_stats(w.to_dict(), cov)
    items = []

    vol = stats["portfolio_volatility"]
    items.append(RiskItem("market", _level(vol, *THRESHOLDS["market_vol"]), vol, "annualized volatility (weekly, CAD)",
                          f"Prices of the holdings can fall together; this mix moved about {vol:.0%} a year."))

    bonds = float(w[groups == "bond"].sum())
    items.append(RiskItem("credit", _level(bonds, *THRESHOLDS["credit_bond_share"]), bonds, "share in bond funds",
                          "Bond issuers could fail to pay. The funds here hold mostly government and investment-grade "
                          "bonds, so this risk is spread out, but it grows with the bond share."))

    # ETF trading volume understates their liquidity (market makers trade against the underlying
    # holdings), so the volume test applies to individual stocks only.
    singles = [t for t in w.index if universe.loc[t, "asset_class"] == "equity"]
    thin = [t for t in singles if dollar_volume is not None and dollar_volume.get(t, np.inf) < MIN_DOLLAR_VOLUME]
    crypto = float(w[groups == "crypto"].sum())
    illiquid = float(w[thin].sum()) + crypto
    items.append(RiskItem("liquidity", _level(illiquid, *THRESHOLDS["liquidity_illiquid_share"]), illiquid,
                          "share in thinly traded assets or crypto",
                          "Selling quickly at a fair price can be hard for thinly traded assets; crypto trades "
                          "every day but its price can gap." + (f" Thinly traded: {', '.join(thin)}." if thin else "")))

    ccy = exposure(w.to_dict(), universe, "currency")
    foreign = float(ccy.drop("CAD", errors="ignore").sum())
    items.append(RiskItem("currency", _level(foreign, *THRESHOLDS["currency_foreign_share"]), foreign,
                          "share listed in a foreign currency",
                          f"{foreign:.0%} is in USD: a stronger Canadian dollar lowers its value in CAD, a weaker one raises it."))

    rd = risk_decomposition(w.to_dict(), cov) if len(w) > 1 else pd.DataFrame({"risk_share": [1.0]}, index=w.index)
    single = rd.loc[[t for t in rd.index if universe.loc[t, "asset_class"] in {"equity", "crypto"}]]
    if len(single):
        top, share = single["risk_share"].idxmax(), float(single["risk_share"].max())
        reason = (f"{top} alone carries {share:.0%} of the portfolio's risk; effective number of positions "
                  f"{stats['effective_positions']:.1f}.")
    else:
        top, share = None, 0.0
        reason = ("No single company or crypto asset: risk is carried by broad funds that are diversified inside "
                  f"(largest: {rd['risk_share'].idxmax()} with {rd['risk_share'].max():.0%} of the risk).")
    items.append(RiskItem("concentration", _level(share, *THRESHOLDS["concentration_top_risk"]), share,
                          "largest single-company or crypto contribution to total risk", reason))

    if expected_nominal is not None:
        real = (1 + expected_nominal) / (1 + inflation) - 1
        items.append(RiskItem("inflation", _level(real, *THRESHOLDS["inflation_real_return"], reverse=True), real,
                              "assumed real return (planning assumption minus inflation)",
                              f"After {inflation:.1%} inflation, the planning assumption leaves about {real:.1%} a year "
                              "of purchasing power growth (a hypothesis, not a forecast)."))
    return items


def average_dollar_volume(prices_local: pd.DataFrame, volume: pd.DataFrame, days: int = 252) -> pd.Series:
    """Average daily traded value over the last year, in listing currency."""
    dv = (prices_local * volume).iloc[-days:]
    return dv.mean()
