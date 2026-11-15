"""Return forecast for crypto and gold: no look-ahead, honest scoring, rating scale."""

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("sklearn")
from wealthpilot import forecast as fc  # noqa: E402


def frame(target_fn, n=150, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    df = pd.DataFrame(rng.normal(0, 1, (n, len(fc.FEATURES))), index=idx, columns=fc.FEATURES)
    df["target"] = target_fn(df, rng)
    df.iloc[-fc.HORIZON:, df.columns.get_loc("target")] = np.nan     # the last 3 targets are not known yet
    return df


@pytest.mark.parametrize("r2, label", [(0.08, "Very good"), (0.03, "Good"), (0.01, "Medium"), (-0.02, "Bad"),
                                       (-0.30, "Very bad"), (None, "Not enough data")])
def test_rating_scale(r2, label):
    assert fc.rate(r2)["label"] == label


def test_a_real_signal_is_found_out_of_sample():
    df = frame(lambda d, rng: 0.5 * d["mom_1m"] + rng.normal(0, 0.3, len(d)))
    pred = fc.walk_forward(df)
    assert fc.score(pred, "ridge")["r2_oos"] > 0.5
    assert fc.score(pred, "gradient_boosting")["r2_oos"] > 0.3
    assert fc.score(pred, "ridge")["dm_p"] < 0.05


def test_pure_noise_is_not_rated_good():
    df = frame(lambda d, rng: rng.normal(0, 1, len(d)), seed=3)
    pred = fc.walk_forward(df)
    assert fc.score(pred, "gradient_boosting")["rating"]["label"] not in {"Good", "Very good"}


def test_walk_forward_never_trains_on_unknown_targets(monkeypatch):
    df = frame(lambda d, rng: rng.normal(0, 1, len(d)))
    seen = []

    class Spy:
        def fit(self, X, y):
            seen.append((X.index.max(), len(y)))
            return self

        def predict(self, X):
            seen[-1] = seen[-1] + (X.index[0],)
            return np.zeros(len(X))

    monkeypatch.setattr(fc, "make_model", lambda kind: Spy())
    fc.walk_forward(df, kinds=("spy",))
    for last_train, _, predicted in seen:
        assert last_train <= predicted - pd.offsets.MonthEnd(fc.HORIZON), "targets ending after the prediction date leaked"


def test_features_use_the_past_only():
    idx = pd.bdate_range("2012-01-02", "2020-12-31")
    px = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0.0003, 0.01, len(idx)))), index=idx)
    macro = pd.DataFrame(0.0, index=px.resample("ME").last().index, columns=["real_rate", "d_real_rate_3m", "usd_3m", "oil_3m", "infl_us"])
    full = fc.features(px, macro)
    cut = fc.features(px.loc[:"2018-06-30"], macro.loc[:"2018-06-30"])
    common = cut.index[cut.index <= "2018-06-30"]
    pd.testing.assert_frame_equal(full.loc[common, fc.FEATURES], cut.loc[common, fc.FEATURES])


def test_diebold_mariano_identical_errors():
    e = np.random.default_rng(0).normal(0, 1, 50)
    stat, p = fc.diebold_mariano(e, e)
    assert np.isnan(stat) or abs(stat) < 1e-9


def test_artifact_in_repository_is_complete():
    art = fc.load_artifact()
    if art is None:
        pytest.skip("models/asset_forecast.json not trained")
    for t, a in art["assets"].items():
        m = a["models"]["gradient_boosting"]
        assert {"r2_oos", "rating", "hit_rate", "dm_p"} <= set(m)
        assert a["usable"] == (m["rating"]["label"] in {"Good", "Very good"} and m["dm_p"] < fc.SIGNIFICANCE)
        assert a["forecast"]["low"] < a["forecast"]["return"] < a["forecast"]["high"]
