"""Market-timing check: costs, execution delay, no look-ahead, threshold chosen on training data only, gate."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
from wealthpilot import timing as tm  # noqa: E402


def test_engine_rule_holds_five_days():
    pos = tm.positions(np.array([0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]), 0.5)
    assert pos.tolist() == [0, 1, 1, 1, 1, 1, 0, 0]


def test_backtest_has_one_day_delay_and_charges_each_side():
    pos = np.array([1.0, 1.0, 0.0, 0.0])
    ret_next = np.array([0.10, 0.10, 0.10, 0.10])
    d = tm.backtest(pos, ret_next, cost=0.01)
    # decided at day 0, held over days 1 and 2; entry on day 1 and exit on day 3 each cost 1%
    assert d.tolist() == pytest.approx([0.0, 0.10 - 0.01, 0.10, -0.01])


def test_holding_pays_one_purchase_and_one_sale():
    d = tm.hold_returns(np.array([0.0, 0.0, 0.0]), cost=0.0005)
    assert d.sum() == pytest.approx(-0.001)


def _ohlcv(n=1500, seed=0):
    idx = pd.bdate_range("2005-01-03", periods=n)
    c = 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(0.0004, 0.012, n)))
    return pd.DataFrame({"Open": c * 0.999, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": np.random.default_rng(seed + 1).integers(1e6, 2e6, n).astype(float)}, index=idx)


def test_features_use_the_past_only():
    df = _ohlcv()
    vix = pd.Series(20 + np.random.default_rng(2).normal(0, 2, len(df)), index=df.index)
    full = tm.features(df, vix)
    cut = tm.features(df.iloc[:1000], vix.iloc[:1000])
    common = cut.index
    pd.testing.assert_frame_equal(full.loc[common, tm.FEATURES], cut.loc[common, tm.FEATURES])


def test_threshold_is_chosen_without_the_test_year(monkeypatch):
    df = _ohlcv(2600)
    vix = pd.Series(20.0, index=df.index) + np.random.default_rng(3).normal(0, 1, len(df))
    feat = tm.features(df, vix)
    seen = []
    real = tm.choose_threshold

    def spy(prob, ret_next, cost):
        seen.append(len(prob))
        return real(prob, ret_next, cost)

    monkeypatch.setattr(tm, "choose_threshold", spy)
    folds = tm.walk_forward(feat, 0.0005, first_year=2013)
    assert len(folds) == len(seen) > 0
    for year, n in zip(folds["year"], seen):
        assert n <= len(feat[feat.index < pd.Timestamp(year, 1, 1)]), "threshold picked with data from the test year"


def test_gate_requires_wins_and_significance():
    folds = pd.DataFrame({"year": range(2010, 2020), "strategy_sharpe": [1.0] * 8 + [0.0] * 2,
                          "hold_sharpe": [0.5] * 10, "strategy_total_return": [0.1] * 10, "hold_total_return": [0.05] * 10,
                          "strategy_time_invested": [0.5] * 10, "auc": [0.6] * 10})
    assert tm.summarize(folds)["usable"]
    folds["strategy_sharpe"] = [1.0] * 5 + [0.0] * 5
    assert not tm.summarize(folds)["usable"]


def test_artifact_and_advocate_challenge():
    from wealthpilot import advocate as adv, onboarding as ob
    art = tm.load_artifact()
    if art is None:
        pytest.skip("models/timing_model.json not trained")
    for t, a in art["assets"].items():
        s = a["scenarios"]["main"]["summary"]
        assert a["usable"] == (s["win_share_sharpe"] >= tm.USABLE_WIN_SHARE and s["p_value"] < tm.USABLE_P)
    c = adv.market_timing_challenge("QQQ", ob.build_profile(ob.PERSONAS["Amira"]), art)
    assert c.code == "MARKET_TIMING" and "yearly tests" in c.claim
    assert adv.market_timing_challenge("TSLA", ob.build_profile(ob.PERSONAS["Amira"]), art) is None
