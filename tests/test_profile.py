import itertools
import random

import pandas as pd
import pytest

from tests.conftest import requires_starter
from wealthpilot import profile as pf
from wealthpilot.assumptions import RETURNS

AMIRA = dict(horizon="gt15", income_stability="stable", emergency_fund="3to6", wealth_share="25to50",
             dependents="none", drop_reaction="buy_more", range_choice="D", goal="max_growth",
             experience="intermediate", return_expectation="7to10")
MATEO = dict(horizon="5to10", income_stability="stable", emergency_fund="3to6", wealth_share="25to50",
             dependents="some", drop_reaction="hold", range_choice="B", goal="balanced",
             experience="intermediate", return_expectation="5to7")
ROBERT = dict(horizon="3to5", income_stability="stable", emergency_fund="gt6", wealth_share="50to75",
              dependents="none", drop_reaction="hold", range_choice="C", goal="preserve",
              experience="advanced", return_expectation="5to7")


def codes(items):
    return {i.code for i in items}


# ------------------------------------------------------------------ personas from the brief

def test_amira_aggressive_but_bounded():
    p = pf.build_profile(AMIRA, pf.Preferences(crypto="open", region="global", themes=("Information Technology",)))
    assert p.level == 5
    c = p.constraints
    assert c.equity_max < 1.0, "high risk is not 'anything goes': some non-equity remains"
    assert c.max_crypto == pf.LEVELS[5].max_crypto
    assert c.limits.max_single_security <= 0.15
    assert "EXPECTATION_GAP" in codes(p.flags)  # 8.5% expected vs ~5.8% planning assumption


def test_mateo_balanced_with_esg_exclusions():
    p = pf.build_profile(MATEO, pf.Preferences(esg="exclude", excluded_sectors=("Energy",), crypto="no"))
    assert p.level == 3
    assert p.constraints.max_crypto == 0.0
    assert "ESG_DATA_LIMIT" in codes(p.flags)


def test_robert_capped_by_horizon():
    p = pf.build_profile(ROBERT)
    assert p.level == 2, "3-5 year horizon caps the level"
    assert "HORIZON_CAP" in codes(p.flags)


# ------------------------------------------------------------------ scoring rules

def test_reasons_add_up_to_scores():
    p = pf.build_profile(MATEO)
    cap = sum(r.contribution for r in p.reasons if r.dimension == "capacity")
    tol = sum(r.contribution for r in p.reasons if r.dimension == "tolerance")
    assert cap == pytest.approx(p.capacity) and tol == pytest.approx(p.tolerance)


def test_level_follows_lower_of_capacity_and_tolerance():
    timid = dict(AMIRA, drop_reaction="sell_all", range_choice="A", goal="preserve")
    p = pf.build_profile(timid)
    assert p.tolerance < p.capacity and p.level == pf.level_from_score(p.tolerance)
    assert "CAPACITY_TOLERANCE_GAP" in codes(p.flags)


def test_missing_and_invalid_answers_rejected():
    with pytest.raises(ValueError):
        pf.build_profile({k: v for k, v in MATEO.items() if k != "goal"})
    with pytest.raises(ValueError):
        pf.build_profile(dict(MATEO, goal="get_rich"))


def test_no_experience_blocks_crypto():
    p = pf.build_profile(dict(AMIRA, experience="none"), pf.Preferences(crypto="open"))
    assert p.constraints.max_crypto == 0.0 and "CRYPTO_NO_EXPERIENCE" in codes(p.flags)


def test_no_emergency_fund_flagged():
    assert "NO_EMERGENCY_FUND" in codes(pf.build_profile(dict(MATEO, emergency_fund="none")).flags)


def test_graham_band_respected_for_middle_levels():
    for n in (2, 3, 4):
        assert 0.25 <= pf.LEVELS[n].equity_min < pf.LEVELS[n].equity_max <= 0.80


# ------------------------------------------------------------------ goal maths

def test_future_value_and_required_return_are_inverse():
    g = pf.Goal(current_amount=50_000, target_amount=120_000, years=10, monthly_contribution=200,
                target_in_todays_dollars=False)
    r = pf.required_return(g)
    assert pf.future_value(50_000, 200, 10, r) == pytest.approx(120_000, rel=1e-6)


def test_required_monthly_contribution_closes_the_gap():
    g = pf.Goal(current_amount=10_000, target_amount=100_000, years=15, target_in_todays_dollars=False)
    m = pf.required_monthly_contribution(g, 0.05)
    assert pf.future_value(10_000, m, 15, 0.05) == pytest.approx(100_000, rel=1e-9)


def test_unreachable_goal_suggests_saving_not_more_risk():
    goal = pf.Goal(current_amount=100_000, target_amount=250_000, years=5)
    p = pf.build_profile(ROBERT, goal=goal)
    assert p.level == 2  # unchanged
    assert not p.goal_analysis["reachable"]
    assert p.goal_analysis["monthly_contribution_needed"] > 0
    assert "GOAL_NOT_REACHABLE" in codes(p.flags)


def test_expected_return_uses_published_assumptions():
    e = pf.expected_return(3, home_share=0.5)
    eq = e["equity_share"]
    manual = eq * 0.5 * RETURNS["canadian_equity"] + eq * 0.5 * RETURNS["us_equity"] + (1 - eq) * RETURNS["fixed_income"]
    assert e["gross"] == pytest.approx(manual)


# ------------------------------------------------------------------ synthetic profiles (all combinations sampled)

ALL_ANSWERS = {q.id: [o.code for o in q.options] for q in pf.QUESTIONS}
PREFS = [pf.Preferences(crypto=c, region=r) for c in ("no", "small", "open") for r in pf.REGION_HOME_SHARE]


def random_profiles(n=600, seed=7):
    rng = random.Random(seed)
    for _ in range(n):
        yield {k: rng.choice(v) for k, v in ALL_ANSWERS.items()}, rng.choice(PREFS)


def test_invariants_on_synthetic_profiles():
    for answers, prefs in random_profiles():
        p = pf.build_profile(answers, prefs)
        c = p.constraints
        assert 1 <= p.level <= 5
        assert p.risk_score <= min(p.capacity, p.tolerance) + 1e-9
        assert p.level <= pf.HORIZON_LEVEL_CAP.get(answers["horizon"], 5)
        assert 0 <= c.equity_min < c.equity_max <= 0.95
        assert c.max_crypto <= pf.LEVELS[p.level].max_crypto
        if prefs.crypto == "no" or answers["experience"] == "none":
            assert c.max_crypto == 0.0


def test_longer_horizon_never_lowers_level():
    horizons = ALL_ANSWERS["horizon"]
    for answers, prefs in itertools.islice(random_profiles(seed=11), 200):
        levels = [pf.build_profile(dict(answers, horizon=h), prefs).level for h in horizons]
        assert levels == sorted(levels)


# ------------------------------------------------------------------ allocation checks

def test_check_allocation_on_synthetic_universe(synthetic_universe, synthetic_prices):
    p = pf.build_profile(ROBERT)
    v = pf.check_allocation({"AAA": 0.40, "CCC": 0.10, "BND": 0.50}, p, synthetic_universe, synthetic_prices)
    assert {"CRYPTO_ABOVE_LIMIT", "SINGLE_SECURITY"} <= codes(v)


@requires_starter
def test_robert_tsla_request_flagged_on_real_data():
    from wealthpilot import data
    u, px = data.load_universe(), data.load_prices_cad()
    p = pf.build_profile(ROBERT)
    prudent = {"XIU.TO": 0.20, "SPY": 0.15, "XBB.TO": 0.30, "ZST.TO": 0.20, "GLD": 0.05, "RY.TO": 0.05, "JNJ": 0.05}
    assert [x for x in pf.check_allocation(prudent, p, u, px) if x.severity == "warning"] == []
    with_tsla = {k: v * 0.7 for k, v in prudent.items()} | {"TSLA": 0.30}
    found = codes(pf.check_allocation(with_tsla, p, u, px))
    assert {"SINGLE_SECURITY", "RISK_CONCENTRATION"} <= found


@requires_starter
def test_mateo_energy_exclusion_on_real_data():
    from wealthpilot import data
    u = data.load_universe()
    p = pf.build_profile(MATEO, pf.Preferences(esg="exclude", excluded_sectors=("Energy",)))
    found = pf.check_allocation({"ESGV": 0.5, "XBB.TO": 0.45, "ENB.TO": 0.05}, p, u)
    assert "EXCLUDED_SECTOR" in codes(found) and "FUND_HOLDINGS_NOT_CHECKED" in codes(found)


def test_questionnaire_is_serializable():
    q = pf.questionnaire()
    assert len(q) == 10 and all(len(x["options"]) >= 3 for x in q)
    pd.DataFrame(q)  # flat enough for a UI table
