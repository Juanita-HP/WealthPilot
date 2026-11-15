"""Devil's advocate: challenges a request, or our own recommendation, with evidence.

Every challenge is produced by a deterministic rule on computed numbers; the
language model only phrases it. Each challenge carries:

* the bias or risk it points to, in plain words
* the evidence (numbers, dates, data source)
* the COUNTERPOINT: what speaks for the request. If the data shows the request
  would have paid off, the advocate says so instead of hiding it
* a question for the investor

It applies the same rules to WealthPilot's own allocations, so the system
critiques itself too.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from . import metrics as m
from .exposure import alerts, exposure
from .portfolio import backtest
from .profile import QUESTION_BY_ID, InvestorProfile, check_allocation

HOME_SHARE_ALERT = 0.70          # share of stocks listed in Canada
CANADA_WORLD_WEIGHT = "about 3%"  # Canada's approximate weight in global equity indexes (e.g. MSCI ACWI)


@dataclass
class Challenge:
    code: str
    bias: str
    severity: str  # info | warning
    claim: str
    evidence: dict
    counterpoint: str | None
    question: str

    def to_dict(self):
        return asdict(self)


@dataclass
class Review:
    subject: str
    challenges: list[Challenge]
    before_after: dict | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if any(c.severity == "warning" for c in self.challenges):
            return "reconsider"
        return "no major objection" if not self.challenges else "proceed with care"

    def to_dict(self):
        d = asdict(self)
        d["verdict"] = self.verdict
        return d


def _metrics(prices, weights, start=None):
    res = backtest(prices, weights, start=start, rebalance="quarterly", transaction_cost=0.001)
    met = m.calculate_all(res.values)
    return {"cagr": met.cagr, "volatility": met.annualized_volatility, "max_drawdown": met.max_drawdown,
            "sharpe": met.sharpe_ratio, "start": met.start, "end": met.end}


def recency_evidence(prices: pd.DataFrame) -> dict:
    """Does last year's ranking of assets predict next year's? Rank correlation across the universe."""
    yearly = prices.resample("YE").last().pct_change().dropna(how="all")
    pairs = []
    for (y0, r0), (y1, r1) in zip(yearly.iloc[:-1].iterrows(), yearly.iloc[1:].iterrows()):
        both = pd.concat([r0, r1], axis=1).dropna()
        if len(both) >= 10:
            pairs.append({"from": y0.year, "to": y1.year,
                          "rank_correlation": float(both.iloc[:, 0].rank().corr(both.iloc[:, 1].rank()))})
    return {"pairs": pairs, "mean": float(np.mean([p["rank_correlation"] for p in pairs])) if pairs else None,
            "assets": int(prices.shape[1])}


def review_allocation(proposed: dict[str, float], profile: InvestorProfile, prices: pd.DataFrame,
                      universe: pd.DataFrame, current: dict[str, float] | None = None,
                      subject: str = "proposed allocation") -> Review:
    challenges: list[Challenge] = []
    window = f"{prices.index[0].date()} to {prices.index[-1].date()}"

    # 1. Constraints from the profile
    for v in check_allocation(proposed, profile, universe, prices):
        if v.severity != "warning":
            continue
        challenges.append(Challenge(
            v.code, "profile mismatch", "warning", v.message,
            {"value": v.value, "limit": v.limit, "profile_level": profile.level, "level_name": profile.level_name},
            None, "Do you want to change the request, or revisit your profile answers?"))

    # 2. Hidden concentration: assets that move together
    for a in alerts(proposed, universe, prices):
        if a.code == "CORRELATED_PAIR":
            challenges.append(Challenge(
                "HIDDEN_CONCENTRATION", "illusion of diversification", "info", a.message,
                {"pair": a.subject, "weekly_correlation": a.value, "window": window}, None,
                "Is holding both a deliberate tilt, or did you expect them to diversify each other?"))

    # 3. Home bias
    eq = {t: w for t, w in proposed.items() if universe.loc[t, "asset_class"] in {"equity", "etf_equity"}}
    if eq:
        home = exposure(eq, universe, "currency").get("CAD", 0.0) / sum(eq.values())
        if home > HOME_SHARE_ALERT and profile.preferences.region != "canada":
            challenges.append(Challenge(
                "HOME_BIAS", "home bias", "info",
                f"{home:.0%} of the stocks are Canadian, while Canada is {CANADA_WORLD_WEIGHT} of world stock markets.",
                {"canadian_share_of_stocks": home, "source": "approximate MSCI ACWI country weight"},
                "Canadian stocks avoid currency risk and have tax advantages for Canadian dividends.",
                "Is the Canadian focus a choice, or a default?"))

    # 4. Before / after: what the change would have done historically (the honest counterpoint)
    before_after = None
    if current:
        start = prices[list(set(current) | set(proposed))].dropna().index[0]
        b, a = _metrics(prices, current, start), _metrics(prices, proposed, start)
        before_after = {"before": b, "after": a, "kind": "historical", "window": f"{b['start']} to {b['end']}"}
        risk_up = a["max_drawdown"] > b["max_drawdown"] * 1.5 and a["max_drawdown"] - b["max_drawdown"] > 0.05
        ret_up = a["cagr"] > b["cagr"]
        if risk_up:
            counter = (f"Historically the change would have RAISED the annual return from {b['cagr']:.1%} to "
                       f"{a['cagr']:.1%}." if ret_up else
                       f"It would not have raised the return either ({b['cagr']:.1%} before, {a['cagr']:.1%} after).")
            challenges.append(Challenge(
                "RISK_JUMP", "risk underestimated", "warning",
                f"The worst fall would have gone from {b['max_drawdown']:.1%} to {a['max_drawdown']:.1%} "
                f"(volatility {b['volatility']:.1%} to {a['volatility']:.1%}).",
                {**before_after}, counter + " Past returns do not tell which way the next five years go.",
                f"With a horizon of '{QUESTION_BY_ID['horizon'].option(profile.answers['horizon']).label.lower()}' "
                f"and an accepted loss of "
                f"{profile.constraints.worst_year_accepted:.0%} in a bad year, is the extra risk worth it?"))
    return Review(subject, challenges, before_after)


# Index funds of the universe and the stocks of the universe they hold (index membership, November 2026).
INDEX_MEMBERS = {
    "SPY": {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "JPM", "JNJ", "PG", "XOM"},
    "ESGV": {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA", "JPM", "JNJ", "PG"},     # screened: no oil producers
    "QQQ": {"AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "TSLA"},
    "XIU.TO": {"RY.TO", "TD.TO", "MFC.TO", "ENB.TO", "CNQ.TO", "CNR.TO", "FTS.TO", "ATD.TO", "SHOP.TO", "CSU.TO"},
}


def already_owned_challenge(ticker: str, current: dict[str, float], universe: pd.DataFrame) -> Challenge | None:
    """A single stock the investor already owns through the index funds of the plan."""
    funds = [f for f, members in INDEX_MEMBERS.items() if ticker in members and current.get(f, 0) > 0]
    if not funds:
        return None
    names = " and ".join(f"{f} ({universe.loc[f, 'name']})" if f in universe.index else f for f in funds)
    share = sum(current[f] for f in funds)
    return Challenge(
        "ALREADY_OWNED", "overlap with your index funds", "info",
        f"You already own {ticker} through {names}, {share:.0%} of your plan: these index funds hold it, along with "
        f"many other companies. Buying it directly adds to a position you already have.",
        {"funds": funds, "funds_share": share},
        "A direct position is a deliberate bet on one company; the index funds already give you its market weight.",
        f"Do you want more {ticker} than the market already gives you?")


def _about_this_trade(c: Challenge, ticker: str, current: dict[str, float], profile: InvestorProfile,
                      prices: pd.DataFrame, universe: pd.DataFrame) -> bool:
    """Keep a portfolio-level challenge only if this trade causes it or is part of it.

    Without this filter, every review repeated remarks about the plan itself (for example two funds of the plan that
    move together), whatever the stock the investor asked about.
    """
    if ticker in c.claim:
        return True
    if c.code == "HIDDEN_CONCENTRATION":
        return False                                    # a pair that does not involve this asset
    if c.code == "HOME_BIAS":
        return universe.loc[ticker, "currency"] == "CAD" and universe.loc[ticker, "asset_class"] in {"equity", "etf_equity"}
    if c.code == "RISK_JUMP":
        return True                                     # computed before vs after this trade
    before = {v.code for v in check_allocation(current, profile, universe, prices) if v.severity == "warning"}
    return c.code not in before                        # a limit this trade breaks, not one the plan already breaks


# Share of headlines that are forecasts/opinions from low-trust sources. At 0.5 the challenge never fired for
# NVDA (0.40), SPY (0.45) or TSLA (0.31) while it did for PG (0.54): 0.30 catches the stocks in the spotlight.
HYPE_SHARE = 0.30
HYPE_MIN_HEADLINES = 4


def review_trade(ticker: str, weight: float, current: dict[str, float], profile: InvestorProfile,
                 prices: pd.DataFrame, universe: pd.DataFrame, risk: dict | None = None,
                 news_digest: dict | None = None, macro_items: list[dict] | None = None) -> Review:
    """Challenge a request to put ``weight`` of the portfolio in ``ticker``.

    ``macro_items``: recent official news (``macro_news.recent``). If the trade makes the portfolio depend much
    more on a factor that is in the news right now, the challenge shows it.
    """
    if ticker not in universe.index:
        raise KeyError(f"{ticker} is not in the asset universe")
    proposed = {t: w * (1 - weight) for t, w in current.items() if t != ticker}
    proposed[ticker] = weight + current.get(ticker, 0.0) * (1 - weight)
    rv = review_allocation(proposed, profile, prices, universe, current, subject=f"{weight:.0%} in {ticker}")
    rv.challenges = [c for c in rv.challenges if _about_this_trade(c, ticker, current, profile, prices, universe)]
    in_plan = current.get(ticker, 0.0) > 0
    owned = already_owned_challenge(ticker, current, universe)
    if owned:
        rv.challenges.append(owned)
    asset_class = universe.loc[ticker, "asset_class"]

    s = prices[ticker].dropna()
    one_year = float(s.iloc[-1] / s.loc[: s.index[-1] - pd.DateOffset(years=1)].iloc[-1] - 1)
    ep = m.drawdown_episode(s)
    rec = recency_evidence(prices)
    if one_year > 0.30 and rec["mean"] is not None:
        rv.challenges.append(Challenge(
            "RECENCY_BIAS", "recency bias", "info",
            f"{ticker} gained {one_year:.0%} over the last 12 months. In this dataset, last year's ranking of the "
            f"{rec['assets']} assets had an average rank correlation of {rec['mean']:.2f} with the next year's.",
            {"one_year_return": one_year, "rank_correlation_by_year": rec["pairs"]},
            "Momentum effects exist in research over some horizons; one asset's past year is still weak evidence.",
            "Would you want this position if it had been flat last year?"))
    horizon_years = {"lt3": 2, "3to5": 4, "5to10": 7.5, "10to15": 12.5, "gt15": 20}[profile.answers["horizon"]]
    recovered = ep["recovery_date"]
    days = ((recovered or s.index[-1]) - ep["peak_date"]).days
    if days / 365.25 > horizon_years / 2:
        # A holding the plan already chose for this horizon is balanced by the rest of the plan: a note, not a warning.
        rv.challenges.append(Challenge(
            "HORIZON_MISMATCH", "horizon mismatch", "info" if in_plan else "warning",
            ("Already part of your plan, which balances it with other holdings. " if in_plan else "")
            + f"{ticker} fell {-ep['drawdown']:.0%} from {ep['peak_date'].date()} and took "
            + (f"{days / 365.25:.1f} years to recover" if recovered is not None else
               f"{days / 365.25:.1f} years without recovering")
            + f", against a horizon of about {horizon_years:g} years.",
            {"peak": str(ep["peak_date"].date()), "trough": str(ep["trough_date"].date()),
             "recovery": str(recovered.date()) if recovered is not None else None, "drawdown": ep["drawdown"]},
            None, "If it happened again just before you need the money, what would you do?"))
    if news_digest and news_digest.get("n", 0) >= HYPE_MIN_HEADLINES and news_digest["hype_share"] >= HYPE_SHARE:
        rv.challenges.append(Challenge(
            "HYPE", "media hype", "info",
            f"{news_digest['hype_share']:.0%} of the {news_digest['n']} recent headlines about {ticker} are forecasts or "
            f"opinions from low-trust sources ({news_digest['window']}).",
            {"share_predictive": news_digest["share_predictive"], "share_low_trust": news_digest["share_low_trust"],
             "examples": news_digest.get("top_predictive", [])[:3], "classifier": news_digest.get("classifier")},
            "Attention is not evidence either way: popular stocks can keep rising. Facts from high-trust sources are "
            "listed separately: " + "; ".join(h["title"] for h in news_digest.get("top_descriptive", [])[:2]),
            "Is the interest in this stock coming from its results, or from what people say about it?"))
    esg = esg_controversy_challenge(profile, news_digest, universe)
    if esg:
        rv.challenges.append(esg)
    # Recent news and swings matter for single companies and crypto; for a diversified fund, reacting to them would be
    # market timing, which the plan advises against.
    recent = (recent_news_challenge(ticker, profile, prices, news_digest)
              if asset_class in {"equity", "crypto"} else None)
    if recent:
        rv.challenges.append(recent)
    news_exp = news_exposure_change(current, proposed, universe, macro_items or [])
    if news_exp:
        rv.challenges.append(Challenge(
            "NEWS_EXPOSURE", "concentration on a current news factor",
            "warning" if news_exp["after"] >= 0.5 and profile.level <= 3 else "info",
            f"With this change, the share of your portfolio directly exposed to {news_exp['factor_label'].lower()} "
            f"goes from {news_exp['before'] * 100:.0f}% to {news_exp['after'] * 100:.0f}%. This factor is in the news: "
            f"{news_exp['fact']}",
            news_exp,
            "News do not say which way markets will move; they say what will move your money. The larger the exposed "
            "share, the more the next announcement of the same kind will matter.",
            "Do you want the next announcement on this topic to affect this much of your money?"))
    return rv


def esg_controversy_challenge(profile: InvestorProfile, news_digest: dict | None,
                              universe: pd.DataFrame | None = None) -> Challenge | None:
    """External evidence for investors with ESG or values preferences: ESG or legal/regulatory headlines."""
    prefs = profile.preferences
    if not news_digest or (prefs.esg == "none" and not prefs.values):
        return None
    items = news_digest.get("controversies") or []
    count = len(items) or news_digest.get("by_category", {}).get("esg_controversy", 0)
    if not count:
        return None
    cats = news_digest.get("by_category", {})
    total = max(count, cats.get("esg_controversy", 0) + cats.get("legal_regulatory", 0))
    first = items[0] if items else None
    claim = (f"{total} of the {news_digest.get('n', total)} recent headlines are about ESG or regulatory issues"
             + (f", for example \"{first['title']}\" ({first['publisher']}, {first['published_at'][:10]})." if first else "."))
    screened = universe is not None and "ESGV" in universe.index
    return Challenge(
        "ESG_CONTROVERSY", "ESG & controversy signal", "warning" if prefs.esg == "exclude" else "info", claim,
        {"controversies": items, "by_category": cats, "esg_preference": prefs.esg, "values": list(prefs.values)},
        "Headlines are not an ESG audit: they show what is being reported, not the company's full record, and "
        "public data has gaps. " + ("A screened fund (ESGV, U.S. stocks) is available in this simulation for "
                                     "investors who prefer a provider's ESG rules." if screened else
                                     "No ESG-screened fund is available in this universe."),
        "Does this recent coverage align with your ESG and values preferences?")


MATERIAL = {"management", "legal_regulatory", "earnings", "deal", "esg_controversy"}
TRUSTED = 0.6          # wire services, major papers and established media
UNSETTLED = 1.5        # last 10 trading days' volatility vs the past year's
LEVEL_NAME = {1: "Conservative", 2: "Moderate", 3: "Balanced", 4: "Growth", 5: "Aggressive"}


def recent_news_challenge(ticker: str, profile: InvestorProfile, prices: pd.DataFrame,
                          news_digest: dict | None) -> Challenge | None:
    """A warning about what is happening around the asset now, stronger for cautious profiles.

    Two signals, both shown: material facts reported by trusted sources (leadership, legal, results, deals,
    controversies) and how much more the price has moved over the last 10 trading days than over the past year.
    News never say which way the price will go, so the warning is about uncertainty, and comes with its limits.
    """
    facts = []
    if news_digest and news_digest.get("n", 0) > 0:
        facts = [h for h in news_digest.get("top_descriptive", [])
                 if h.get("trust", 0) >= TRUSTED and h.get("category") in MATERIAL and h.get("importance", 0) >= 3]
    ratio = None
    if ticker in prices:
        r = prices[ticker].dropna().pct_change().dropna()
        if len(r) > 260:
            recent_vol, year_vol = float(r.iloc[-10:].std()), float(r.iloc[-260:].std())
            ratio = recent_vol / year_vol if year_vol > 0 else None
    unsettled = ratio is not None and ratio >= UNSETTLED
    if not facts and not unsettled:
        return None
    level = profile.level
    parts = []
    if facts:
        parts.append("Recent facts reported by trusted sources: " + "; ".join(
            f"\"{h['title']}\" ({h['publisher']}, {h['published_at'][:10]})" for h in facts[:2]) + ".")
    if ratio is not None:
        parts.append(f"Over the last 10 trading days its price moved {ratio:.1f} times as much as over the past year"
                     + (" (more unsettled than usual)." if unsettled else " (no unusual swings so far)."))
    if level <= 2:
        severity = "warning"
        advice = (f"For a {LEVEL_NAME[level]} profile, this kind of uncertainty is what the plan tries to avoid: if you go "
                  "ahead, keep the position very small, so that a bad surprise stays a small loss.")
    elif level == 3:
        severity = "info"
        advice = (f"For a {LEVEL_NAME[level]} profile, it is worth reading the original sources before acting and "
                  "keeping the position within your single-holding limit.")
    else:
        severity = "info"
        advice = (f"A {LEVEL_NAME[level]} profile can absorb this kind of swing; size the position knowingly.")
    return Challenge(
        "RECENT_NEWS", "acting on recent news", severity, " ".join(parts) + " " + advice,
        {"facts": facts[:3], "volatility_ratio_10d_vs_1y": ratio, "level": level,
         "classifier": (news_digest or {}).get("classifier")},
        "These are headlines (their full text could not be read), news do not tell "
        "which way the price will go, and markets often price them in within hours.",
        "If the news turn out worse than they look today, would you still want this position?")


NEWS_EXPOSURE_JUMP = 0.10   # +10 points of the portfolio directly exposed to a factor in the news


def news_exposure_change(current: dict[str, float], proposed: dict[str, float], universe: pd.DataFrame,
                         macro_items: list[dict]) -> dict | None:
    """Largest rise in direct exposure to a factor that recent official news are about."""
    from . import macro_news as mn
    best = None
    for it in mn._dedupe(macro_items):
        a = it["analysis"]
        if a["importance"] < 3 or not a["main_factors"]:
            continue
        f = a["main_factors"][0]
        before = mn.exposure(current, universe, f, it["region"])["share_direct"]
        after = mn.exposure(proposed, universe, f, it["region"])["share_direct"]
        if after - before >= NEWS_EXPOSURE_JUMP and (best is None or after - before > best["after"] - best["before"]):
            best = {"factor": f, "factor_label": mn.FACTOR_LABEL[f], "region": it["region"], "before": before,
                    "after": after, "fact": mn.fact(it), "source": it["publisher"], "date": it["published_at"][:10],
                    "link": it["link"]}
    return best


def review_lab(result) -> Review:
    """Turn strategy-lab findings into challenges."""
    rv = Review(f"{result.strategy} on {result.ticker}", [])
    for f in result.findings:
        if f["code"] in {"OVERFITTING_SIGN", "LOSES_TO_BUY_HOLD_OOS", "NO_POSITION_OOS", "TOO_FEW_TRADES"}:
            rv.challenges.append(Challenge(
                f["code"], "overfitting" if f["code"] == "OVERFITTING_SIGN" else "weak evidence",
                f["severity"], f["message"],
                {"in_sample": result.in_sample, "out_of_sample": result.out_of_sample,
                 "buy_hold_out_of_sample": result.buy_hold_out_of_sample,
                 "combinations_tested": result.combinations_tested, "split_date": result.split_date},
                "A rule that is simple and set before looking at the data deserves more trust than an optimized one.",
                "Would you still use this rule if you had chosen its settings before seeing these prices?"))
    return rv
