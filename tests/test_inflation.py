from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from wealthpilot import inflation as inf

HISTORY = Path(__file__).resolve().parent.parent / "data" / "external" / "macro_history.csv"
requires_history = pytest.mark.skipif(not HISTORY.exists(), reason="run scripts/fetch_macro_history.py")


def test_ridge_matches_normal_equations():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(80, 4))
    y = X @ np.array([1.0, -2.0, 0.5, 0.0]) + rng.normal(0, 0.1, 80) + 3.0
    lam = 5.0
    m = inf.Ridge(lam).fit(X, y)
    Z = (X - X.mean(0)) / X.std(0)
    w = np.linalg.solve(Z.T @ Z + lam * np.eye(4), Z.T @ (y - y.mean()))
    assert np.allclose(m.weights, w) and m.bias == pytest.approx(y.mean())
    assert np.allclose(inf.Ridge(0.0).fit(X, y).predict(X), Z @ np.linalg.lstsq(Z, y - y.mean(), rcond=None)[0] + y.mean())


def test_scaler_comes_from_training_rows_only():
    X_train = np.array([[1.0], [2.0], [3.0]])
    m = inf.Ridge(1.0).fit(X_train, np.array([1.0, 2.0, 3.0]))
    assert m.mean[0] == pytest.approx(2.0)
    m.predict(np.array([[100.0]]))  # predicting does not refit the scaler
    assert m.mean[0] == pytest.approx(2.0)


def test_mean_reversion_coefficient():
    yoy = np.array([4.0, 0.0, 3.0, 1.0])
    change = 0.5 * (inf.TARGET - yoy)
    assert inf.fit_mean_reversion(yoy, change) == pytest.approx(0.5)
    assert inf.fit_mean_reversion(yoy, -3 * (inf.TARGET - yoy)) == 0.0  # clipped


def test_choose_lambda_returns_scores_for_every_candidate():
    rng = np.random.default_rng(1)
    X, y = rng.normal(size=(120, 3)), rng.normal(size=120)
    best, scores = inf.choose_lambda(X, y, h=3)
    assert set(scores) == set(inf.LAMBDAS) and best == min(scores, key=scores.get)


@requires_history
def test_walk_forward_has_no_look_ahead():
    hist = pd.read_csv(HISTORY, parse_dates=["date"])
    panel = inf.monthly_panel(hist)
    h, origin = 6, pd.Timestamp("2015-06-01")
    base = inf.walk_forward(panel.loc[:"2016-12-01"], h, first_origin="2015-06-01").loc[origin]
    tampered = panel.copy()
    tampered.loc[origin + pd.DateOffset(months=1):] *= 3  # change the future only
    after = inf.walk_forward(tampered.loc[:"2016-12-01"], h, first_origin="2015-06-01").loc[origin]
    for m in inf.METHODS:
        assert after[m] == pytest.approx(base[m]), m


@requires_history
def test_forecast_respects_publication_dates():
    hist = pd.read_csv(HISTORY, parse_dates=["date"])
    art = inf.load() if inf.ARTIFACT.exists() else inf.train(hist, horizons=(3,))
    f_before = inf.forecast(hist, art, 3, as_of="2026-10-31")
    f_after = inf.forecast(hist, art, 3, as_of="2026-11-01")
    assert f_before.origin_month == "2026-08-01"   # September CPI not yet published
    assert f_after.origin_month == "2026-09-01"


@requires_history
def test_artifact_reproduces_and_reports_all_methods():
    hist = pd.read_csv(HISTORY, parse_dates=["date"])
    art = inf.train(hist, horizons=(3,))
    spec = art["horizons"]["3"]
    assert set(spec["evaluation"]["methods"]) == set(inf.METHODS)
    assert spec["method_used"] == spec["evaluation"]["best_method"]
    panel = inf.supervised(inf.monthly_panel(hist), 3).dropna(subset=list(inf.FEATURES) + ["target"])
    m = inf.Ridge(spec["lambda"]).fit(panel[list(inf.FEATURES)].to_numpy(), panel["target"].to_numpy())
    assert np.allclose(m.weights, spec["weights"])
    cov = spec["evaluation"]["methods"][spec["method_used"]]["interval_coverage"]
    assert 0.65 <= cov <= 0.95, "80% intervals should be roughly calibrated"
