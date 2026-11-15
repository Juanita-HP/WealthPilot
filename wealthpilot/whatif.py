"""What would change the answer.

The BNC finance workshop: an explanation should state which data was used, why
this choice, its limits, and WHAT WOULD CHANGE IT ("this recommendation holds
if..."). These functions compute those conditions instead of guessing them:

* profile tipping points: which single answer, moved one step, changes the level
* goal conditions: the horizon at which a goal's level changes, the effect of
  higher inflation, and of a 1-point lower return on the saving needed
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import profile as pf
from .goals import CASH_ONLY_HORIZON, GoalSpec, horizon_cap


@dataclass
class Condition:
    subject: str
    condition: str
    effect: str
    kind: str  # profile | horizon | inflation | return

    def to_dict(self):
        return asdict(self)


def profile_tipping_points(profile: pf.InvestorProfile) -> list[Condition]:
    out = []
    for q in pf.QUESTIONS:
        if q.dimension not in {"capacity", "tolerance"}:
            continue
        codes = [o.code for o in q.options]
        i = codes.index(profile.answers[q.id])
        for j in (i - 1, i + 1):
            if not 0 <= j < len(codes):
                continue
            alt = pf.build_profile(dict(profile.answers, **{q.id: codes[j]}), profile.preferences)
            if alt.level != profile.level:
                out.append(Condition(
                    q.id, f"If the answer to '{q.text}' were '{q.options[j].label}' instead of '{q.options[i].label}'",
                    f"the level would be {alt.level} ({alt.level_name}) instead of {profile.level} ({profile.level_name}).",
                    "profile"))
    return out


def goal_conditions(profile: pf.InvestorProfile, g: GoalSpec, inflation_alt: float = 0.03) -> list[Condition]:
    out = []
    level = min(profile.level, horizon_cap(g.horizon_years)) if g.type != "emergency_fund" else 1
    if g.type != "emergency_fund":
        for years in (CASH_ONLY_HORIZON, 3, 5, 10, 15):
            if years < g.horizon_years:
                new = 1 if years < CASH_ONLY_HORIZON else min(profile.level, horizon_cap(years - 0.01))
                if new != level:
                    out.append(Condition(g.name, f"If the horizon fell below {years:g} years",
                                         "the goal would move to cash-like holdings." if years == CASH_ONLY_HORIZON
                                         else f"the goal's level would drop to {new} ({pf.LEVELS[new].name}).",
                                         "horizon"))
                    break
    exp = pf.expected_return(level, profile.constraints.home_equity_share, split=profile.constraints.equity_split)["net"]
    real_base = (1 + exp) / (1 + pf.assumptions.INFLATION) - 1
    real_alt = (1 + exp) / (1 + inflation_alt) - 1
    out.append(Condition(g.name, f"If inflation averaged {inflation_alt:.1%} instead of {pf.assumptions.INFLATION:.1%}",
                         f"the assumed real return would fall from {real_base:.1%} to {real_alt:.1%} a year.", "inflation"))
    if g.target_amount > 0 and g.horizon_years >= 1 and g.type != "emergency_fund":
        goal = pf.Goal(g.current_amount, g.target_amount, g.horizon_years, g.monthly_contribution)
        need_base = pf.required_monthly_contribution(goal, exp)
        need_low = pf.required_monthly_contribution(goal, exp - 0.01)
        out.append(Condition(g.name, "If returns were 1 percentage point lower than the planning assumption",
                             f"reaching the target would need ${need_low:,.0f} a month instead of ${need_base:,.0f}.",
                             "return"))
    return out
