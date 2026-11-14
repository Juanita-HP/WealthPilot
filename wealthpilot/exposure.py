"""Portfolio composition, risk contributions and concentration alerts.

Everything here is a deterministic function of the weights, the asset universe
and historical returns, so every alert can be traced back to a number and a
threshold. Default thresholds live in ``Limits``; the profile module overrides
them per investor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import combinations

import numpy as np
import pandas as pd

SINGLE_SECURITY_CLASSES = {"equity", "crypto"}


@dataclass(frozen=True)
class Limits:
    max_single_security: float = 0.10   # one stock or one crypto asset
    max_sector: float = 0.35            # sector share, individual stocks only
    max_crypto: float = 0.05
    max_currency: float = 0.80          # share of one listing currency
    correlated_pair: float = 0.80       # weekly return correlation
    min_pair_weight: float = 0.03       # ignore tiny positions for the pair check
    max_risk_share: float = 0.35        # one asset's share of total portfolio risk


@dataclass(frozen=True)
class Alert:
    code: str
    severity: str        # "info" | "warning"
    subject: str
    value: float
    threshold: float
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def exposure(weights: dict[str, float], universe: pd.DataFrame, by: str) -> pd.Series:
    """Share of the portfolio by a universe column: currency, sector, asset_class or market."""
    w = pd.Series(weights, dtype=float)
    return w.groupby(universe.loc[w.index, by]).sum().sort_values(ascending=False)


def weekly_returns(prices: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    """Friday-to-Friday returns; weekly data avoids the noise of mismatched holidays."""
    return prices.loc[start:end].resample("W-FRI").last().pct_change().iloc[1:]


def covariance(prices: pd.DataFrame, tickers, start=None, end=None) -> pd.DataFrame:
    """Annualized covariance of weekly returns."""
    return weekly_returns(prices[list(tickers)], start, end).dropna().cov() * 52


def risk_decomposition(weights: dict[str, float], cov: pd.DataFrame) -> pd.DataFrame:
    """Each asset's share of portfolio volatility (Euler decomposition; shares sum to 1)."""
    w = pd.Series(weights, dtype=float)
    c = cov.loc[w.index, w.index]
    port_var = float(w @ c @ w)
    contrib = w * (c @ w) / port_var
    vol = np.sqrt(np.diag(c))
    return pd.DataFrame({
        "weight": w,
        "volatility": vol,
        "risk_share": contrib,
    }).sort_values("risk_share", ascending=False)


def diversification_stats(weights: dict[str, float], cov: pd.DataFrame) -> dict:
    w = pd.Series(weights, dtype=float)
    c = cov.loc[w.index, w.index]
    port_vol = float(np.sqrt(w @ c @ w))
    weighted_vol = float(w @ np.sqrt(np.diag(c)))
    return {
        "portfolio_volatility": port_vol,
        "effective_positions": float(1.0 / (w ** 2).sum()),
        "diversification_ratio": weighted_vol / port_vol,
    }


def alerts(weights: dict[str, float], universe: pd.DataFrame, prices: pd.DataFrame,
           limits: Limits = Limits(), start=None, end=None) -> list[Alert]:
    w = pd.Series(weights, dtype=float)
    w = w[w > 0]
    u = universe.loc[w.index]
    out: list[Alert] = []

    for t in w.index[u["asset_class"].isin(SINGLE_SECURITY_CLASSES)]:
        if w[t] > limits.max_single_security:
            out.append(Alert("SINGLE_SECURITY", "warning", t, w[t], limits.max_single_security,
                             f"{t} is {w[t]:.0%} of the portfolio (limit {limits.max_single_security:.0%})."))

    stocks = w[u["asset_class"] == "equity"]
    for sector, share in stocks.groupby(u.loc[stocks.index, "sector"]).sum().items():
        if share > limits.max_sector:
            out.append(Alert("SECTOR", "warning", sector, share, limits.max_sector,
                             f"Individual {sector} stocks are {share:.0%} of the portfolio (limit {limits.max_sector:.0%})."))

    crypto = float(w[u["asset_class"] == "crypto"].sum())
    if crypto > limits.max_crypto:
        out.append(Alert("CRYPTO", "warning", "crypto", crypto, limits.max_crypto,
                         f"Crypto assets are {crypto:.0%} of the portfolio (limit {limits.max_crypto:.0%})."))

    for ccy, share in exposure(w.to_dict(), universe, "currency").items():
        if share > limits.max_currency:
            out.append(Alert("CURRENCY", "info", ccy, share, limits.max_currency,
                             f"{share:.0%} of the portfolio is listed in {ccy}."))

    big = w[w >= limits.min_pair_weight].index
    if len(big) > 1:
        corr = weekly_returns(prices[list(big)], start, end).corr()
        for a, b in combinations(big, 2):
            if corr.loc[a, b] > limits.correlated_pair:
                out.append(Alert("CORRELATED_PAIR", "info", f"{a}/{b}", float(corr.loc[a, b]), limits.correlated_pair,
                                 f"{a} and {b} moved together (weekly correlation {corr.loc[a, b]:.2f}); "
                                 f"holding both adds less diversification than their weights suggest."))

    if len(w) > 1:
        rd = risk_decomposition(w.to_dict(), covariance(prices, w.index, start, end))
        for t, row in rd.iterrows():
            if row["risk_share"] > limits.max_risk_share and row["risk_share"] > row["weight"] * 1.5:
                out.append(Alert("RISK_CONCENTRATION", "warning", t, float(row["risk_share"]), limits.max_risk_share,
                                 f"{t} is {row['weight']:.0%} of the money but {row['risk_share']:.0%} of the risk."))
    return out
