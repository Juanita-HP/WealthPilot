import importlib
import os
import sys

import numpy as np
import pandas as pd
import pytest

from wealthpilot import metrics as m


def test_cumulative_return_and_drawdown():
    v = [100, 120, 90, 130]
    assert m.cumulative_return(v) == pytest.approx(0.30)
    assert m.max_drawdown(v) == pytest.approx(0.25)  # 120 -> 90


def test_constant_returns_give_nan_sharpe():
    assert np.isnan(m.sharpe_ratio([0.01] * 10, 252))


def test_sharpe_matches_definition_with_risk_free():
    r = np.array([0.01, -0.02, 0.015, 0.003, -0.004])
    rf = 0.0001
    expected = (r - rf).mean() / (r - rf).std(ddof=1) * np.sqrt(252)
    assert m.sharpe_ratio(r, 252, rf) == pytest.approx(expected)
    # risk-free as a series of the same length
    assert m.sharpe_ratio(r, 252, np.full(5, rf)) == pytest.approx(expected)


def test_sortino_ignores_upside():
    up_only = np.array([0.01, 0.02, 0.03])
    assert np.isnan(m.sortino_ratio(up_only, 252))


def test_cagr_doubling_in_two_years():
    s = pd.Series([100.0, 200.0], index=pd.to_datetime(["2020-01-01", "2021-12-31"]))
    years = (s.index[1] - s.index[0]).days / m.DAYS_PER_YEAR
    assert m.cagr(s) == pytest.approx(2 ** (1 / years) - 1)


def test_real_return_fisher():
    assert m.real_return(0.05, 0.03) == pytest.approx(1.05 / 1.03 - 1)


def test_drawdown_episode_dates():
    idx = pd.bdate_range("2024-01-01", periods=6)
    s = pd.Series([100, 110, 80, 90, 111, 105], index=idx)
    ep = m.drawdown_episode(s)
    assert ep["peak_date"] == idx[1] and ep["trough_date"] == idx[2] and ep["recovery_date"] == idx[4]
    assert ep["drawdown"] == pytest.approx(80 / 110 - 1)


def test_calculate_all_with_risk_free_series():
    idx = pd.bdate_range("2024-01-01", periods=300)
    rng = np.random.default_rng(1)
    v = pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=idx)
    rf = pd.Series(0.0001, index=idx)
    res = m.calculate_all(v, 252, rf)
    r = v.pct_change().iloc[1:].to_numpy()
    assert res.sharpe_ratio == pytest.approx(m.sharpe_ratio(r, 252, 0.0001))
    assert res.mean_risk_free_annual == pytest.approx(1.0001 ** 252 - 1)


def _load_cpp():
    """The original C++ engine, if a build is on METRICS_CPP_PATH or importable."""
    path = os.environ.get("METRICS_CPP_PATH")
    if path and path not in sys.path:
        sys.path.insert(0, path)
    try:
        return importlib.import_module("metrics_cpp")
    except ImportError:
        return None


@pytest.mark.skipif(_load_cpp() is None, reason="C++ metrics engine not built (set METRICS_CPP_PATH)")
def test_numpy_port_matches_cpp_engine():
    cpp = _load_cpp()
    rng = np.random.default_rng(42)
    values = 100_000 * np.cumprod(1 + rng.normal(0.0004, 0.012, 1000))
    returns = list(values[1:] / values[:-1] - 1)
    ref = cpp.calculateAll(returns, list(values), 252)
    assert m.cumulative_return(values) == pytest.approx(ref.cumulative_return, rel=1e-12)
    assert m.period_volatility(returns) == pytest.approx(ref.period_volatility, rel=1e-12)
    assert m.annualized_volatility(returns, 252) == pytest.approx(ref.annualized_volatility, rel=1e-12)
    assert m.sharpe_ratio(returns, 252) == pytest.approx(ref.sharpe_ratio, rel=1e-12)
    assert m.max_drawdown(values) == pytest.approx(ref.max_drawdown, rel=1e-12)
