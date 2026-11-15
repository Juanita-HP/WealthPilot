"""Goals: one portfolio, several objectives, each with its own horizon.

From the BNC finance workshop: people invest FOR something (emergency fund,
a project, retirement, income, leaving something behind); the horizon belongs
to the goal, not to the person's age; and one global portfolio can hold several
horizons at once. So each goal gets its own sub-portfolio ("account"), with a
risk level that is the LOWER of:

* the investor's overall level (capacity and tolerance), and
* what the goal's horizon allows (under 3 years there is no time to recover from
  a downturn; 3 to 10 years is medium term; beyond 10 years a full cycle fits).

An emergency fund is always cash-like: it must be available tomorrow.

Account types are suggested for education (CELI / TFSA, REER / RRSP,
CELIAPP / FHSA, non-registered); eligibility and taxes are outside this
simulation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import pandas as pd

from . import profile as pf
from .strategist import BLOCKS, policy_allocation

GOAL_TYPES = {
    "emergency_fund": "Emergency fund (about 3 to 6 months of expenses, must stay available)",
    "home_purchase": "First home down payment",
    "project": "Project with a date and an amount (trip, car, studies)",
    "retirement": "Retirement",
    "income": "Regular income from investments",
    "legacy": "Wealth to pass on",
}
ACCOUNT_SUGGESTION = {
    "emergency_fund": ("CELI / TFSA or high-interest savings", "Withdrawals are tax-free and the room comes back the next year."),
    "home_purchase": ("CELIAPP / FHSA", "Contributions are deductible and qualifying withdrawals for a first home are tax-free."),
    "project": ("CELI / TFSA", "Flexible withdrawals without tax."),
    "retirement": ("REER / RRSP, then CELI / TFSA", "Deduction now, tax at withdrawal, usually at a lower rate in retirement."),
    "income": ("CELI / TFSA, then non-registered", "Income inside a TFSA is not taxed."),
    "legacy": ("Non-registered or TFSA; see an estate planner", "Estate rules depend on the province and the account."),
}


def horizon_cap(years: float) -> int:
    """Highest level a goal's horizon allows."""
    if years < 3:
        return 1
    if years < 5:
        return 2
    if years < 10:
        return 3
    if years < 15:
        return 4
    return 5


@dataclass(frozen=True)
class GoalSpec:
    name: str
    type: str
    horizon_years: float
    target_amount: float
    current_amount: float = 0.0
    monthly_contribution: float = 0.0

    def __post_init__(self):
        if self.type not in GOAL_TYPES:
            raise ValueError(f"unknown goal type {self.type!r}; expected one of {list(GOAL_TYPES)}")


@dataclass
class GoalPlan:
    goal: GoalSpec
    level: int
    level_name: str
    why_level: str
    weights: dict[str, float]
    reasons: list[dict]
    account: str
    account_why: str
    goal_analysis: dict
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


@dataclass
class Plan:
    goals: list[GoalPlan]
    total_weights: dict[str, float]
    total_amount: float
    order: list[str]
    notes: list[str]

    def to_dict(self):
        return asdict(self)


def _cushion_analysis(g: GoalSpec) -> dict:
    """An emergency fund has no return to reach: it has to be filled."""
    gap = max(0.0, g.target_amount - g.current_amount)
    months = None if gap == 0 else (gap / g.monthly_contribution if g.monthly_contribution > 0 else None)
    return {"kind": "cushion", "reachable": gap == 0, "gap": gap, "months_to_fill": months,
            "required_return": None, "assumed_return": None}


def _goal_analysis(g: GoalSpec, expected_net: float) -> dict:
    goal = pf.Goal(g.current_amount, g.target_amount, max(g.horizon_years, 0.25), g.monthly_contribution)
    need = pf.required_return(goal)
    out = {"required_return": need, "assumed_return": expected_net, "reachable": need <= expected_net,
           "assumption_source": pf.assumptions.SOURCE["name"]}
    if need > expected_net:
        out["monthly_contribution_needed"] = pf.required_monthly_contribution(goal, expected_net)
    return out


CASH_ONLY_HORIZON = 2.0  # years: too short to recover from a market fall


def plan_goal(profile: pf.InvestorProfile, g: GoalSpec, prices: pd.DataFrame | None = None) -> GoalPlan:
    if g.type != "emergency_fund" and g.horizon_years < CASH_ONLY_HORIZON:
        return GoalPlan(
            g, 1, "Cash reserve", f"A {g.horizon_years:g}-year horizon is too short to wait for a recovery after a "
                                  "market fall, so the money stays in cash-like holdings.",
            {BLOCKS["cash"]: 1.0},
            [{"ticker": BLOCKS["cash"], "weight": 1.0, "reason": "Capital preservation until the date of the project."}],
            *ACCOUNT_SUGGESTION[g.type], _goal_analysis(g, pf.assumptions.RETURNS["short_term"] - pf.FEE_ASSUMPTION),
            ["If the target is not reachable with cash returns, saving more or moving the date works better than "
             "taking market risk."])
    if g.type == "emergency_fund":
        return GoalPlan(
            g, 1, "Cash reserve", "An emergency fund must be available immediately, whatever the investor's profile.",
            {BLOCKS["cash"]: 1.0},
            [{"ticker": BLOCKS["cash"], "weight": 1.0,
              "reason": "Ultra short-term bonds as a cash proxy in this dataset; a high-interest savings account or "
                        "GIC plays the same role in practice."}],
            *ACCOUNT_SUGGESTION[g.type], _cushion_analysis(g),
            ["Its return may not beat inflation: that is the price of being available tomorrow."])
    cap = horizon_cap(g.horizon_years)
    level = min(profile.level, cap)
    why = (f"Profile level {profile.level} ({profile.level_name}); a {g.horizon_years:g}-year horizon allows up to "
           f"level {cap} ({pf.LEVELS[cap].name}). The goal uses the lower: level {level}.")
    goal_profile = profile if level == profile.level else pf.with_level(profile, level, why)
    al = policy_allocation(goal_profile, prices)
    notes = list(al.notes)
    expected = pf.expected_return(level, goal_profile.constraints.home_equity_share, al.equity_share,
                                  split=al.equity_split or goal_profile.constraints.equity_split)
    if g.type == "income":
        notes.append("Income goal: dividends and bond interest matter more than growth; check yields in the "
                     "ticker dashboard.")
    return GoalPlan(g, level, pf.LEVELS[level].name, why, al.weights,
                    [{"ticker": ln.ticker, "weight": ln.weight, "reason": ln.reason} for ln in al.lines],
                    *ACCOUNT_SUGGESTION[g.type], _goal_analysis(g, expected["net"]), notes)


def plan(profile: pf.InvestorProfile, goals: list[GoalSpec], prices: pd.DataFrame | None = None) -> Plan:
    """A sub-portfolio per goal, plus the combined portfolio weighted by money in each goal."""
    plans = [plan_goal(profile, g, prices) for g in goals]
    amounts = [max(p.goal.current_amount, 1.0) for p in plans]
    total = sum(amounts)
    combined: dict[str, float] = {}
    for p, a in zip(plans, amounts):
        for t, w in p.weights.items():
            combined[t] = combined.get(t, 0.0) + w * a / total
    notes = []
    order = sorted(range(len(plans)), key=lambda i: (plans[i].goal.type != "emergency_fund", plans[i].goal.horizon_years))
    if not any(p.goal.type == "emergency_fund" for p in plans):
        notes.append("No emergency fund among the goals. Usually it comes first, so a surprise expense does not "
                     "force a sale in a downturn.")
    return Plan(plans, combined, sum(p.goal.current_amount for p in plans),
                [plans[i].goal.name for i in order], notes)


def check_plan(profile: pf.InvestorProfile, p: Plan, universe: pd.DataFrame, prices: pd.DataFrame | None = None) -> dict:
    """Constraint checks per goal, each against that goal's own level (the combined portfolio mixes levels)."""
    out = {}
    for g in p.goals:
        if g.weights == {BLOCKS["cash"]: 1.0}:
            out[g.goal.name] = []
            continue
        goal_profile = profile if g.level == profile.level else pf.with_level(profile, g.level, g.why_level)
        out[g.goal.name] = pf.check_allocation(g.weights, goal_profile, universe, prices)
    return out


def effective_profile(profile: pf.InvestorProfile, p: Plan) -> pf.InvestorProfile:
    """The most restrictive level among invested goals: what a new request must respect."""
    levels = [g.level for g in p.goals if g.weights != {BLOCKS["cash"]: 1.0}]
    if not levels or min(levels) >= profile.level:
        return profile
    lvl = min(levels)
    return pf.with_level(profile, lvl, f"Most restrictive invested goal is at level {lvl} ({pf.LEVELS[lvl].name}).")
