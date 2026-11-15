"""Return forecast for assets with no statements and no planning assumption (crypto, gold), tested honestly.

Question: can a model predict the next 3 months' return of Bitcoin, Ether or gold better than simply using the
historical average? Most research on asset returns says it rarely can (Welch and Goyal, 2008), so the answer is
measured, shown to the investor, and only used for the gauge if it clearly passes.

Design
------
* Monthly observations (month-end). Target: log return over the next 3 months.
* Features known at month-end, macro series with their publication lag (``data.load_macro_history``):
  momentum over 1, 3, 6 and 12 months; 3-month volatility; distance from the 12-month high; U.S. real rate
  (10-year Treasury minus CPI inflation) and its 3-month change; 3-month change of the broad dollar index and
  of oil; U.S. inflation.
* Models: gradient boosting (shallow trees, strong regularization: little data) as the main model, ridge
  regression as a linear comparison.
* Baselines: historical average of past targets (the benchmark of the out-of-sample R²), zero, and
  "the last 3 months repeat".
* Walk-forward: at each month the models are refitted on the past only; samples whose 3-month target is not
  yet known are purged. The first predictions start after 36 months of history.
* Score: out-of-sample R² = 1 - SSE(model) / SSE(historical average). Above 0 the model beats the average,
  below 0 it does worse. Also the share of months where the direction was right, and a Diebold-Mariano test
  (Newey-West variance, 2 lags for the overlapping targets) of the model against the average.
* Rating of the R² (3-month horizon): very good from 5%, good from 2%, medium from 0%, bad down to -5%,
  very bad below. For context, 0.5% a month is considered economically useful for stock indexes.
* The gauge uses the forecast only if the rating is good or very good AND the test is significant at 10%.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import data

ASSETS = {"BTC-USD": "Bitcoin", "ETH-USD": "Ether", "GLD": "Gold (SPDR Gold Shares)"}
LONG_PRICES = data.EXTERNAL_DIR / "long_prices.csv"
ARTIFACT = Path(os.environ.get("WEALTHPILOT_FORECAST_PATH",
                               Path(__file__).resolve().parent.parent / "models" / "asset_forecast.json"))
HORIZON = 3          # months
MIN_TRAIN = 36       # months of history before the first prediction
FEATURES = ["mom_1m", "mom_3m", "mom_6m", "mom_12m", "vol_3m", "dd_12m", "real_rate", "d_real_rate_3m",
            "usd_3m", "oil_3m", "infl_us"]
FEATURE_LABEL = {"mom_1m": "1-month price trend", "mom_3m": "3-month price trend", "mom_6m": "6-month price trend",
                 "mom_12m": "12-month price trend", "vol_3m": "3-month volatility", "dd_12m": "Distance from 12-month high",
                 "real_rate": "U.S. real interest rate", "d_real_rate_3m": "Change in the real rate (3 months)",
                 "usd_3m": "U.S. dollar strength (3 months)", "oil_3m": "Oil price (3 months)", "infl_us": "U.S. inflation"}
RATING = [(0.05, "Very good", "green"), (0.02, "Good", "green"), (0.0, "Medium", "yellow"),
          (-0.05, "Bad", "red"), (-math.inf, "Very bad", "red")]
SIGNIFICANCE = 0.10


def rate(r2: float | None) -> dict:
    if r2 is None or not np.isfinite(r2):
        return {"label": "Not enough data", "tone": "grey"}
    label, tone = next((lbl, tone) for th, lbl, tone in RATING if r2 >= th)
    return {"label": label, "tone": tone}


# ----------------------------------------------------------------------------- data


def load_long_prices(path: Path | None = None) -> pd.DataFrame:
    path = path or LONG_PRICES
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/fetch_long_history.py.")
    p = pd.read_csv(path, parse_dates=["date"])
    return p.pivot(index="date", columns="ticker", values="adj_close").sort_index()


def _macro_monthly(month_ends: pd.DatetimeIndex) -> pd.DataFrame:
    """Macro values as they were known at each month-end (publication lags applied)."""
    def asof(sid):
        s = data.load_macro_history(sid, point_in_time=True).dropna()
        return s.reindex(s.index.union(month_ends)).ffill().reindex(month_ends)
    cpi = data.load_macro_history("CPIAUCSL", point_in_time=False).dropna()
    infl = (cpi / cpi.shift(12) - 1) * 100
    infl.index = infl.index + pd.offsets.MonthBegin(2)               # published about six weeks later
    infl = infl.reindex(infl.index.union(month_ends)).ffill().reindex(month_ends)
    y10 = asof("DGS10")
    usd = asof("DTWEXBGS")
    oil = asof("DCOILWTICO")
    real = y10 - infl
    return pd.DataFrame({"real_rate": real, "d_real_rate_3m": real - real.shift(3),
                         "usd_3m": np.log(usd / usd.shift(3)), "oil_3m": np.log(oil / oil.shift(3)),
                         "infl_us": infl}, index=month_ends)


def features(px: pd.Series, macro: pd.DataFrame | None = None) -> pd.DataFrame:
    """Monthly features and the 3-month-ahead target for one asset (daily prices in)."""
    px = px.dropna()
    px = px[px > 0]
    m = px.resample("ME").last().dropna()
    logp = np.log(m)
    daily = np.log(px).diff().dropna()
    per_year = 365 if (px.index.dayofweek >= 5).any() else 252      # crypto trades every day
    vol = daily.rolling(int(per_year / 4)).std().resample("ME").last() * math.sqrt(per_year)
    hi12 = px.rolling(per_year, min_periods=int(per_year * 0.8)).max().resample("ME").last()
    df = pd.DataFrame({
        "mom_1m": logp.diff(1), "mom_3m": logp.diff(3), "mom_6m": logp.diff(6), "mom_12m": logp.diff(12),
        "vol_3m": vol.reindex(m.index), "dd_12m": (m / hi12.reindex(m.index) - 1),
    }, index=m.index)
    macro = macro if macro is not None else _macro_monthly(m.index)
    df = df.join(macro.reindex(m.index))
    df["target"] = logp.shift(-HORIZON) - logp
    return df.dropna(subset=["mom_12m"])


# ----------------------------------------------------------------------------- models


def make_model(kind: str):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "gradient_boosting":
        return HistGradientBoostingRegressor(max_depth=2, learning_rate=0.05, max_iter=150, min_samples_leaf=10,
                                             l2_regularization=1.0, random_state=0)
    if kind == "ridge":
        return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=10.0))
    raise KeyError(kind)


def walk_forward(df: pd.DataFrame, kinds=("gradient_boosting", "ridge"), min_train: int = MIN_TRAIN) -> pd.DataFrame:
    """One prediction per month, each from models fitted on the past only (targets known at that date)."""
    rows = []
    X, y = df[FEATURES], df["target"]
    for i in range(min_train + HORIZON, len(df)):
        if not np.isfinite(y.iloc[i]):
            continue
        train = slice(0, i - HORIZON + 1)            # target of row j ends at j + 3 months: purge the last 3 rows
        Xt, yt = X.iloc[train], y.iloc[train]
        keep = yt.notna()
        Xt, yt = Xt[keep], yt[keep]
        if len(yt) < min_train:
            continue
        row = {"date": df.index[i], "actual": float(y.iloc[i]), "mean": float(yt.mean()), "zero": 0.0,
               "last_3m": float(X["mom_3m"].iloc[i])}
        for k in kinds:
            row[k] = float(make_model(k).fit(Xt, yt).predict(X.iloc[[i]])[0])
        rows.append(row)
    return pd.DataFrame(rows).set_index("date")


def diebold_mariano(e_model: np.ndarray, e_bench: np.ndarray, lags: int = HORIZON - 1) -> tuple[float, float]:
    """One-sided test that the model's squared errors are smaller than the benchmark's. Returns (stat, p)."""
    from scipy.stats import norm
    d = e_bench ** 2 - e_model ** 2
    n = len(d)
    if n < 10:
        return float("nan"), float("nan")
    dc = d - d.mean()
    var = dc @ dc / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (dc[k:] @ dc[:-k]) / n
    if var <= 0:
        return float("nan"), float("nan")
    stat = d.mean() / math.sqrt(var / n)
    return float(stat), float(1 - norm.cdf(stat))


def score(pred: pd.DataFrame, kind: str) -> dict:
    a, p, m = pred["actual"].values, pred[kind].values, pred["mean"].values
    sse, sse_mean, sse_zero = ((a - p) ** 2).sum(), ((a - m) ** 2).sum(), (a ** 2).sum()
    stat, pval = diebold_mariano(a - p, a - m)
    r2 = float(1 - sse / sse_mean) if sse_mean > 0 else None
    return {"r2_oos": r2, "r2_vs_zero": float(1 - sse / sse_zero) if sse_zero > 0 else None,
            "hit_rate": float(np.mean(np.sign(p) == np.sign(a))), "mae": float(np.mean(np.abs(a - p))),
            "dm_stat": stat, "dm_p": pval, "rating": rate(r2)}


def evaluate_asset(px: pd.Series, name: str, macro: pd.DataFrame | None = None) -> dict:
    df = features(px, macro)
    pred = walk_forward(df)
    if pred.empty:
        return {"name": name, "error": "not enough history"}
    models = {k: score(pred, k) for k in ("gradient_boosting", "ridge", "last_3m")}
    base = {"hit_rate_mean": float(np.mean(np.sign(pred["mean"]) == np.sign(pred["actual"])))}
    main = models["gradient_boosting"]
    usable = main["rating"]["label"] in {"Good", "Very good"} and np.isfinite(main["dm_p"]) and main["dm_p"] < SIGNIFICANCE

    # Final model on every month whose target is known; forecast from the latest month.
    known = df.dropna(subset=["target"])
    model = make_model("gradient_boosting").fit(known[FEATURES], known["target"])
    latest = df.iloc[[-1]]
    f = float(model.predict(latest[FEATURES])[0])
    resid = pred["actual"] - pred["gradient_boosting"]
    lo, hi = float(resid.quantile(0.10)), float(resid.quantile(0.90))
    coverage = float(((resid >= lo) & (resid <= hi)).mean())
    from sklearn.inspection import permutation_importance
    recent = known.iloc[-60:]
    imp = permutation_importance(model, recent[FEATURES], recent["target"], n_repeats=20, random_state=0)
    importance = sorted(({"feature": c, "label": FEATURE_LABEL[c], "importance": float(v)}
                         for c, v in zip(FEATURES, imp.importances_mean)), key=lambda x: -x["importance"])
    return {
        "name": name, "horizon_months": HORIZON,
        "history": f"{df.index[0].date()} to {df.index[-1].date()}", "months": int(len(df)),
        "tested": f"{pred.index[0].date()} to {pred.index[-1].date()}", "n_predictions": int(len(pred)),
        "models": models, "baselines": base, "usable": bool(usable),
        "forecast": {"as_of": str(px.dropna().index[-1].date()), "log_return": f, "return": math.expm1(f),
                     "low": math.expm1(f + lo), "high": math.expm1(f + hi), "interval": "80%",
                     "interval_coverage_in_test": coverage,
                     "annualized": math.expm1(f * 12 / HORIZON)},
        "importance": importance[:5],
    }


def train(prices: pd.DataFrame | None = None) -> dict:
    prices = prices if prices is not None else load_long_prices()
    out = {"trained_on": date.today().isoformat(), "method": __doc__.split("Design")[0].strip(),
           "target": f"log return over the next {HORIZON} months", "min_train_months": MIN_TRAIN,
           "rating_scale": [{"from": th if np.isfinite(th) else None, "label": lbl} for th, lbl, _ in RATING],
           "assets": {}}
    for t, name in ASSETS.items():
        if t in prices:
            out["assets"][t] = evaluate_asset(prices[t], name)
    return out


def load_artifact(path: Path | None = None) -> dict | None:
    path = path or ARTIFACT
    if not path.exists():
        return None
    return json.loads(path.read_text())
