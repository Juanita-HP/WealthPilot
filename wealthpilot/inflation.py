"""Canadian inflation forecaster, validated walk-forward against simple baselines.

What it predicts: Canada total CPI inflation (year over year) h months after the
latest published month, for h in HORIZONS.

How (and why):
* Target = CHANGE in y/y inflation over h months. Predicting the change makes
  "no change" (random walk) the natural zero, so the model only gets credit for
  what it adds beyond persistence.
* Model = ridge regression on standardized features: the same regularized
  linear model as the gradient-descent trainer in nicho-spekt/real-estate-
  price-predictor, solved in closed form (exact, no learning rate or iteration
  count to tune). Linear, so each forecast splits into feature contributions.
* The scaler is fit on training rows only and stored with the weights in a
  JSON artifact (same idea as model_params.json in that project).
* The penalty lambda is chosen per horizon by time-series cross-validation
  inside the training window; the CV error of every candidate is saved, so the
  choice can be justified.
* Point-in-time: a forecast made with month t data is dated at the publication
  of month t CPI (about six weeks later). Training rows only use targets that
  were published by then.
* Intervals: empirical quantiles of the model's own past out-of-sample errors
  (split-conformal style). Their realized coverage is reported.

Data: data/external/macro_history.csv (Bank of Canada Valet, FRED), see
scripts/fetch_macro_history.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .assumptions import INFLATION as LONG_RUN_ASSUMPTION

HORIZONS = (3, 6, 12)
TARGET = 2.0  # Bank of Canada inflation target, percent
LAMBDAS = (0.1, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0)
CV_VALIDATION_MONTHS = 36
MIN_TRAIN_MONTHS = 60
INTERVAL = (0.10, 0.90)
ARTIFACT = Path(os.environ.get("WEALTHPILOT_MODEL_PATH", Path(__file__).resolve().parent.parent / "models" / "inflation_model.json"))

FEATURES = {  # name -> why it is in the model
    "yoy": "Current inflation: inflation is persistent.",
    "core_yoy": "Core inflation (CPIW): the underlying trend, less affected by volatile items.",
    "accel_3m": "Change in y/y inflation over the last 3 months: momentum.",
    "oil_yoy": "Crude oil (WTI) y/y change: energy prices pass quickly into CPI.",
    "fx_yoy": "USD/CAD y/y change: a weaker dollar raises import prices.",
    "yield_2y": "2-year Government of Canada yield: market view of the policy path.",
    "slope_10y_2y": "10-year minus 2-year yield: growth expectations.",
    "us_yoy": "U.S. CPI inflation: common global inflation pressures.",
    "us_unrate_chg": "12-month change in U.S. unemployment: economic slack.",
}


# --------------------------------------------------------------------------- data


def monthly_panel(history: pd.DataFrame) -> pd.DataFrame:
    """Features by reference month from the long-format macro history (realized values)."""
    def series(sid):
        s = history.loc[history["series_id"] == sid].set_index("date")["value"].sort_index()
        s.index = pd.to_datetime(s.index)
        return s

    def monthly_mean(sid):
        return series(sid).resample("MS").mean()

    cpi = series("V41690973").resample("MS").last()
    yoy = 100 * (cpi / cpi.shift(12) - 1)
    oil, fx = monthly_mean("DCOILWTICO"), monthly_mean("DEXCAUS")
    y2, y10 = monthly_mean("BD.CDN.2YR.DQ.YLD"), monthly_mean("BD.CDN.10YR.DQ.YLD")
    us = series("CPIAUCSL").resample("MS").last()
    ur = series("UNRATE").resample("MS").last()
    panel = pd.DataFrame({
        "yoy": yoy,
        "core_yoy": series("CPIW").resample("MS").last(),
        "accel_3m": yoy - yoy.shift(3),
        "oil_yoy": 100 * np.log(oil / oil.shift(12)),
        "fx_yoy": 100 * np.log(fx / fx.shift(12)),
        "yield_2y": y2,
        "slope_10y_2y": y10 - y2,
        "us_yoy": 100 * (us / us.shift(12) - 1),
        "us_unrate_chg": ur - ur.shift(12),
    })
    panel.index.name = "month"
    return panel


def publication_date(month: pd.Timestamp) -> pd.Timestamp:
    """Conservative availability date of month-t data: first day of month t+2 (same rule as data.py)."""
    return month + pd.offsets.MonthBegin(2)


def supervised(panel: pd.DataFrame, h: int) -> pd.DataFrame:
    """Rows: origin month t with features at t and target = yoy(t+h) - yoy(t)."""
    df = panel.copy()
    df["target"] = df["yoy"].shift(-h) - df["yoy"]
    df["target_month"] = df.index + pd.DateOffset(months=h)
    return df


# --------------------------------------------------------------------------- ridge


@dataclass
class Ridge:
    lam: float
    mean: np.ndarray = field(default=None)
    scale: np.ndarray = field(default=None)
    weights: np.ndarray = field(default=None)
    bias: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "Ridge":
        self.mean = X.mean(axis=0)
        self.scale = X.std(axis=0, ddof=0)
        self.scale[self.scale == 0] = 1.0
        Z = (X - self.mean) / self.scale
        self.bias = float(y.mean())
        yc = y - self.bias
        n_feat = Z.shape[1]
        # Minimizes ||yc - Z w||^2 + lam ||w||^2 (bias not penalized).
        self.weights = np.linalg.solve(Z.T @ Z + self.lam * np.eye(n_feat), Z.T @ yc)
        return self

    def standardize(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean) / self.scale

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.standardize(X) @ self.weights + self.bias


def choose_lambda(X: np.ndarray, y: np.ndarray, lambdas=LAMBDAS, val_months=CV_VALIDATION_MONTHS,
                  h: int = 12) -> tuple[float, dict]:
    """Time-series CV inside the training window: one-step expanding refits over the last val_months.

    A validation row at position i is predicted by a model trained on rows up to i - h,
    the same information gap as in real use.
    """
    n = len(y)
    start = max(MIN_TRAIN_MONTHS, n - val_months)
    scores = {}
    for lam in lambdas:
        errs = []
        for i in range(start, n):
            tr = i - h + 1
            if tr < MIN_TRAIN_MONTHS // 2:
                continue
            m = Ridge(lam).fit(X[:tr], y[:tr])
            errs.append(abs(m.predict(X[i:i + 1])[0] - y[i]))
        scores[lam] = float(np.mean(errs)) if errs else float("inf")
    best = min(scores, key=scores.get)
    return best, scores


# --------------------------------------------------------------------------- walk-forward evaluation

METHODS = ("ridge", "mean_reversion", "random_walk", "target_2pct")
METHOD_LABELS = {
    "ridge": "ridge regression on macro features",
    "mean_reversion": "partial return toward the 2% target (one coefficient fitted on past data)",
    "random_walk": "no change from today's inflation",
    "target_2pct": "the Bank of Canada's 2% target",
}


def fit_mean_reversion(yoy: np.ndarray, change: np.ndarray) -> float:
    """k in change = k * (TARGET - yoy), least squares, clipped to [0, 1]."""
    gap = TARGET - yoy
    k = float(gap @ change / (gap @ gap)) if gap @ gap > 0 else 0.0
    return min(1.0, max(0.0, k))


def walk_forward(panel: pd.DataFrame, h: int, first_origin: str = "2008-01-01",
                 lambda_every: int = 12) -> pd.DataFrame:
    """Out-of-sample forecasts of every method for every origin from first_origin on.

    At origin t, training rows are origins s with s + h <= t (their target was published
    by the time month-t data is) and complete features. Weights are refit every month;
    lambda is re-chosen every ``lambda_every`` months.
    """
    df = supervised(panel, h)
    feats = list(FEATURES)
    usable = df.dropna(subset=feats)
    rows, lam = [], None
    errors = {m: [] for m in METHODS}
    for k, t in enumerate(usable.loc[first_origin:].index):
        train = usable.loc[: t - pd.DateOffset(months=h)].dropna(subset=["target"])
        if len(train) < MIN_TRAIN_MONTHS:
            continue
        X, y = train[feats].to_numpy(), train["target"].to_numpy()
        if lam is None or k % lambda_every == 0:
            lam, _ = choose_lambda(X, y, h=h)
        ridge = Ridge(lam).fit(X, y)
        kmr = fit_mean_reversion(train["yoy"].to_numpy(), y)
        yoy_t = float(usable.loc[t, "yoy"])
        preds = {
            "ridge": yoy_t + float(ridge.predict(usable.loc[[t], feats].to_numpy())[0]),
            "mean_reversion": yoy_t + kmr * (TARGET - yoy_t),
            "random_walk": yoy_t,
            "target_2pct": TARGET,
        }
        actual = df.loc[t, "target"]
        row = {"origin": t, "target_month": t + pd.DateOffset(months=h), "lambda": lam, "k_mean_reversion": kmr,
               "yoy_now": yoy_t, "actual": yoy_t + actual if pd.notna(actual) else np.nan, **preds}
        for mth in METHODS:
            if len(errors[mth]) >= 24:
                q = np.quantile(errors[mth], INTERVAL)
                row[f"{mth}_low"], row[f"{mth}_high"] = preds[mth] + q[0], preds[mth] + q[1]
        rows.append(row)
        # The error of the forecast made h months ago becomes known now (its target month is t).
        if len(rows) > h and pd.notna(rows[-1 - h]["actual"]):
            old = rows[-1 - h]
            for mth in METHODS:
                errors[mth].append(old["actual"] - old[mth])
    return pd.DataFrame(rows).set_index("origin")


def scorecard(wf: pd.DataFrame) -> dict:
    d = wf.dropna(subset=["actual"])
    out = {"methods": {}, "n_forecasts": int(len(d)), "period": f"{d.index[0].date()} to {d.index[-1].date()}",
           "interval_nominal": INTERVAL[1] - INTERVAL[0]}
    for mth in METHODS:
        e = d["actual"] - d[mth]
        lo, hi = f"{mth}_low", f"{mth}_high"
        iv = d.dropna(subset=[lo, hi]) if lo in d else d.iloc[0:0]
        out["methods"][mth] = {
            "mae": float(e.abs().mean()), "rmse": float(np.sqrt((e ** 2).mean())),
            "interval_coverage": float(((iv["actual"] >= iv[lo]) & (iv["actual"] <= iv[hi])).mean()) if len(iv) else None,
            "mae_2008_2019": float(e.loc["2008":"2019"].abs().mean()),
            "mae_2020_on": float(e.loc["2020":].abs().mean()),
        }
    maes = {m: v["mae"] for m, v in out["methods"].items()}
    out["best_method"] = min(maes, key=maes.get)
    out["ridge_skill_vs_random_walk"] = 1 - maes["ridge"] / maes["random_walk"]
    return out


# --------------------------------------------------------------------------- training, artifact, forecast


def train(history: pd.DataFrame, horizons=HORIZONS, first_origin: str = "2008-01-01") -> dict:
    """Fit final models on all available rows, evaluate walk-forward, return the artifact dict."""
    panel = monthly_panel(history)
    feats = list(FEATURES)
    artifact = {"created": date.today().isoformat(), "features": FEATURES, "target_definition":
                "change in Canada total CPI y/y inflation (percentage points) over h months",
                "data": {"file": "data/external/macro_history.csv",
                         "retrieved_on": str(history["retrieved_on"].iloc[0]) if "retrieved_on" in history else None,
                         "sources": sorted(history["source"].unique().tolist())},
                "method": {"model": "ridge regression on standardized features (closed form)",
                           "lambda_grid": list(LAMBDAS), "cv": f"expanding one-step, last {CV_VALIDATION_MONTHS} months of the training window",
                           "interval": f"empirical {INTERVAL[0]:.0%}-{INTERVAL[1]:.0%} quantiles of past out-of-sample errors"},
                "horizons": {}}
    for h in horizons:
        df = supervised(panel, h).dropna(subset=feats + ["target"])
        X, y = df[feats].to_numpy(), df["target"].to_numpy()
        lam, cv = choose_lambda(X, y, h=h)
        model = Ridge(lam).fit(X, y)
        wf = walk_forward(panel, h, first_origin)
        sc = scorecard(wf)
        done = wf.dropna(subset=["actual"])
        quantiles = {mth: np.quantile((done["actual"] - done[mth]).to_numpy(), INTERVAL).tolist() for mth in METHODS}
        kmr = fit_mean_reversion(df["yoy"].to_numpy(), y)
        artifact["horizons"][str(h)] = {
            "lambda": lam, "cv_mae_by_lambda": {str(k): v for k, v in cv.items()},
            "training_rows": int(len(df)), "training_window": f"{df.index[0].date()} to {df.index[-1].date()}",
            "scaler_mean": model.mean.tolist(), "scaler_scale": model.scale.tolist(),
            "weights": model.weights.tolist(), "bias": model.bias,
            "k_mean_reversion": kmr,
            "error_quantiles": quantiles,
            "evaluation": sc,
            "method_used": sc["best_method"],
        }
    return artifact


def save(artifact: dict, path: Path = ARTIFACT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")


def load(path: Path = ARTIFACT) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/train_inflation.py.")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Forecast:
    horizon_months: int
    origin_month: str
    available_from: str
    target_month: str
    current_yoy: float
    forecast: float
    low: float
    high: float
    method: str
    method_label: str
    all_methods: dict
    contributions: dict
    evaluation: dict
    note: str

    def to_dict(self):
        return asdict(self)


def forecast(history: pd.DataFrame, artifact: dict, h: int = 12, as_of=None) -> Forecast:
    """Forecast from the latest month whose data was published by ``as_of`` (default: today).

    Uses the method with the lowest out-of-sample error for this horizon, and reports the others.
    """
    panel = monthly_panel(history).dropna(subset=list(FEATURES))
    as_of = pd.Timestamp(as_of or date.today())
    published = [t for t in panel.index if publication_date(t) <= as_of]
    if not published:
        raise ValueError("no published data at that date")
    t = published[-1]
    spec = artifact["horizons"][str(h)]
    x = panel.loc[t, list(FEATURES)].to_numpy(dtype=float)
    z = (x - np.array(spec["scaler_mean"])) / np.array(spec["scaler_scale"])
    w = np.array(spec["weights"])
    yoy = float(panel.loc[t, "yoy"])
    preds = {
        "ridge": yoy + float(z @ w + spec["bias"]),
        "mean_reversion": yoy + spec["k_mean_reversion"] * (TARGET - yoy),
        "random_walk": yoy,
        "target_2pct": TARGET,
    }
    used = spec["method_used"]
    q = spec["error_quantiles"][used]
    ev = spec["evaluation"]
    maes = {m: round(v["mae"], 2) for m, v in ev["methods"].items()}
    contrib = {name: float(c) for name, c in zip(FEATURES, z * w)} if used == "ridge" else {}
    note = (f"Method chosen because it had the lowest mean absolute error in walk-forward tests over {ev['period']} "
            f"({ev['n_forecasts']} forecasts): " + ", ".join(f"{m} {v} pt" for m, v in maes.items()) + ". "
            f"Ridge skill vs 'no change': {ev['ridge_skill_vs_random_walk']:.0%}. "
            f"Long-run planning assumption: {LONG_RUN_ASSUMPTION:.1%} (FP Canada / IFP 2026).")
    return Forecast(h, str(t.date()), str(publication_date(t).date()), str((t + pd.DateOffset(months=h)).date()),
                    yoy, preds[used], preds[used] + q[0], preds[used] + q[1], used, METHOD_LABELS[used],
                    preds, contrib, {"mae": maes, "interval_coverage": ev["methods"][used]["interval_coverage"]}, note)


FEATURE_LABELS = {"yoy": "Current inflation", "core_yoy": "Core inflation (CPIW)", "accel_3m": "Recent acceleration (3 months)",
                  "oil_yoy": "Oil price (1-year change)", "fx_yoy": "U.S. dollar vs CAD (1-year change)",
                  "yield_2y": "2-year Canada bond yield", "slope_10y_2y": "Yield curve slope (10-year minus 2-year)",
                  "us_yoy": "U.S. inflation", "us_unrate_chg": "Change in U.S. unemployment (1 year)"}


def ridge_view(history: pd.DataFrame, artifact: dict, h: int = 12, as_of=None, top: int = 3) -> dict:
    """What the machine-learning model (ridge) predicts and which macro variables push its prediction.

    Contribution of a variable = its standardized value today times its weight, in percentage points of change
    in inflation over h months (positive: pushes inflation up). The ridge forecast is reported next to the
    method actually used, with both out-of-sample errors, so the investor can see which one tested better.
    """
    f = forecast(history, artifact, h, as_of)
    spec = artifact["horizons"][str(h)]
    panel = monthly_panel(history).dropna(subset=list(FEATURES))
    t = pd.Timestamp(f.origin_month)
    x = panel.loc[t, list(FEATURES)].to_numpy(dtype=float)
    z = (x - np.array(spec["scaler_mean"])) / np.array(spec["scaler_scale"])
    contrib = z * np.array(spec["weights"])
    order = np.argsort(-np.abs(contrib))
    q = spec["error_quantiles"]["ridge"]
    ridge = f.all_methods["ridge"]
    ev = spec["evaluation"]["methods"]
    return {
        "forecast": ridge, "low": ridge + q[0], "high": ridge + q[1],
        "mae": ev["ridge"]["mae"], "mae_used_method": ev[f.method]["mae"], "used_method": f.method,
        "interval_coverage": ev["ridge"]["interval_coverage"],
        "top": [{"feature": list(FEATURES)[i], "label": FEATURE_LABELS[list(FEATURES)[i]],
                 "value": float(x[i]), "contribution": float(contrib[i]), "why": FEATURES[list(FEATURES)[i]]}
                for i in order[:top]],
        "baseline": float(spec["bias"]),
    }
