import pytest

from tests.conftest import requires_starter
from wealthpilot import accounts, goals as gl, onboarding as ob, profile as pf, strategist as st


def fin(**kw):
    base = dict(age=35, province="QC", employment="salaried", annual_income=80_000, monthly_expenses=3_000,
                monthly_savings=800, cash_savings=18_000, investments=50_000, other_assets=0, debts=0, dependents=0)
    return ob.Financials(**{**base, **kw})


TOL = dict(drop_reaction="hold", range_choice="C", goal="balanced", experience="intermediate", return_expectation="5to7")


def test_ratios():
    f = fin(debts=20_000)
    assert f.emergency_months == pytest.approx(6.0)
    assert f.net_worth == 48_000
    assert f.investable_share == pytest.approx(50_000 / 68_000)
    assert f.debt_to_income == pytest.approx(0.25)
    assert f.savings_rate == pytest.approx(0.12)
    assert f.emergency_target() == 9_000                      # 3 months, stable job, no dependents
    assert fin(employment="self_employed").emergency_target() == 18_000


def test_capacity_reasons_add_up_and_move_the_right_way():
    score, reasons = ob.capacity_from(fin())
    assert sum(r.contribution for r in reasons) == pytest.approx(score)
    assert ob.capacity_from(fin(cash_savings=0))[0] < score          # no cushion lowers capacity
    assert ob.capacity_from(fin(debts=80_000))[0] < score            # debt lowers capacity
    assert ob.capacity_from(fin(employment="unemployed"))[0] < score
    assert ob.capacity_from(fin(dependents=3))[0] < score
    assert ob.capacity_from(fin(other_assets=500_000))[0] > score    # investing a small share of assets


def test_negative_amounts_and_unknown_employment_rejected():
    with pytest.raises(ValueError):
        fin(annual_income=-1)
    with pytest.raises(ValueError):
        fin(employment="astronaut")


def test_flags_from_numbers():
    o = ob.Onboarding(fin(cash_savings=1_000, debts=50_000, monthly_savings=200),
                      [gl.GoalSpec("Retirement", "retirement", 25, 500_000, 50_000, 900)], TOL)
    codes = {f.code for f in ob.build_profile(o).flags}
    assert {"EMERGENCY_FUND_SHORT", "SAVINGS_OVERCOMMITTED", "HIGH_DEBT"} <= codes


def test_no_single_horizon_cap_goals_cap_themselves():
    o = ob.Onboarding(fin(other_assets=300_000), [gl.GoalSpec("Voyage", "project", 3.5, 8_000, 2_000)],
                      dict(TOL, drop_reaction="buy_more", range_choice="D", goal="max_growth"))
    p = ob.build_profile(o)
    assert p.level >= 4                                        # overall level from capacity and tolerance
    assert gl.plan_goal(p, o.goals[0]).level == 2               # the 3.5-year goal is capped


def test_round_trip_dict():
    o = ob.PERSONAS["Mateo"]
    back = ob.Onboarding.from_dict(o.to_dict())
    assert back == o and ob.build_profile(back).level == ob.build_profile(o).level


def test_personas():
    levels = {n: ob.build_profile(o).level for n, o in ob.PERSONAS.items()}
    assert levels["Amira"] >= 4 and levels["Mateo"] == 3
    rob = ob.build_profile(ob.PERSONAS["Robert"])
    p = gl.plan(rob, ob.PERSONAS["Robert"].goals)
    assert gl.effective_profile(rob, p).level == 2              # his 4-year retirement goal sets the bar


def test_themes_become_bounded_satellites():
    o = ob.PERSONAS["Mateo"]
    p = ob.build_profile(o)
    al = st.policy_allocation(p)
    sats = [ln for ln in al.lines if ln.block == "satellite"]
    assert sats and all(ln.weight <= p.constraints.limits.max_single_security + 1e-12 for ln in sats)
    assert all(ln.weight >= st.MIN_SATELLITE - 1e-12 for ln in sats)
    assert sum(al.weights.values()) == pytest.approx(1.0)
    assert not any(t in al.weights for t in ("XOM", "CNQ.TO", "ENB.TO"))  # values exclude fossil fuels


def test_level_one_has_no_satellites_and_excluded_theme_is_skipped():
    p = pf.with_level(ob.build_profile(ob.PERSONAS["Robert"]), 1, "test")
    assert not [ln for ln in st.policy_allocation(p).lines if ln.block == "satellite"]
    energy = pf.build_profile(dict(horizon="gt15", income_stability="stable", emergency_fund="3to6",
                                   wealth_share="25to50", dependents="none", drop_reaction="hold", range_choice="C",
                                   goal="balanced", experience="intermediate", return_expectation="5to7"),
                              pf.Preferences(themes=("energy",), values=("no_fossil_fuels",)))
    al = st.policy_allocation(energy)
    assert not [ln for ln in al.lines if ln.block == "satellite"]
    assert any("excluded" in n for n in al.notes)


@requires_starter
def test_plan_checks_each_goal_against_its_own_level():
    from wealthpilot import data
    for name, o in ob.PERSONAS.items():
        p = ob.build_profile(o)
        plan = gl.plan(p, o.goals, data.load_prices_cad())
        checks = gl.check_plan(p, plan, data.load_universe(), data.load_prices_cad())
        assert not [v for vs in checks.values() for v in vs if v.severity == "warning"], name


def test_accounts(tmp_path):
    db = tmp_path / "u.db"
    accounts.create_user("demo.user", "longpassword", db)
    with pytest.raises(accounts.AccountError):
        accounts.create_user("Demo.User", "longpassword", db)       # case-insensitive duplicate
    with pytest.raises(accounts.AccountError):
        accounts.create_user("ab", "longpassword", db)
    with pytest.raises(accounts.AccountError):
        accounts.create_user("other", "short", db)
    assert accounts.authenticate("DEMO.user", "longpassword", db)
    assert not accounts.authenticate("demo.user", "wrongpassword", db)
    assert not accounts.authenticate("nobody", "longpassword", db)
    assert accounts.load_profile("demo.user", db) is None
    accounts.save_profile("demo.user", ob.PERSONAS["Amira"].to_dict(), db)
    assert ob.Onboarding.from_dict(accounts.load_profile("demo.user", db)) == ob.PERSONAS["Amira"]
    raw = (db).read_bytes()
    assert b"longpassword" not in raw


def test_stock_share_follows_the_exact_score_within_a_level():
    from dataclasses import replace
    from wealthpilot import strategist as st
    p = ob.build_profile(ob.PERSONAS["Mateo"])
    low, high = replace(p, risk_score=41.0), replace(p, risk_score=59.0)
    assert low.level == high.level == 3
    a, b = st.policy_allocation(low).equity_share, st.policy_allocation(high).equity_share
    lv = pf.LEVELS[3]
    assert lv.equity_min <= a < b <= lv.equity_max
    assert "risk score 59/100" in st.policy_allocation(high).lines[0].reason


def test_lowered_level_uses_the_middle_of_its_range():
    p = ob.build_profile(ob.PERSONAS["Mateo"])
    lower = pf.with_level(p, 2, "test")
    pos, why = pf.equity_position(lower)
    assert pos == 0.5 and "middle" in why


def test_goal_amounts_must_match_savings_and_investments():
    o = ob.PERSONAS["Amira"]
    too_much = ob.Onboarding(o.financials, [gl.GoalSpec("Big", "retirement", 20, 900_000, 500_000, 0)], o.tolerance, o.preferences)
    assert "GOALS_EXCEED_ASSETS" in {f.code for f in ob.build_profile(too_much).flags}
    too_little = ob.Onboarding(o.financials, [gl.GoalSpec("Small", "retirement", 20, 900_000, 5_000, 0)], o.tolerance, o.preferences)
    flags = {f.code: f for f in ob.build_profile(too_little).flags}
    assert flags["UNASSIGNED_SAVINGS"].severity == "info" and "$50,000" in flags["UNASSIGNED_SAVINGS"].message
    assert ob.assigned_amount(o) == o.financials.cash_savings + o.financials.investments
