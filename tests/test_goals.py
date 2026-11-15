import pytest

from tests.conftest import requires_starter
from tests.test_profile import AMIRA, MATEO, ROBERT
from wealthpilot import goals as gl
from wealthpilot import profile as pf
from wealthpilot import strategist as st
from wealthpilot import whatif


def test_horizon_caps_and_cash_only_below_two_years():
    assert [gl.horizon_cap(y) for y in (1, 3, 6, 12, 20)] == [1, 2, 3, 4, 5]
    amira = pf.build_profile(AMIRA)
    trip = gl.plan_goal(amira, gl.GoalSpec("Trip", "project", 1.5, 8000, 5000))
    assert trip.weights == {"ZST.TO": 1.0}
    cushion = gl.plan_goal(amira, gl.GoalSpec("Cushion", "emergency_fund", 0, 15000, 15000))
    assert cushion.weights == {"ZST.TO": 1.0}


def test_goal_level_never_above_profile_level():
    rob = pf.build_profile(ROBERT)          # level 2
    for years in (3, 6, 12, 25):
        p = gl.plan_goal(rob, gl.GoalSpec("G", "retirement", years, 100000, 50000))
        assert p.level <= rob.level and p.level <= gl.horizon_cap(years)


def test_plan_combines_goals_by_money_and_orders_emergency_first():
    p = pf.build_profile(MATEO)
    plan = gl.plan(p, [gl.GoalSpec("Retirement", "retirement", 24, 800000, 90000),
                       gl.GoalSpec("Cushion", "emergency_fund", 0, 10000, 10000)])
    assert sum(plan.total_weights.values()) == pytest.approx(1.0)
    assert plan.order[0] == "Cushion"
    # The cushion's cash weighs in the total; the 24-year goal holds none (the cushion is the cash reserve).
    assert plan.total_weights["ZST.TO"] == pytest.approx(0.1)
    retirement = next(g for g in plan.goals if g.goal.name == "Retirement")
    assert retirement.weights.get("ZST.TO", 0) == 0


def test_safe_sleeve_duration_matches_short_horizons():
    p = pf.build_profile(MATEO)  # level 3: 20% cash-like by default
    share, why = st.cash_share_for(p.level, 4)
    bond = st.CANADIAN_BOND_SHARE * st.DURATION["canadian_bonds"] + (1 - st.CANADIAN_BOND_SHARE) * st.DURATION["us_bonds"]
    assert share * st.DURATION["cash"] + (1 - share) * bond == pytest.approx(4)  # average duration = horizon
    assert "duration" in why
    assert st.cash_share_for(p.level, 8)[0] == st.CASH_SHARE[p.level]          # never below the level's share
    assert st.cash_share_for(p.level, 15)[0] == 0.0
    assert st.cash_share_for(p.level, None)[0] == st.CASH_SHARE[p.level]       # without a goal: unchanged


def test_more_conservative_choice_allowed_more_aggressive_refused():
    p = pf.build_profile(MATEO)  # level 3
    lower, msg = pf.choose_level(p, 2)
    assert lower.level == 2 and lower.constraints.equity_max == pf.LEVELS[2].equity_max
    same, msg = pf.choose_level(p, 5)
    assert same.level == 3 and "not applied" in msg
    with pytest.raises(ValueError):
        pf.with_level(p, 4, "x")


def test_non_financial_preferences():
    p = pf.build_profile(MATEO, pf.Preferences(values=("no_fossil_fuels",), simplicity=True))
    assert "Energy" in p.constraints.excluded_sectors
    simple = st.policy_allocation(p).weights
    full = st.policy_allocation(pf.build_profile(MATEO)).weights
    assert len(simple) < len(full) and sum(simple.values()) == pytest.approx(1.0)
    assert pf.level_card(p.level)["name"] == "Balanced"


def test_tipping_points_are_real():
    p = pf.build_profile(ROBERT)
    for c in whatif.profile_tipping_points(p):
        q = pf.QUESTION_BY_ID[c.subject]
        label = c.condition.split("were '")[1].split("' instead")[0]
        code = next(o.code for o in q.options if o.label == label)
        assert pf.build_profile(dict(p.answers, **{c.subject: code})).level != p.level


def test_goal_conditions_include_inflation_and_return():
    p = pf.build_profile(MATEO)
    kinds = {c.kind for c in whatif.goal_conditions(p, gl.GoalSpec("House", "home_purchase", 4, 60000, 30000, 500))}
    assert {"horizon", "inflation", "return"} <= kinds


@requires_starter
def test_risk_map_on_real_data():
    from wealthpilot import data, risks
    px, u = data.load_prices_cad(), data.load_universe()
    vol = risks.average_dollar_volume(data.load_prices("close"), data.load_prices("volume"))
    funds = {r.kind: r for r in risks.risk_map({"XIU.TO": 0.4, "SPY": 0.3, "XBB.TO": 0.3}, u, px, vol)}
    assert funds["liquidity"].level == "low"            # ETF volume is not used as a liquidity test
    assert funds["concentration"].level == "low"        # broad funds only
    tsla = {r.kind: r for r in risks.risk_map({"TSLA": 0.3, "XIU.TO": 0.4, "XBB.TO": 0.3}, u, px, vol)}
    assert tsla["concentration"].level == "high" and tsla["market"].level == "high"
