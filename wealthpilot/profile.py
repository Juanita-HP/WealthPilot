"""Investor profile: questionnaire, scoring, constraints and allocation checks.

Three separate measures, as in financial planning practice:

* risk CAPACITY  - objective: how much loss can the investor absorb without
                   changing their life (horizon, income, emergency fund, share
                   of wealth, dependents)
* risk TOLERANCE - psychological: how much loss can they live with
                   (reaction to a drop, preferred range of outcomes, goal)
* REQUIRED RETURN - what their goal needs, compared with what a risk level can
                   reasonably deliver under published planning assumptions

The risk level is set by the LOWER of capacity and tolerance, and short
horizons cap it. A gap between the two is reported, never silently resolved.
Every score is traceable to the answers that produced it (``reasons``).

Simulation only: the output is an educational profile, not financial advice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from . import assumptions
from .exposure import Limits

# --------------------------------------------------------------------------- questionnaire


@dataclass(frozen=True)
class Option:
    code: str
    label: str
    score: float  # 0 = most cautious, 1 = most risk-taking


@dataclass(frozen=True)
class Question:
    id: str
    dimension: str  # capacity | tolerance | experience | expectation
    text: str
    options: tuple[Option, ...]
    weight: float = 1.0

    def option(self, code: str) -> Option:
        for o in self.options:
            if o.code == code:
                return o
        raise ValueError(f"{self.id}: unknown answer {code!r}; expected one of {[o.code for o in self.options]}")


QUESTIONS: tuple[Question, ...] = (
    Question("horizon", "capacity", "When will you need to withdraw most of this money?", (
        Option("lt3", "In less than 3 years", 0.0),
        Option("3to5", "In 3 to 5 years", 0.25),
        Option("5to10", "In 5 to 10 years", 0.5),
        Option("10to15", "In 10 to 15 years", 0.75),
        Option("gt15", "In more than 15 years", 1.0),
    ), weight=3.0),
    Question("income_stability", "capacity", "How stable is your income?", (
        Option("unstable", "Unstable or no income", 0.0),
        Option("variable", "Variable (commissions, contracts)", 1 / 3),
        Option("stable", "Stable", 2 / 3),
        Option("very_stable", "Very stable, with good prospects", 1.0),
    )),
    Question("emergency_fund", "capacity", "How many months of expenses do you keep aside for emergencies?", (
        Option("none", "None", 0.0),
        Option("lt3", "Less than 3 months", 1 / 3),
        Option("3to6", "3 to 6 months", 2 / 3),
        Option("gt6", "More than 6 months", 1.0),
    )),
    Question("wealth_share", "capacity", "What share of your total savings does this investment represent?", (
        Option("gt75", "More than 75%", 0.0),
        Option("50to75", "50% to 75%", 1 / 3),
        Option("25to50", "25% to 50%", 2 / 3),
        Option("lt25", "Less than 25%", 1.0),
    ), weight=1.5),
    Question("dependents", "capacity", "Do other people depend on your income or savings?", (
        Option("several", "Yes, several people or large commitments", 0.0),
        Option("some", "Yes, some", 0.5),
        Option("none", "No", 1.0),
    )),
    Question("drop_reaction", "tolerance", "Your investments lose 20% in a few months. What do you do?", (
        Option("sell_all", "Sell everything", 0.0),
        Option("sell_some", "Sell part of it", 1 / 3),
        Option("hold", "Wait", 2 / 3),
        Option("buy_more", "Invest more", 1.0),
    ), weight=2.0),
    Question("range_choice", "tolerance", "Which range of one-year results would you accept?", (
        Option("A", "Best year +4%, worst year -2%", 0.0),
        Option("B", "Best year +8%, worst year -8%", 1 / 3),
        Option("C", "Best year +14%, worst year -18%", 2 / 3),
        Option("D", "Best year +22%, worst year -32%", 1.0),
    ), weight=2.0),
    Question("goal", "tolerance", "What is your main objective?", (
        Option("preserve", "Preserve my capital", 0.0),
        Option("income", "Generate regular income", 1 / 3),
        Option("balanced", "Balance growth and stability", 2 / 3),
        Option("max_growth", "Maximize long-term growth", 1.0),
    )),
    Question("experience", "experience", "How would you describe your investment experience?", (
        Option("none", "None", 0.0),
        Option("beginner", "Beginner", 1 / 3),
        Option("intermediate", "Intermediate", 2 / 3),
        Option("advanced", "Advanced", 1.0),
    )),
    Question("return_expectation", "expectation", "What average annual return do you expect?", (
        Option("lt3", "Less than 3%", 0.02),
        Option("3to5", "3% to 5%", 0.04),
        Option("5to7", "5% to 7%", 0.06),
        Option("7to10", "7% to 10%", 0.085),
        Option("gt10", "More than 10%", 0.12),
    )),
)
QUESTION_BY_ID = {q.id: q for q in QUESTIONS}

# Worst one-year loss implied by range_choice, reused by the stress test ("time machine").
WORST_YEAR_ACCEPTED = {"A": 0.02, "B": 0.08, "C": 0.18, "D": 0.32}
HORIZON_LEVEL_CAP = {"lt3": 1, "3to5": 2}
CONFLICT_GAP = 25.0


def questionnaire() -> list[dict]:
    """Serializable questionnaire for the UI."""
    return [{"id": q.id, "dimension": q.dimension, "text": q.text,
             "options": [{"code": o.code, "label": o.label} for o in q.options]} for q in QUESTIONS]


# --------------------------------------------------------------------------- preferences and goal


@dataclass(frozen=True)
class Preferences:
    esg: str = "none"                      # none | prefer | exclude
    excluded_sectors: tuple[str, ...] = ()  # chosen by the investor, e.g. ("Energy",)
    crypto: str = "no"                     # no | small | open
    region: str = "balanced"               # canada | balanced | us | global
    themes: tuple[str, ...] = ()           # e.g. ("Information Technology",)
    simplicity: bool = False               # prefers few, easy-to-understand funds
    values: tuple[str, ...] = ()           # non-financial values, e.g. ("no_fossil_fuels",)


REGION_HOME_SHARE = {"canada": 0.60, "balanced": 0.40, "us": 0.20, "global": 0.30}


@dataclass(frozen=True)
class Goal:
    current_amount: float
    target_amount: float
    years: float
    monthly_contribution: float = 0.0
    target_in_todays_dollars: bool = True


def future_value(amount: float, monthly: float, years: float, annual_return: float) -> float:
    n = round(years * 12)
    i = (1 + annual_return) ** (1 / 12) - 1
    growth = (1 + i) ** n
    annuity = n if abs(i) < 1e-12 else (growth - 1) / i
    return amount * growth + monthly * annuity


def required_return(goal: Goal, inflation: float = assumptions.INFLATION) -> float:
    """Nominal annual return that makes the plan reach the target (bisection)."""
    target = goal.target_amount * ((1 + inflation) ** goal.years if goal.target_in_todays_dollars else 1)
    lo, hi = -0.5, 1.0
    if future_value(goal.current_amount, goal.monthly_contribution, goal.years, hi) < target:
        return float("inf")
    for _ in range(200):
        mid = (lo + hi) / 2
        if future_value(goal.current_amount, goal.monthly_contribution, goal.years, mid) < target:
            lo = mid
        else:
            hi = mid
    return hi


def required_monthly_contribution(goal: Goal, annual_return: float,
                                  inflation: float = assumptions.INFLATION) -> float:
    """Monthly saving needed to reach the target at a given return."""
    target = goal.target_amount * ((1 + inflation) ** goal.years if goal.target_in_todays_dollars else 1)
    gap = target - future_value(goal.current_amount, 0.0, goal.years, annual_return)
    if gap <= 0:
        return 0.0
    return gap / future_value(0.0, 1.0, goal.years, annual_return)


# --------------------------------------------------------------------------- risk levels and constraints


@dataclass(frozen=True)
class Level:
    number: int
    name: str
    equity_min: float
    equity_max: float
    max_crypto: float
    max_single_security: float
    max_sector: float


# Benjamin Graham's rule for the defensive investor keeps stocks between 25% and
# 75%. Levels 2-4 stay inside that band; level 1 goes below it (capital
# preservation, short horizon) and level 5 above it (long horizon, high capacity
# AND tolerance). That extension is a design choice, stated as such.
LEVELS = {
    1: Level(1, "Conservative", 0.15, 0.35, 0.00, 0.05, 0.20),
    2: Level(2, "Moderately conservative", 0.25, 0.50, 0.00, 0.075, 0.25),
    3: Level(3, "Balanced", 0.40, 0.65, 0.02, 0.10, 0.30),
    4: Level(4, "Growth", 0.60, 0.80, 0.05, 0.10, 0.35),
    5: Level(5, "Aggressive", 0.75, 0.95, 0.10, 0.15, 0.40),
}
# Display, in the style of Canadian robo-advisors (Wealthsimple shows a named profile and a score out of 10).
LEVEL_CARDS = {
    1: {"fr": "Prudent", "score_10": 2, "for": "short horizons, little comfort with swings, or money needed soon"},
    2: {"fr": "Modéré", "score_10": 4, "for": "near retirement or medium horizons with a focus on stability"},
    3: {"fr": "Équilibré", "score_10": 6, "for": "medium to long horizons, balance between growth and stability"},
    4: {"fr": "Croissance", "score_10": 8, "for": "long horizons and comfort with sizeable temporary losses"},
    5: {"fr": "Audacieux", "score_10": 10, "for": "very long horizons, high capacity AND high tolerance"},
}


def level_card(level: int) -> dict:
    lv = LEVELS[level]
    return {"level": level, "name": lv.name, **LEVEL_CARDS[level], "stocks": f"{lv.equity_min:.0%}-{lv.equity_max:.0%}",
            "max_crypto": lv.max_crypto, "max_single_security": lv.max_single_security}


MAX_GOLD = 0.10
CRYPTO_SMALL = 0.03
FEE_ASSUMPTION = 0.0025  # broad index ETF portfolio; a stated hypothesis


def level_from_score(score: float) -> int:
    return min(5, int(score // 20) + 1)


def expected_return(level: int, home_share: float) -> dict:
    """Assumed long-term return of a level's mid equity share (planning hypothesis)."""
    lv = LEVELS[level]
    eq = (lv.equity_min + lv.equity_max) / 2
    mix = {"canadian_equity": eq * home_share, "us_equity": eq * (1 - home_share), "fixed_income": 1 - eq}
    gross, _ = assumptions.blended_return(mix)
    return {"equity_share": eq, "gross": gross, "fees": FEE_ASSUMPTION, "net": gross - FEE_ASSUMPTION,
            "source": assumptions.SOURCE["name"]}


@dataclass(frozen=True)
class Constraints:
    equity_min: float
    equity_max: float
    max_crypto: float
    max_gold: float
    excluded_sectors: tuple[str, ...]
    home_equity_share: float
    worst_year_accepted: float
    limits: Limits

    def to_dict(self) -> dict:
        d = asdict(self)
        d["limits"] = asdict(self.limits)
        return d


@dataclass(frozen=True)
class Reason:
    question: str
    answer: str
    label: str
    dimension: str
    contribution: float  # weighted points added to that dimension's score (0-100 scale)


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str  # info | warning
    message: str
    evidence: dict = field(default_factory=dict)


@dataclass
class InvestorProfile:
    answers: dict[str, str]
    preferences: Preferences
    capacity: float
    tolerance: float
    risk_score: float
    level: int
    level_name: str
    experience: str
    constraints: Constraints
    expected: dict
    goal_analysis: dict | None
    reasons: list[Reason]
    flags: list[Flag]
    financials: dict | None = None   # set when the profile comes from the numeric onboarding

    def to_dict(self) -> dict:
        d = asdict(self)
        d["constraints"] = self.constraints.to_dict()
        return d


def _dimension_score(answers: dict[str, str], dimension: str) -> tuple[float, list[Reason]]:
    qs = [q for q in QUESTIONS if q.dimension == dimension]
    total_w = sum(q.weight for q in qs)
    score, reasons = 0.0, []
    for q in qs:
        o = q.option(answers[q.id])
        pts = 100 * q.weight * o.score / total_w
        score += pts
        reasons.append(Reason(q.id, o.code, o.label, dimension, pts))
    return score, reasons


VALUES = {  # non-financial values -> what they exclude in this universe (sector level only)
    "no_fossil_fuels": {"Energy"},
}


def values_exclusions(values) -> set[str]:
    out: set[str] = set()
    for v in values:
        out |= VALUES.get(v, set())
    return out


def constraints_for(level: int, answers: dict[str, str], preferences: Preferences) -> tuple["Constraints", list["Flag"]]:
    """Constraints of a risk level for one investor (preferences applied INSIDE the level's limits)."""
    flags: list[Flag] = []
    lv = LEVELS[level]
    max_crypto = {"no": 0.0, "small": min(CRYPTO_SMALL, lv.max_crypto), "open": lv.max_crypto}[preferences.crypto]
    if max_crypto > 0 and answers["experience"] == "none":
        flags.append(Flag("CRYPTO_NO_EXPERIENCE", "info",
                          "Crypto exposure is set to 0% because the profile reports no investment experience."))
        max_crypto = 0.0
    if preferences.crypto != "no" and lv.max_crypto == 0:
        flags.append(Flag("CRYPTO_NOT_ALLOWED", "info",
                          f"Crypto interest noted, but level {level} ({lv.name}) allows 0% crypto. "
                          "A preference never overrides a constraint."))
    if preferences.esg in {"prefer", "exclude"}:
        flags.append(Flag("ESG_DATA_LIMIT", "info",
                          "ESG preferences are applied through sector exclusions chosen by the investor and "
                          "ESG-screened funds. The dataset has no ESG scores or controversy data; those need "
                          "outside sources."))
    return Constraints(
        equity_min=lv.equity_min, equity_max=lv.equity_max, max_crypto=max_crypto, max_gold=MAX_GOLD,
        excluded_sectors=tuple(sorted(set(preferences.excluded_sectors) | values_exclusions(preferences.values))),
        home_equity_share=REGION_HOME_SHARE[preferences.region],
        worst_year_accepted=WORST_YEAR_ACCEPTED[answers["range_choice"]],
        limits=Limits(max_single_security=lv.max_single_security, max_sector=lv.max_sector, max_crypto=max_crypto),
    ), flags


def with_level(profile: "InvestorProfile", level: int, reason: str) -> "InvestorProfile":
    """Same investor, a lower (never higher) risk level: used per goal and when the investor picks a safer level."""
    if level > profile.level:
        raise ValueError(f"level {level} is above the recommended level {profile.level}")
    from dataclasses import replace
    constraints, _ = constraints_for(level, profile.answers, profile.preferences)
    return replace(profile, level=level, level_name=LEVELS[level].name, constraints=constraints,
                   expected=expected_return(level, constraints.home_equity_share),
                   flags=profile.flags + [Flag("LEVEL_LOWERED", "info", reason, {"from": profile.level, "to": level})])


def choose_level(profile: "InvestorProfile", requested: int) -> tuple["InvestorProfile", str]:
    """Investor override, as robo-advisors do it: a MORE conservative level is always allowed,
    a more aggressive one is not (the recommendation already reflects capacity and tolerance)."""
    if requested == profile.level:
        return profile, "Recommended level kept."
    if requested < profile.level:
        return with_level(profile, requested, f"Investor chose level {requested} ({LEVELS[requested].name}), "
                                              f"more conservative than the recommended {profile.level}."), "Allowed."
    return profile, (f"Level {requested} ({LEVELS[requested].name}) is above the recommended level {profile.level}: "
                     "it would exceed the investor's capacity or tolerance, so it is not applied.")


def build_profile(answers: dict[str, str], preferences: Preferences = Preferences(),
                  goal: Goal | None = None, capacity_override: tuple[float, list] | None = None,
                  horizon_cap: bool = True, financials: dict | None = None) -> InvestorProfile:
    """Profile from questionnaire answers.

    ``capacity_override`` (score, reasons) replaces the capacity questions with a capacity
    computed from real numbers (see onboarding.py). With ``horizon_cap=False`` the overall level
    is not capped by a single horizon: each goal applies its own horizon cap instead.
    """
    missing = [q.id for q in QUESTIONS if q.id not in answers]
    if missing:
        raise ValueError(f"missing answers: {missing}")
    if preferences.esg not in {"none", "prefer", "exclude"} or preferences.crypto not in {"no", "small", "open"} \
            or preferences.region not in REGION_HOME_SHARE:
        raise ValueError(f"invalid preferences: {preferences}")

    capacity, cap_reasons = capacity_override if capacity_override else _dimension_score(answers, "capacity")
    tolerance, tol_reasons = _dimension_score(answers, "tolerance")
    risk = min(capacity, tolerance)
    level = level_from_score(risk)
    flags: list[Flag] = []

    if abs(capacity - tolerance) >= CONFLICT_GAP:
        lower = "capacity" if capacity < tolerance else "tolerance"
        flags.append(Flag("CAPACITY_TOLERANCE_GAP", "warning",
                          f"Risk capacity ({capacity:.0f}/100) and risk tolerance ({tolerance:.0f}/100) disagree; "
                          f"the level follows the lower one ({lower}).",
                          {"capacity": capacity, "tolerance": tolerance}))

    cap = HORIZON_LEVEL_CAP.get(answers["horizon"]) if horizon_cap else None
    if cap is not None and level > cap:
        flags.append(Flag("HORIZON_CAP", "warning",
                          f"A horizon of '{QUESTION_BY_ID['horizon'].option(answers['horizon']).label}' limits the "
                          f"level to {cap} ({LEVELS[cap].name}), down from {level} ({LEVELS[level].name}).",
                          {"score_level": level, "cap": cap}))
        level = cap

    if capacity_override is None and answers["emergency_fund"] == "none":
        flags.append(Flag("NO_EMERGENCY_FUND", "warning",
                          "No emergency fund: an unexpected expense could force a sale at a bad time. "
                          "Building 3 to 6 months of expenses in cash usually comes first."))

    constraints, cflags = constraints_for(level, answers, preferences)
    flags += cflags
    lv = LEVELS[level]
    home = constraints.home_equity_share

    expected = expected_return(level, home)
    expectation = QUESTION_BY_ID["return_expectation"].option(answers["return_expectation"]).score
    if expectation > expected["net"] + 0.02:
        flags.append(Flag("EXPECTATION_GAP", "warning",
                          f"Expected return ({expectation:.1%}) is well above the planning assumption for this level "
                          f"({expected['net']:.1%} after fees).",
                          {"expected_by_investor": expectation, "assumption": expected["net"]}))

    goal_analysis = None
    if goal is not None:
        need = required_return(goal)
        goal_analysis = {"required_return": need, "assumed_return": expected["net"], "reachable": need <= expected["net"]}
        if need > expected["net"]:
            reachable_levels = [n for n in LEVELS if expected_return(n, home)["net"] >= need]
            goal_analysis["monthly_contribution_needed"] = required_monthly_contribution(goal, expected["net"])
            goal_analysis["lowest_level_reaching_goal"] = reachable_levels[0] if reachable_levels else None
            flags.append(Flag("GOAL_NOT_REACHABLE", "warning",
                              f"The goal needs about {need:.1%} per year; the assumption for level {level} is "
                              f"{expected['net']:.1%}. Options: save {goal_analysis['monthly_contribution_needed']:,.0f} $ "
                              f"per month, extend the horizon, or lower the target. The level is not raised "
                              f"automatically because it is set by capacity and tolerance.",
                              goal_analysis))

    return InvestorProfile(
        answers=dict(answers), preferences=preferences, capacity=capacity, tolerance=tolerance,
        risk_score=risk, level=level, level_name=lv.name, experience=answers["experience"],
        constraints=constraints, expected=expected, goal_analysis=goal_analysis,
        reasons=cap_reasons + tol_reasons, flags=flags, financials=financials,
    )


# --------------------------------------------------------------------------- allocation checks

ASSET_GROUP = {"equity": "equity", "etf_equity": "equity", "etf_bond": "bond",
               "etf_commodity": "gold", "crypto": "crypto"}


@dataclass(frozen=True)
class Violation:
    code: str
    severity: str
    message: str
    value: float | None = None
    limit: float | None = None


def group_weights(weights: dict[str, float], universe: pd.DataFrame) -> pd.Series:
    w = pd.Series(weights, dtype=float)
    groups = universe.loc[w.index, "asset_class"].map(ASSET_GROUP)
    if groups.isna().any():
        raise KeyError(f"unmapped asset classes: {universe.loc[w.index[groups.isna()], 'asset_class'].unique()}")
    return w.groupby(groups).sum()


def check_allocation(weights: dict[str, float], profile: InvestorProfile, universe: pd.DataFrame,
                     prices: pd.DataFrame | None = None) -> list[Violation]:
    """Compare an allocation with the profile's constraints. Empty list = compliant."""
    from .exposure import alerts

    c = profile.constraints
    g = group_weights(weights, universe)
    out: list[Violation] = []
    eq, crypto, gold = g.get("equity", 0.0), g.get("crypto", 0.0), g.get("gold", 0.0)

    if eq > c.equity_max + 1e-9:
        out.append(Violation("EQUITY_ABOVE_RANGE", "warning",
                             f"Stocks are {eq:.0%}; level {profile.level} ({profile.level_name}) allows "
                             f"{c.equity_min:.0%} to {c.equity_max:.0%}.", eq, c.equity_max))
    if eq < c.equity_min - 1e-9:
        out.append(Violation("EQUITY_BELOW_RANGE", "info",
                             f"Stocks are {eq:.0%}, below the {c.equity_min:.0%} minimum for level {profile.level}.",
                             eq, c.equity_min))
    if crypto > c.max_crypto + 1e-9:
        out.append(Violation("CRYPTO_ABOVE_LIMIT", "warning",
                             f"Crypto is {crypto:.0%}; this profile allows {c.max_crypto:.0%}.", crypto, c.max_crypto))
    if gold > c.max_gold + 1e-9:
        out.append(Violation("GOLD_ABOVE_LIMIT", "warning", f"Gold is {gold:.0%} (limit {c.max_gold:.0%}).",
                             gold, c.max_gold))

    w = pd.Series(weights, dtype=float)
    u = universe.loc[w.index]
    for t in w.index:
        if u.loc[t, "asset_class"] == "equity" and u.loc[t, "sector"] in c.excluded_sectors:
            out.append(Violation("EXCLUDED_SECTOR", "warning",
                                 f"{t} is in {u.loc[t, 'sector']}, a sector the investor chose to exclude.",
                                 float(w[t]), 0.0))
    if c.excluded_sectors and (u["asset_class"] == "etf_equity").any():
        out.append(Violation("FUND_HOLDINGS_NOT_CHECKED", "info",
                             "Broad equity ETFs may hold companies in excluded sectors; fund holdings are not checked."))

    if prices is not None:
        for a in alerts(weights, universe, prices, limits=c.limits):
            if a.code in {"SINGLE_SECURITY", "SECTOR", "RISK_CONCENTRATION"}:
                out.append(Violation(a.code, a.severity, a.message, a.value, a.threshold))
    return out
