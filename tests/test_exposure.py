import pytest

from wealthpilot import exposure as ex


def codes(alerts):
    return {a.code for a in alerts}


def test_exposure_by_currency(synthetic_universe):
    s = ex.exposure({"AAA": 0.3, "BBB": 0.3, "BND": 0.4}, synthetic_universe, "currency")
    assert s["USD"] == pytest.approx(0.6) and s["CAD"] == pytest.approx(0.4)


def test_risk_shares_sum_to_one(synthetic_prices):
    w = {"AAA": 0.4, "BBB": 0.3, "CCC": 0.1, "BND": 0.2}
    rd = ex.risk_decomposition(w, ex.covariance(synthetic_prices, w))
    assert rd["risk_share"].sum() == pytest.approx(1.0)
    assert rd.index[0] == "CCC"  # 10% of the money, most of the risk


def test_alerts_fire_on_concentrated_portfolio(synthetic_prices, synthetic_universe):
    w = {"AAA": 0.45, "BBB": 0.05, "CCC": 0.10, "BND": 0.40}
    found = codes(ex.alerts(w, synthetic_universe, synthetic_prices))
    assert {"SINGLE_SECURITY", "SECTOR", "CRYPTO", "RISK_CONCENTRATION"} <= found


def test_correlated_pair_detected(synthetic_prices, synthetic_universe):
    px = synthetic_prices.copy()
    px["BBB"] = px["AAA"] * 1.01  # moves exactly with AAA
    found = ex.alerts({"AAA": 0.05, "BBB": 0.05, "BND": 0.90}, synthetic_universe, px)
    assert "CORRELATED_PAIR" in codes(found)


def test_no_alerts_on_bond_only_portfolio(synthetic_prices, synthetic_universe):
    found = ex.alerts({"BND": 1.0}, synthetic_universe, synthetic_prices,
                      limits=ex.Limits(max_currency=1.0))
    assert found == []


def test_diversification_ratio_above_one(synthetic_prices):
    w = {"AAA": 0.5, "BND": 0.5}
    stats = ex.diversification_stats(w, ex.covariance(synthetic_prices, w))
    assert stats["diversification_ratio"] > 1.0
    assert stats["effective_positions"] == pytest.approx(2.0)
