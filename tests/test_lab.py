import importlib
import os
import sys

import numpy as np
import pandas as pd
import pytest

from tests.conftest import requires_starter
from tests.test_profile import AMIRA, ROBERT
from wealthpilot import lab
from wealthpilot import profile as pf


@pytest.fixture
def close():
    idx = pd.bdate_range("2020-01-01", periods=900)
    rng = np.random.default_rng(3)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0.0003, 0.015, len(idx))), index=idx)


ta = pytest.importorskip("ta", reason="ta not installed; indicator cross-check skipped")


def test_rsi_matches_ta(close):
    ref = ta.momentum.RSIIndicator(close=close, window=14).rsi()
    pd.testing.assert_series_equal(lab.rsi(close, 14), ref, check_names=False, atol=1e-9)


def test_bollinger_matches_ta(close):
    b = ta.volatility.BollingerBands(close=close, window=20, window_dev=2)
    lo, mid, hi = lab.bollinger(close, 20, 2)
    pd.testing.assert_series_equal(lo, b.bollinger_lband(), check_names=False, atol=1e-9)
    pd.testing.assert_series_equal(hi, b.bollinger_hband(), check_names=False, atol=1e-9)


def test_macd_matches_ta(close):
    ref = ta.trend.MACD(close=close, window_fast=12, window_slow=26, window_sign=9)
    line, sig = lab.macd(close, 12, 26, 9)
    pd.testing.assert_series_equal(line, ref.macd(), check_names=False, atol=1e-9)
    pd.testing.assert_series_equal(sig, ref.macd_signal(), check_names=False, atol=1e-9)


def _cpp():
    path = os.environ.get("METRICS_CPP_PATH")
    if path and path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("metrics_cpp")
    except ImportError:
        return None


@pytest.mark.skipif(_cpp() is None, reason="C++ engine not built (set METRICS_CPP_PATH)")
def test_backtester_matches_cpp_engine(close):
    cpp = _cpp()
    pos = lab.sig_ma_crossover(close, 10, 50)
    costs = lab.Costs(commission=5.0, slippage=0.001)
    ours = lab.run(close, pos, 100_000, costs, execution_delay=1)
    trades = (pos - pos.shift(fill_value=0)).shift(1, fill_value=0).astype(int).tolist()
    ref = cpp.runBacktest(close.tolist(), trades, 100_000, 5.0, 0.001)
    assert np.allclose(ours["value"].to_numpy(), ref.total_values, rtol=1e-12)
    assert ours["shares"].tolist() == list(ref.shares)


def test_buy_and_hold_value(close):
    bt = lab.run(close, lab.sig_buy_hold(close), 10_000, lab.Costs(0, 0), execution_delay=0)
    shares = int(10_000 / close.iloc[0])
    assert bt["value"].iloc[-1] == pytest.approx(10_000 - shares * close.iloc[0] + shares * close.iloc[-1])


def test_signal_executes_next_day(close):
    pos = pd.Series(0, index=close.index)
    pos.iloc[100:] = 1
    bt = lab.run(close, pos, 10_000, lab.Costs(0, 0), execution_delay=1)
    assert bt["shares"].iloc[100] == 0 and bt["shares"].iloc[101] > 0


def test_signals_are_causal(close):
    """Changing future prices must not change today's position."""
    for name, spec in lab.STRATEGIES.items():
        a = spec.func(close, **spec.defaults)
        future = close.copy()
        future.iloc[600:] *= 2
        b = spec.func(future, **spec.defaults)
        assert (a.iloc[:600] == b.iloc[:600]).all(), name


def test_evaluate_always_reports_buy_hold_and_oos(close):
    r = lab.evaluate(close, "rsi", "TEST")
    assert r.buy_hold_out_of_sample and r.out_of_sample
    assert r.combinations_tested == len(list(lab.combinations(lab.STRATEGIES["rsi"])))
    assert {f["code"] for f in r.findings} & {"LOSES_TO_BUY_HOLD_OOS", "BEATS_BUY_HOLD_OOS"}
    assert r.assumptions["current_signal"].startswith("not provided")


def test_guided_mode_does_not_optimize(close):
    r = lab.evaluate(close, "ma_crossover", profile=pf.build_profile(dict(ROBERT, experience="beginner")))
    assert r.mode == "guided" and r.combinations_tested == 0
    assert r.params == lab.STRATEGIES["ma_crossover"].defaults
    assert lab.lab_mode(pf.build_profile(AMIRA)) == "full"


def test_walk_forward_reports_each_fold(close):
    wf = lab.walk_forward(close, "ma_crossover", folds=4)
    assert wf["n_folds"] == 3 and len(wf["folds"]) == 3


@requires_starter
def test_lab_on_tsla():
    from wealthpilot.data import load_prices
    r = lab.evaluate(load_prices()["TSLA"], "rsi", "TSLA", profile=pf.build_profile(ROBERT))
    assert r.mode == "full" and r.combinations_tested > 100
    assert r.split_date.startswith("2025")


def test_never_invested_is_not_reported_as_a_win(close):
    r = lab.evaluate(close, "rsi", params={"window": 14, "lower": 0, "upper": 70})  # RSI never below 0
    codes = {f["code"] for f in r.findings}
    assert "NO_POSITION_OOS" in codes and "BEATS_BUY_HOLD_OOS" not in codes
