"""Numeric onboarding: the investor's real (fictional) numbers instead of multiple-choice proxies.

Canadian robo-advisors ask for income, savings, debts and goals in dollars, then
ask how the investor would react to a loss expressed in their own dollars.
This module turns those numbers into the same profile structure as before:

* Risk CAPACITY comes from measured ratios, each with a documented scale:
  emergency fund in months of expenses, share of assets being invested, debt
  relative to income, savings rate, employment stability, dependents.
  The horizon is NOT part of the overall capacity: every goal has its own
  horizon and caps its own risk level (goals.py), as the BNC workshop put it.
* Risk TOLERANCE still comes from behaviour questions, now in dollars.
* The savings capacity (income - expenses) is checked against what the goals
  need each month.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from . import profile as pf
from .goals import GoalSpec

EMPLOYMENT = {  # code -> (stability score 0..1, label)
    "public": (1.0, "Public sector or very stable job"),
    "salaried": (0.8, "Permanent employee"),
    "retired": (0.6, "Retired with a pension"),
    "contract": (0.45, "Contract, commission or seasonal work"),
    "self_employed": (0.4, "Self-employed"),
    "student": (0.3, "Student"),
    "unemployed": (0.0, "Unemployed"),
}
PROVINCES = ["QC", "ON", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "YT", "NT", "NU"]

# Weights of the capacity components (sum does not need to be 1).
CAPACITY_WEIGHTS = {"emergency": 1.5, "investable_share": 1.5, "employment": 1.5, "debt": 1.0, "savings": 1.0,
                    "dependents": 1.0}


def lin(x: float, at_zero: float, at_one: float) -> float:
    t = (x - at_zero) / (at_one - at_zero)
    return float(min(1.0, max(0.0, t)))


@dataclass
class Financials:
    age: int
    province: str
    employment: str
    annual_income: float        # gross, CAD
    monthly_expenses: float
    monthly_savings: float      # what the investor can set aside each month
    cash_savings: float         # savings account, available now
    investments: float          # amount to invest in this simulation
    other_assets: float = 0.0   # home equity, other property (net of mortgage)
    debts: float = 0.0          # debts other than the mortgage
    dependents: int = 0

    def __post_init__(self):
        if self.employment not in EMPLOYMENT:
            raise ValueError(f"employment must be one of {list(EMPLOYMENT)}")
        for name in ("annual_income", "monthly_expenses", "monthly_savings", "cash_savings", "investments",
                     "other_assets", "debts"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")

    @property
    def net_worth(self) -> float:
        return self.cash_savings + self.investments + self.other_assets - self.debts

    @property
    def total_assets(self) -> float:
        return self.cash_savings + self.investments + self.other_assets

    @property
    def emergency_months(self) -> float:
        return self.cash_savings / self.monthly_expenses if self.monthly_expenses > 0 else 12.0

    @property
    def investable_share(self) -> float:
        return self.investments / self.total_assets if self.total_assets > 0 else 1.0

    @property
    def debt_to_income(self) -> float:
        if self.annual_income > 0:
            return self.debts / self.annual_income
        return 0.0 if self.debts == 0 else 10.0

    @property
    def savings_rate(self) -> float:
        return 12 * self.monthly_savings / self.annual_income if self.annual_income > 0 else 0.0

    def emergency_target(self) -> float:
        """3 months of expenses, 6 when income is less stable or others depend on it."""
        months = 6 if EMPLOYMENT[self.employment][0] < 0.6 or self.dependents > 0 else 3
        return months * self.monthly_expenses

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(net_worth=self.net_worth, emergency_months=self.emergency_months,
                 investable_share=self.investable_share, debt_to_income=self.debt_to_income,
                 savings_rate=self.savings_rate, emergency_target=self.emergency_target())
        return d


def capacity_from(fin: Financials) -> tuple[float, list[pf.Reason]]:
    """Capacity score 0-100 from measured ratios, with one reason per component."""
    comps = {
        "emergency": (lin(fin.emergency_months, 0, 6), f"{fin.emergency_months:.1f} months of expenses in cash "
                                                       "(0 scores 0, 6 or more scores 1)"),
        "investable_share": (lin(fin.investable_share, 0.75, 0.25),
                             f"{fin.investable_share:.0%} of assets invested here (75% or more scores 0, 25% or less scores 1)"),
        "employment": (EMPLOYMENT[fin.employment][0], EMPLOYMENT[fin.employment][1]),
        "debt": (lin(fin.debt_to_income, 1.0, 0.0), f"debts other than mortgage = {fin.debt_to_income:.0%} of income "
                                                    "(100% or more scores 0, none scores 1)"),
        "savings": (lin(fin.savings_rate, 0.0, 0.20), f"saves {fin.savings_rate:.0%} of income (0% scores 0, 20% or more scores 1)"),
        "dependents": ({0: 1.0, 1: 0.7, 2: 0.5}.get(fin.dependents, 0.3), f"{fin.dependents} dependent(s)"),
    }
    total_w = sum(CAPACITY_WEIGHTS.values())
    reasons, score = [], 0.0
    for k, (v, why) in comps.items():
        pts = 100 * CAPACITY_WEIGHTS[k] * v / total_w
        score += pts
        reasons.append(pf.Reason(k, f"{v:.2f}", why, "capacity", pts))
    return score, reasons


def _answers_for_compat(fin: Financials, goals: list[GoalSpec]) -> dict[str, str]:
    """Closest questionnaire codes, so the rest of the system (and its tests) keep one profile shape."""
    m = fin.emergency_months
    share = fin.investable_share
    longest = max((g.horizon_years for g in goals), default=10)
    horizon = "lt3" if longest < 3 else "3to5" if longest < 5 else "5to10" if longest < 10 else "10to15" if longest < 15 else "gt15"
    stab = EMPLOYMENT[fin.employment][0]
    return {
        "horizon": horizon,
        "income_stability": "very_stable" if stab >= 0.9 else "stable" if stab >= 0.6 else "variable" if stab > 0 else "unstable",
        "emergency_fund": "none" if m < 0.5 else "lt3" if m < 3 else "3to6" if m <= 6 else "gt6",
        "wealth_share": "gt75" if share > 0.75 else "50to75" if share > 0.5 else "25to50" if share > 0.25 else "lt25",
        "dependents": "none" if fin.dependents == 0 else "some" if fin.dependents <= 2 else "several",
    }


@dataclass
class Onboarding:
    financials: Financials
    goals: list[GoalSpec]
    tolerance: dict[str, str]     # drop_reaction, range_choice, goal, experience, return_expectation
    preferences: pf.Preferences = field(default_factory=pf.Preferences)

    def to_dict(self) -> dict:
        return {"financials": asdict(self.financials), "goals": [asdict(g) for g in self.goals],
                "tolerance": dict(self.tolerance), "preferences": asdict(self.preferences)}

    @classmethod
    def from_dict(cls, d: dict) -> "Onboarding":
        prefs = d.get("preferences", {})
        return cls(Financials(**d["financials"]), [GoalSpec(**g) for g in d["goals"]], dict(d["tolerance"]),
                   pf.Preferences(**{k: tuple(v) if isinstance(v, list) else v for k, v in prefs.items()}))


def build_profile(onb: Onboarding) -> pf.InvestorProfile:
    fin = onb.financials
    answers = {**_answers_for_compat(fin, onb.goals), **onb.tolerance}
    capacity = capacity_from(fin)
    p = pf.build_profile(answers, onb.preferences, capacity_override=capacity, horizon_cap=False,
                         financials=fin.to_dict())
    extra = []
    target = fin.emergency_target()
    if fin.cash_savings < target:
        extra.append(pf.Flag("EMERGENCY_FUND_SHORT", "warning",
                             f"Emergency fund: ${fin.cash_savings:,.0f} covers {fin.emergency_months:.1f} months; "
                             f"the target is ${target:,.0f} ({target / fin.monthly_expenses:.0f} months). "
                             "Filling it usually comes before investing.",
                             {"cash": fin.cash_savings, "target": target}))
    need = sum(g.monthly_contribution for g in onb.goals)
    if need > fin.monthly_savings + 1e-9:
        extra.append(pf.Flag("SAVINGS_OVERCOMMITTED", "warning",
                             f"The goals plan ${need:,.0f} a month but the stated savings capacity is "
                             f"${fin.monthly_savings:,.0f}.", {"planned": need, "capacity": fin.monthly_savings}))
    # The plan invests what is set aside for the goals; it must match the savings and investments declared.
    assigned, available = assigned_amount(onb), fin.cash_savings + fin.investments
    if assigned > available + 1:
        extra.append(pf.Flag("GOALS_EXCEED_ASSETS", "warning",
                             f"The goals count ${assigned:,.0f} already set aside, but savings and investments total "
                             f"${available:,.0f}. Lower the amounts already set aside, or update your savings.",
                             {"assigned": assigned, "available": available}))
    elif available - assigned > max(1000.0, 0.05 * available):
        extra.append(pf.Flag("UNASSIGNED_SAVINGS", "info",
                             f"${available - assigned:,.0f} of savings and investments is not assigned to a goal. The plan "
                             "invests only what is assigned; add it to a goal to include it.",
                             {"assigned": assigned, "available": available}))
    if fin.debt_to_income > 0.4:
        extra.append(pf.Flag("HIGH_DEBT", "warning",
                             f"Debts other than the mortgage equal {fin.debt_to_income:.0%} of income. Paying down "
                             "high-interest debt is a guaranteed return that investing cannot promise.",
                             {"debt_to_income": fin.debt_to_income}))
    p.flags.extend(extra)
    return p


def assigned_amount(onb: Onboarding) -> float:
    """Money already set aside across the goals: the size of the simulated portfolio."""
    return float(sum(g.current_amount for g in onb.goals))


def invested_amount(onb: Onboarding) -> float:
    """Money exposed to markets (goals other than the emergency fund): the amount risk questions talk about."""
    return float(sum(g.current_amount for g in onb.goals if g.type != "emergency_fund"))


def suggested_goals(fin: Financials) -> list[GoalSpec]:
    """Default goals: the emergency fund sized from expenses, and long-term growth or retirement."""
    years_to_65 = max(1, 65 - fin.age)
    return [
        GoalSpec("Emergency fund", "emergency_fund", 0, round(fin.emergency_target(), -2), fin.cash_savings, 0),
        GoalSpec("Retirement", "retirement", years_to_65, round(25 * 12 * fin.monthly_expenses, -3), fin.investments,
                 round(fin.monthly_savings * 0.6, -1)),
    ]


# ----------------------------------------------------------------------------- demo personas (fictional)

PERSONAS = {
    "Amira": Onboarding(
        Financials(26, "QC", "salaried", 95_000, 3_200, 1_500, 15_000, 40_000, 0, 12_000, 0),
        [GoalSpec("Emergency fund", "emergency_fund", 0, 9_600, 15_000, 0),
         GoalSpec("Long-term growth", "retirement", 20, 600_000, 40_000, 1_200)],
        dict(drop_reaction="buy_more", range_choice="D", goal="max_growth", experience="intermediate",
             return_expectation="7to10"),
        pf.Preferences(crypto="open", region="global", themes=("tech_ai", "crypto"))),
    "Mateo": Onboarding(
        Financials(41, "ON", "salaried", 110_000, 5_500, 1_200, 25_000, 150_000, 150_000, 10_000, 2),
        [GoalSpec("Emergency fund", "emergency_fund", 0, 33_000, 25_000, 300),
         GoalSpec("Children's education", "project", 10, 80_000, 20_000, 300),
         GoalSpec("Retirement", "retirement", 22, 900_000, 130_000, 600)],
        dict(drop_reaction="hold", range_choice="B", goal="balanced", experience="intermediate",
             return_expectation="5to7"),
        pf.Preferences(esg="exclude", values=("no_fossil_fuels",), themes=("health", "consumer"))),
    "Robert": Onboarding(
        Financials(59, "QC", "salaried", 140_000, 6_000, 2_500, 60_000, 450_000, 600_000, 0, 0),
        [GoalSpec("Emergency fund", "emergency_fund", 0, 18_000, 60_000, 0),
         GoalSpec("Retirement in 4 years", "retirement", 4, 600_000, 450_000, 2_000)],
        dict(drop_reaction="hold", range_choice="C", goal="preserve", experience="advanced",
             return_expectation="5to7"),
        pf.Preferences(themes=("canadian_banks", "dividends"))),
}
