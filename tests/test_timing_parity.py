"""The timing features are the backtesting engine's: compare them with the engine's own strategy code.

Runs only when the engine is available locally: BACKTESTING_ENGINE_PATH=<path to backtesting-engine/src>
(plus the `ta` package and data/external/timing_prices.csv). Same idea as METRICS_CPP_PATH for the C++ metrics.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

ENGINE = os.environ.get("BACKTESTING_ENGINE_PATH")
pytestmark = pytest.mark.skipif(not ENGINE, reason="set BACKTESTING_ENGINE_PATH to the engine's src/ folder")


def test_features_match_the_engine():
    pytest.importorskip("ta")
    sys.path.insert(0, ENGINE)
    from strategies.Atr import Atr
    from strategies.BollingerBands import BollingerBands
    from strategies.BreakoutMomentum import BreakoutMomentum
    from strategies.MaCrossover import MaCrossover
    from strategies.Rsi import Rsi
    from wealthpilot import timing as tm
    try:
        p = tm.load_prices()
    except FileNotFoundError:
        pytest.skip("run scripts/fetch_timing_history.py first")
    df, vix = tm.ohlcv(p, "QQQ"), tm.ohlcv(p, tm.VIX)["Close"]
    ours = tm.features(df, vix)
    theirs = pd.concat([MaCrossover(50, 200).generateFeatures(df), Rsi(14, 30, 70).generateFeatures(df),
                        BollingerBands(20, 2).generateFeatures(df), BreakoutMomentum(20, 20).generateFeatures(df),
                        Atr(14).generateFeatures(df)], axis=1, sort=True).dropna()
    common = ours.index.intersection(theirs.index)[300:]       # skip the indicators' warm-up
    for col in theirs.columns:
        np.testing.assert_allclose(ours.loc[common, col].astype(float), theirs.loc[common, col].astype(float),
                                   rtol=1e-5, atol=1e-6, err_msg=col)
