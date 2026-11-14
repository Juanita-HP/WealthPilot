import numpy as np
import pandas as pd
import pytest

from wealthpilot.portfolio import backtest, compare


def test_single_asset_buy_and_hold_tracks_price(synthetic_prices):
    res = backtest(synthetic_prices, {"AAA": 1.0}, rebalance=None)
    expected = 100_000 * synthetic_prices["AAA"] / synthetic_prices["AAA"].iloc[0]
    pd.testing.assert_series_equal(res.values, expected, check_names=False)


def test_without_rebalancing_weights_drift(synthetic_prices):
    res = backtest(synthetic_prices, {"AAA": 0.5, "CCC": 0.5}, rebalance=None)
    assert abs(res.weights["AAA"].iloc[-1] - 0.5) > 0.01


def test_rebalance_restores_targets_one_day_after_period_end(synthetic_prices):
    res = backtest(synthetic_prices, {"AAA": 0.6, "BND": 0.4}, rebalance="monthly", execution_delay=1)
    reb = res.trades.iloc[1:]
    first = reb.iloc[0]
    assert first["decision_date"] == pd.Timestamp("2024-01-31")
    assert first["execution_date"] == pd.Timestamp("2024-02-01")
    for d in reb["execution_date"]:
        assert res.weights.loc[d, "AAA"] == pytest.approx(0.6)


def test_value_is_continuous_through_rebalance_without_costs(synthetic_prices):
    res = backtest(synthetic_prices, {"AAA": 0.5, "BBB": 0.5}, rebalance="monthly")
    no_reb = backtest(synthetic_prices, {"AAA": 0.5, "BBB": 0.5}, rebalance=None)
    d = res.trades["execution_date"].iloc[1]
    prev = res.values.index[res.values.index.get_loc(d) - 1]
    assert res.values.loc[prev] == pytest.approx(no_reb.values.loc[prev])


def test_transaction_costs_reduce_value(synthetic_prices):
    free = backtest(synthetic_prices, {"AAA": 0.5, "CCC": 0.5}, rebalance="monthly")
    costly = backtest(synthetic_prices, {"AAA": 0.5, "CCC": 0.5}, rebalance="monthly", transaction_cost=0.001)
    assert costly.total_costs > 100  # at least the initial purchase cost
    assert costly.values.iloc[-1] < free.values.iloc[-1]


def test_annual_fee_drag_on_flat_prices(bdays):
    flat = pd.DataFrame({"X": 50.0}, index=bdays[:253])
    res = backtest(flat, {"X": 1.0}, rebalance=None, annual_fee=0.01)
    assert res.values.iloc[-1] == pytest.approx(99_000, rel=1e-9)
    assert res.total_fees == pytest.approx(1_000, rel=1e-9)


@pytest.mark.parametrize("weights, err", [
    ({"AAA": 0.5, "BBB": 0.4}, ValueError),
    ({"AAA": 1.2, "BBB": -0.2}, ValueError),
    ({"ZZZ": 1.0}, KeyError),
])
def test_invalid_weights(synthetic_prices, weights, err):
    with pytest.raises(err):
        backtest(synthetic_prices, weights)


def test_compare_uses_common_start(synthetic_prices):
    px = synthetic_prices.copy()
    px.loc[:"2024-03-01", "CCC"] = np.nan  # CCC starts later
    results, table = compare(px, {"a": {"AAA": 1.0}, "b": {"AAA": 0.5, "CCC": 0.5}}, rebalance=None)
    assert results["a"].values.index[0] == results["b"].values.index[0] == pd.Timestamp("2024-03-04")
    assert set(table.index) == {"a", "b"}
