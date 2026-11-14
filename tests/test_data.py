"""Checks on the real starter dataset (skipped when the CSVs are not present)."""

import pandas as pd
import pytest

from tests.conftest import requires_starter
from wealthpilot import data

pytestmark = requires_starter


def test_prices_cad_cover_universe_on_one_calendar():
    px = data.load_prices_cad()
    assert set(px.columns) == set(data.load_universe().index)
    assert (px.index.dayofweek < 5).all()
    assert px.loc["2021-11-15":].notna().all().all()


def test_usd_assets_are_converted_with_boc_rate():
    raw = data.align(data.load_prices())
    fx = data.load_fx(index=raw.index)
    cad = data.load_prices_cad()
    d = pd.Timestamp("2024-06-03")
    assert cad.loc[d, "SPY"] == pytest.approx(raw.loc[d, "SPY"] * fx.loc[d])
    assert cad.loc[d, "RY.TO"] == pytest.approx(raw.loc[d, "RY.TO"])


def test_spy_2022_return_matches_reference():
    # Reference computed independently from prices_daily.csv: -18.6% in USD over 2022.
    spy = data.load_prices()["SPY"].loc["2022"].dropna()
    assert spy.iloc[-1] / spy.iloc[0] - 1 == pytest.approx(-0.186, abs=0.001)


def test_monthly_cpi_is_point_in_time():
    cpi = data.load_macro("STATIC_TOTALCPICHANGE")
    raw = data.load_macro("STATIC_TOTALCPICHANGE", point_in_time=False)
    assert raw.index[-1] == pd.Timestamp("2026-09-01")
    assert cpi.index[-1] == pd.Timestamp("2026-11-01")  # September CPI usable from November 1


def test_risk_free_from_overnight_rate():
    idx = pd.bdate_range("2026-11-02", "2026-11-12")
    rf = data.risk_free_per_period(idx)
    assert (1 + rf.iloc[-1]) ** 252 - 1 == pytest.approx(0.025, abs=1e-9)
