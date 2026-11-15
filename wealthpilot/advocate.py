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


HYPE_SHARE = 0.5   # share of headlines that are forecasts/opinions from low-trust sources
HYPE_MIN_HEADLINES = 5


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
        rv.challenges.append(Challenge(
            "HORIZON_MISMATCH", "horizon mismatch", "warning",
            f"{ticker} fell {-ep['drawdown']:.0%} from {ep['peak_date'].date()} and took "
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
    news_exp = news_exposure_change(current, proposed, universe, macro_items or [])
    if news_exp:
        rv.challenges.append(Challenge(
            "NEWS_EXPOSURE", "concentration on a current news factor", "warning" if news_exp["after"] >= 0.5 else "info",
            f"Avec ce changement, la part de votre portefeuille directement exposée au facteur "
            f"« {news_exp['factor_fr']} » passe de {news_exp['before'] * 100:.0f} % à {news_exp['after'] * 100:.0f} %. "
            f"Ce facteur est dans l'actualité : {news_exp['fact']}",
            news_exp,
            "Une nouvelle ne dit pas dans quel sens le marché va bouger; elle dit seulement ce qui va faire bouger "
            "votre argent. Plus la part exposée est grande, plus la prochaine nouvelle du même type comptera.",
            "Voulez-vous que la prochaine annonce sur ce sujet touche autant de votre argent ?"))
    return rv


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
            best = {"factor": f, "factor_fr": mn.FACTOR_FR[f], "region": it["region"], "before": before,
                    "after": after, "fact": mn.fact_fr(it), "source": it["publisher"], "date": it["published_at"][:10],
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
