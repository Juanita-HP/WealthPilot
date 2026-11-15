import pandas as pd
import pytest

from tests.conftest import requires_starter
from tests.test_profile import AMIRA, MATEO, ROBERT
from wealthpilot import profile as pf
from wealthpilot import strategist as st
from wealthpilot import time_machine as tm
from wealthpilot import validation as va

PERSONAS = {
    "amira": (AMIRA, pf.Preferences(crypto="open", themes=("Information Technology",))),
    "mateo": (MATEO, pf.Preferences(esg="exclude", excluded_sectors=("Energy",))),
    "robert": (ROBERT, pf.Preferences()),
}


@pytest.mark.parametrize("name", PERSONAS)
def test_policy_weights_sum_to_one_and_follow_reasons(name):
    a, prefs = PERSONAS[name]
    p = pf.build_profile(a, prefs)
    al = st.policy_allocation(p)
    assert sum(al.weights.values()) == pytest.approx(1.0)
    assert all(w > 0 for w in al.weights.values())
    assert all(ln.reason for ln in al.lines)
    by_ticker = {}
    for ln in al.lines:
        by_ticker[ln.ticker] = by_ticker.get(ln.ticker, 0) + ln.weight
    for t, w in al.weights.items():
        assert w == pytest.approx(by_ticker[t], abs=1e-9), "every weight comes from a reasoned line"


def test_equity_share_inside_level_range_for_every_level():
    for level in range(1, 6):
        p = va.profile_at_level(level)
        for pos in (0.0, 0.5, 1.0):
            w = st.policy_allocation(p, equity_position=pos).weights
            eq = sum(w.get(t, 0) for t in ("XIU.TO", "SPY", "ESGV", "QQQ", "XEF.TO", "XEC.TO"))
            assert p.constraints.equity_min - 1e-9 <= eq <= p.constraints.equity_max + 1e-9


def test_preferences_change_the_allocation():
    esg = st.policy_allocation(pf.build_profile(MATEO, pf.Preferences(esg="exclude"))).weights
    plain = st.policy_allocation(pf.build_profile(MATEO)).weights
    assert "ESGV" in esg and "SPY" not in esg and "SPY" in plain
    no_crypto = st.policy_allocation(pf.build_profile(AMIRA, pf.Preferences(crypto="no"))).weights
    assert "BTC-USD" not in no_crypto


def test_crypto_uses_half_the_limit():
    p = pf.build_profile(AMIRA, pf.Preferences(crypto="open"))
    assert st.policy_allocation(p).weights["BTC-USD"] == pytest.approx(p.constraints.max_crypto / 2)


def test_reasons_quote_no_numbers_without_data():
    al = st.policy_allocation(pf.build_profile(AMIRA, pf.Preferences(crypto="open")))
    assert not any("correlation" in ln.reason for ln in al.lines)


def test_inverse_vol_uses_only_past_data(synthetic_prices):
    # build a price frame with the tickers the strategist needs
    cols = ["XIU.TO", "SPY", "ESGV", "QQQ", "XBB.TO", "AGG", "ZST.TO", "GLD", "BTC-USD", "ETH-USD"]
    px = pd.concat([synthetic_prices] * 3, axis=1).iloc[:, :len(cols)]
    px.columns = cols
    p = pf.build_profile(MATEO)
    cut = px.index[150]
    a = st.inverse_vol_allocation(p, px, end=cut, lookback_years=1).weights
    shocked = px.copy()
    shocked.loc[cut + pd.Timedelta(days=1):, "SPY"] *= 5  # future change must not matter
    b = st.inverse_vol_allocation(p, shocked, end=cut, lookback_years=1).weights
    assert a == pytest.approx(b)


def test_revise_tolerance_steps_down_only_when_needed():
    assert tm.revise_tolerance(ROBERT, would_hold=True) == ROBERT
    assert tm.revise_tolerance(ROBERT, would_hold=False)["range_choice"] == "B"
    assert tm.revise_tolerance(dict(ROBERT, range_choice="A"), would_hold=False)["range_choice"] == "A"


def test_inflation_erosion():
    e = tm.inflation_erosion(100_000, 10, rates=(0.02,))[0]
    assert e["real_value"] == pytest.approx(100_000 / 1.02 ** 10)


def test_shock_is_weighted_sum(synthetic_universe):
    w = {"AAA": 0.5, "BND": 0.4, "CCC": 0.1}
    s = tm.shock(w, synthetic_universe, 10_000, "equity_crash")
    moves = tm.SHOCKS["equity_crash"]["moves"]
    assert s["portfolio_return"] == pytest.approx(0.5 * moves["equity"] + 0.4 * moves["bond"] + 0.1 * moves["crypto"])
    assert s["kind"] == "hypothetical"


@requires_starter
def test_replay_on_real_data_in_dollars():
    from wealthpilot import data
    px = data.load_prices_cad()
    p = pf.build_profile(ROBERT)
    w = st.policy_allocation(p, px).weights
    r = tm.replay(w, px, p, 150_000)
    assert r.worst_drawdown["trough_date"].startswith("2022")
    assert r.worst_drawdown["dollars_lost"] == pytest.approx(r.worst_drawdown["peak_value"] - r.worst_drawdown["trough_value"])
    assert "Would you have held on?" in r.question
    assert r.calendar_years[2022] < 0
    assert -r.worst_12_months["return"] < p.constraints.worst_year_accepted


@requires_starter
def test_level_ladder_risk_increases_with_level():
    from wealthpilot import data
    lad = va.level_ladder(data.load_prices_cad())
    assert lad["volatility"].is_monotonic_increasing
    assert lad["max_drawdown"].is_monotonic_increasing
    assert lad["equity_share"].is_monotonic_increasing


@requires_starter
def test_walk_forward_uses_past_only_and_reports_every_year():
    from wealthpilot import data
    df, summary = va.walk_forward_sleeves(pf.build_profile(MATEO), data.load_prices_cad())
    assert summary["test_years"] == len(df) >= 3
    for year, row in df.iterrows():
        assert pd.Timestamp(row["estimated_to"]).year == year - 1
