import numpy as np
import pandas as pd
import pytest

from wealthpilot.data import DATA_DIR


@pytest.fixture
def bdays():
    return pd.bdate_range("2024-01-01", periods=260, name="date")


@pytest.fixture
def synthetic_prices(bdays):
    rng = np.random.default_rng(0)
    r = pd.DataFrame(rng.normal(0.0004, 0.01, (len(bdays), 4)), index=bdays, columns=["AAA", "BBB", "CCC", "BND"])
    r["CCC"] = rng.normal(0.0, 0.05, len(bdays))      # very volatile asset
    r["BND"] = rng.normal(0.0001, 0.002, len(bdays))  # quiet asset
    return 100 * (1 + r).cumprod()


@pytest.fixture
def synthetic_universe():
    return pd.DataFrame({
        "asset_class": ["equity", "equity", "crypto", "etf_bond"],
        "sector": ["Information Technology", "Information Technology", "Crypto asset", "Bonds"],
        "currency": ["USD", "USD", "USD", "CAD"],
    }, index=pd.Index(["AAA", "BBB", "CCC", "BND"], name="ticker"))


requires_starter = pytest.mark.skipif(
    not (DATA_DIR / "prices_daily.csv").exists(), reason="starter dataset not present in data/starter/"
)
