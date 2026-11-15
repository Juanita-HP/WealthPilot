"""Strategist: a policy allocation built from the investor profile, with a reason for every weight.

Method: rule-based strategic asset allocation on broad index ETFs ("core"), set
inside the profile's constraints. Each step is a written rule, so the result
can be explained line by line and reproduced by hand.

Why rules and not a mean-variance optimizer? With five years of data, expected
returns and covariances are estimated with large error, and optimizers amplify
that error (DeMiguel, Garlappi & Uppal, 2009, "Optimal Versus Naive
Diversification", Review of Financial Studies). ``validation.py`` checks this
choice out of sample against an inverse-volatility variant estimated on past
data only.

Why index ETFs as the core? Lower fees and no single-company risk; individual
stocks can be added as small "satellite" positions, judged with the ticker
fit score and the profile limits.

Statistics quoted in the reasons are computed from the price data passed in,
never typed by hand.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from .profile import InvestorProfile

BLOCKS = {
    "canadian_equity": "XIU.TO",
    "us_equity": "SPY",
    "us_equity_esg": "ESGV",
    "us_growth": "QQQ",
    "canadian_bonds": "XBB.TO",
    "us_bonds": "AGG",
    "cash": "ZST.TO",
    "gold": "GLD",
    "crypto": "BTC-USD",
}

# Share of the defensive sleeve kept in ultra short-term bonds (cash-like), by level.
CASH_SHARE = {1: 0.50, 2: 0.35, 3: 0.20, 4: 0.10, 5: 0.00}
GOLD_WEIGHT = {1: 0.00, 2: 0.05, 3: 0.05, 4: 0.05, 5: 0.05}
CANADIAN_BOND_SHARE = 0.75    # AGG adds USD currency risk to the safe sleeve
GROWTH_TILT_MAX = 1 / 3       # at most a third of the U.S. sleeve in QQQ
CRYPTO_STRATEGIC_SHARE = 0.5  # use half of the crypto limit, never all of it

# Themes the investor can pick. Each maps to assets of the universe. Themes never replace the
# diversified core: they become small "satellite" positions taken from the stock sleeve, within the
# single-security limit, the sector limit and the investor's exclusions.
THEMES = {
    "tech_ai": ("Technology and AI", ["QQQ"]),
    "canadian_banks": ("Canadian banks", ["RY.TO", "TD.TO"]),
    "dividends": ("Dividends and income", ["FTS.TO", "ENB.TO", "JNJ", "PG"]),
    "energy": ("Energy and resources", ["CNQ.TO", "XOM", "ENB.TO"]),
    "health": ("Health care", ["JNJ"]),
    "consumer": ("Consumer staples", ["PG", "ATD.TO"]),
    "ecommerce": ("E-commerce", ["AMZN", "SHOP.TO"]),
    "software_ca": ("Canadian software", ["CSU.TO", "SHOP.TO"]),
    "megacap_tech": ("U.S. tech giants", ["MSFT", "AAPL", "GOOGL", "NVDA"]),
    "ev_mobility": ("Electric vehicles", ["TSLA"]),
    "infrastructure": ("Infrastructure and transport", ["CNR.TO", "FTS.TO"]),
    "insurance": ("Insurance", ["MFC.TO"]),
    "gold": ("Gold and safe havens", ["GLD"]),
    "crypto": ("Crypto assets", ["BTC-USD"]),
    "esg": ("Responsible investing (ESG)", ["ESGV"]),
}
THEME_ALIASES = {"Information Technology": "tech_ai"}
SATELLITE_SHARE = {1: 0.0, 2: 0.05, 3: 0.10, 4: 0.15, 5: 0.20}  # of the stock sleeve
SATELLITES_PER_THEME = 2
MIN_SATELLITE = 0.01  # a position under 1% adds noise, not exposure


def normalize_themes(themes) -> list[str]:
    return list(dict.fromkeys(THEME_ALIASES.get(t, t) for t in themes if THEME_ALIASES.get(t, t) in THEMES))


@dataclass
class Line:
    ticker: str
    weight: float
    block: str
    reason: str


@dataclass
class Allocation:
    weights: dict[str, float]
    lines: list[Line]
    method: str
    notes: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def evidence(prices: pd.DataFrame | None) -> dict:
    """Statistics quoted in the reasons, computed from the price data (weekly returns, CAD)."""
    if prices is None or prices.empty:
        return {}
    wk = prices.resample("W-FRI").last().pct_change()

    def corr(a, b):
        return float(wk[[a, b]].dropna().corr().iloc[0, 1])

    def mdd(t):
        s = prices[t].dropna()
        return float((s / s.cummax() - 1).min())

    return {
        "window": f"{prices.index[0].date()} to {prices.index[-1].date()}",
        "corr_spy_qqq": corr("SPY", "QQQ"), "corr_spy_esgv": corr("SPY", "ESGV"),
        "corr_xbb_agg": corr("XBB.TO", "AGG"), "corr_gld_spy": corr("GLD", "SPY"),
        "corr_btc_eth": corr("BTC-USD", "ETH-USD"),
        "mdd_zst": mdd("ZST.TO"), "mdd_btc": mdd("BTC-USD"), "mdd_eth": mdd("ETH-USD"),
    }


def _q(ev: dict, key: str, text: str) -> str:
    """A computed statistic for a reason, or nothing when no data was given."""
    return f" {text.format(ev[key])} ({ev['window']})." if key in ev else ""


def policy_allocation(profile: InvestorProfile, prices: pd.DataFrame | None = None,
                      equity_position: float = 0.5) -> Allocation:
    """Policy portfolio for a profile.

    ``equity_position`` places the stock share inside the level's range
    (0 = minimum, 1 = maximum, 0.5 = midpoint).
    """
    if not 0 <= equity_position <= 1:
        raise ValueError("equity_position must be between 0 and 1")
    ev = evidence(prices)
    c = profile.constraints
    p = profile.preferences
    lines: list[Line] = []
    notes: list[str] = []

    equity = c.equity_min + equity_position * (c.equity_max - c.equity_min)
    crypto = round(c.max_crypto * CRYPTO_STRATEGIC_SHARE, 6)
    gold = min(GOLD_WEIGHT[profile.level], c.max_gold)
    defensive = 1.0 - equity - crypto - gold

    # Equity sleeve
    ca = equity * c.home_equity_share
    us = equity - ca
    lines.append(Line(BLOCKS["canadian_equity"], ca, "canadian_equity",
                      f"Canadian stocks: {c.home_equity_share:.0%} of the {equity:.0%} stock share "
                      f"(region preference '{p.region}'; level {profile.level} allows "
                      f"{c.equity_min:.0%} to {c.equity_max:.0%} in stocks)."))
    esg = p.esg in {"prefer", "exclude"}
    tilt = 0.0
    themes = normalize_themes(p.themes)
    if "tech_ai" in themes and profile.level >= 4 and not esg:
        tilt = us * GROWTH_TILT_MAX
        lines.append(Line(BLOCKS["us_growth"], tilt, "us_growth",
                          "Technology interest: a third of the U.S. sleeve in the Nasdaq-100; a tilt, not extra "
                          "diversification." + _q(ev, "corr_spy_qqq", "Weekly correlation QQQ/SPY {:.2f}")))
    if esg:
        lines.append(Line(BLOCKS["us_equity_esg"], us - tilt, "us_equity",
                          "U.S. stocks through an ESG-screened fund (ESGV) for the ESG preference."
                          + _q(ev, "corr_spy_esgv", "Weekly correlation ESGV/SPY {:.2f}")))
        notes.append("ESGV is screened by its provider's rules; WealthPilot does not check its holdings.")
    else:
        lines.append(Line(BLOCKS["us_equity"], us - tilt, "us_equity", "U.S. stocks through the S&P 500."))

    # Defensive sleeve
    cash = defensive * CASH_SHARE[profile.level]
    bonds = defensive - cash
    if cash > 0:
        lines.append(Line(BLOCKS["cash"], cash, "cash",
                          f"Ultra short-term bonds (cash-like): {CASH_SHARE[profile.level]:.0%} of the safe sleeve "
                          f"at level {profile.level}." + _q(ev, "mdd_zst", "Worst drop {:.1%}")))
    lines.append(Line(BLOCKS["canadian_bonds"], bonds * CANADIAN_BOND_SHARE, "canadian_bonds",
                      "Canadian bonds: most of the bond sleeve, in CAD, so the safe part carries no currency risk."))
    lines.append(Line(BLOCKS["us_bonds"], bonds * (1 - CANADIAN_BOND_SHARE), "us_bonds",
                      "U.S. bonds: a quarter of the bond sleeve, for a second interest-rate market."
                      + _q(ev, "corr_xbb_agg", "Weekly correlation with Canadian bonds {:.2f}")))
    if gold > 0:
        lines.append(Line(BLOCKS["gold"], gold, "gold",
                          "Gold: 5% diversifier; no long-term return assumption is used for gold."
                          + _q(ev, "corr_gld_spy", "Weekly correlation with the S&P 500 {:.2f}")))
    if crypto > 0:
        lines.append(Line(BLOCKS["crypto"], crypto, "crypto",
                          f"Bitcoin: half of the {c.max_crypto:.0%} crypto limit. Ether is left out because it adds "
                          "little diversification." + _q(ev, "corr_btc_eth", "Weekly correlation BTC/ETH {:.2f}")))

    lines, theme_notes = _theme_satellites(lines, themes, profile, ev)
    notes += theme_notes

    if p.simplicity:
        # Fewer, simpler holdings: fold U.S. bonds into Canadian bonds, drop gold and the growth tilt.
        merged: list[Line] = []
        extra_bonds = sum(ln.weight for ln in lines if ln.block in {"us_bonds", "gold"})
        extra_us = sum(ln.weight for ln in lines if ln.block == "us_growth")
        for ln in lines:
            if ln.block in {"us_bonds", "gold", "us_growth"}:
                continue
            if ln.block == "canadian_bonds":
                ln = Line(ln.ticker, ln.weight + extra_bonds, ln.block,
                          ln.reason + " Simplicity preference: also holds the U.S. bond and gold shares.")
            if ln.block == "us_equity" and extra_us:
                ln = Line(ln.ticker, ln.weight + extra_us, ln.block, ln.reason)
            merged.append(ln)
        lines = merged
        notes.append("Simplicity preference: three or four funds instead of six or seven, with slightly less "
                     "diversification across bond markets.")

    weights: dict[str, float] = {}
    for ln in lines:
        weights[ln.ticker] = weights.get(ln.ticker, 0.0) + ln.weight
    weights = {k: v for k, v in weights.items() if v > 1e-9}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}  # removes floating-point drift only
    return Allocation(weights, lines, "policy rules v1", notes, ev)


def _theme_satellites(lines: list[Line], themes: list[str], profile: InvestorProfile, ev: dict):
    """Turn picked themes into small satellite positions funded from the core stock lines."""
    from .data import load_universe

    c = profile.constraints
    notes: list[str] = []
    skip = {"tech_ai", "esg", "crypto", "gold"}  # handled by the core rules (QQQ tilt, ESGV, crypto, gold lines)
    picks = [t for t in themes if t not in skip]
    if "esg" in themes and profile.preferences.esg == "none":
        notes.append("ESG theme noted: set the ESG preference to use the screened fund for U.S. stocks.")
    if not picks:
        return lines, notes
    core = [ln for ln in lines if ln.block in {"canadian_equity", "us_equity"}]
    stock_sleeve = sum(ln.weight for ln in lines if ln.block in {"canadian_equity", "us_equity", "us_growth"})
    budget = stock_sleeve * SATELLITE_SHARE[profile.level]
    if budget <= 0:
        notes.append(f"Themes noted but not added: level {profile.level} keeps the whole stock share in broad funds.")
        return lines, notes
    try:
        universe = load_universe()
    except FileNotFoundError:
        return lines, notes + ["Themes not applied: asset universe not available."]
    candidates: dict[str, list[str]] = {}
    for th in picks:
        ok = [t for t in THEMES[th][1] if t in universe.index and universe.loc[t, "sector"] not in c.excluded_sectors]
        candidates[th] = ok[:SATELLITES_PER_THEME]
    chosen: list[tuple[str, str]] = []
    for rank in range(SATELLITES_PER_THEME):  # round robin: every theme gets its first pick before any second pick
        for th in picks:
            if rank < len(candidates[th]) and candidates[th][rank] not in [x for x, _ in chosen]:
                chosen.append((candidates[th][rank], th))
    if not chosen:
        return lines, notes + ["Themes noted, but every matching asset is excluded by the investor's preferences."]
    max_picks = max(1, int(budget / MIN_SATELLITE))
    if len(chosen) > max_picks:
        notes.append(f"Only {max_picks} theme position(s) fit at level {profile.level}: "
                     f"{', '.join(t for t, _ in chosen[max_picks:])} left out to keep each position at 1% or more.")
        chosen = chosen[:max_picks]
    each = min(budget / len(chosen), c.limits.max_single_security)
    used = each * len(chosen)
    core_total = sum(ln.weight for ln in core)
    out = []
    for ln in lines:
        if ln in core:
            out.append(Line(ln.ticker, ln.weight - used * ln.weight / core_total, ln.block, ln.reason))
        else:
            out.append(ln)
    for t, th in chosen:
        out.append(Line(t, each, "satellite",
                        f"Theme '{THEMES[th][0]}': satellite position of {each:.1%}, funded from the broad stock funds "
                        f"and kept under the {c.limits.max_single_security:.1%} single-holding limit."))
    notes.append(f"Themes use {used:.1%} of the portfolio ({SATELLITE_SHARE[profile.level]:.0%} of the stock share at "
                 f"level {profile.level}); the rest stays in broad index funds.")
    return out, notes


def inverse_vol_allocation(profile: InvestorProfile, prices: pd.DataFrame, end=None,
                           lookback_years: int = 3) -> Allocation:
    """Validation variant: same sleeves and sleeve totals, but weights inside each sleeve set by
    inverse volatility estimated on data available up to ``end`` only (no look-ahead)."""
    window = prices.loc[:end]
    window = window.loc[window.index[-1] - pd.DateOffset(years=lookback_years):]
    base = policy_allocation(profile, window)
    vol = window.resample("W-FRI").last().pct_change().std() * np.sqrt(52)
    sleeves = ({"canadian_equity", "us_equity", "us_growth"}, {"cash", "canadian_bonds", "us_bonds"})
    weights = dict(base.weights)
    for blocks in sleeves:
        tickers = sorted({ln.ticker for ln in base.lines if ln.block in blocks})
        if len(tickers) < 2:
            continue
        total = sum(base.weights[t] for t in tickers)
        inv = 1 / vol[tickers]
        for t in tickers:
            weights[t] = float(total * inv[t] / inv.sum())
    return Allocation(weights, base.lines,
                      f"inverse volatility within sleeves, {lookback_years}y lookback to {window.index[-1].date()}")
