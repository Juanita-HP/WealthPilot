"""Market-timing check: can a machine-learning entry signal beat simply holding, after real trading costs?

The model is adapted from the team's backtesting engine (nicho-spekt/backtesting-engine, ``src/ml``): a logistic
regression that estimates the probability that an asset rises more than 2% over the next 5 trading days, from
about thirty technical indicators (returns, volatility, volume, moving averages, RSI, Bollinger bands, breakout
channel, ATR) and the VIX. The strategy buys when that probability passes a threshold and holds for 5 days.

What changes here, so that the result can be trusted
-----------------------------------------------------
* **Costs.** Canadian commission-free brokers (Wealthsimple, Questrade, Qtrade) charge $0 per trade on stocks and
  ETFs, but every trade crosses the bid-ask spread and moves a little against the investor. We charge 0.05% per
  side (main scenario), and report 0% and 1.55% per side (U.S.-listed asset bought from a CAD account at
  Wealthsimple's 1.5% currency conversion fee) as sensitivity checks.
* **No threshold chosen on the test.** Inside each training window, the last two years are held out to pick the
  probability threshold (best Sharpe after costs, at least 5 trades); the model is then refitted on the whole window
  and applied, with that threshold, to the next calendar year it has never seen.
* **Many tests, not four.** Expanding walk-forward with one test per calendar year (about 15 per asset), on several
  assets (QQQ, SPY, XIU.TO, VGT), not only the one that worked.
* **Fixed indicator settings** (moving averages 50/200, RSI 14 with 30/70, Bollinger 20/2, 20-day channel) instead of
  settings optimized on the same data, to avoid a second layer of selection.
* **A gate fixed before running** (``USABLE_*``): the signal is shown to investors only if, after costs, it beats
  holding on Sharpe ratio in at least 70% of the yearly tests AND the average Sharpe difference is significant
  (one-sided paired t-test, p < 0.10). Otherwise the devil's advocate uses the result as evidence that timing is hard.
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

ASSETS = {"QQQ": "Invesco QQQ (Nasdaq-100)", "VGT": "Vanguard Information Technology ETF",
          "SPY": "SPDR S&P 500 ETF", "XIU.TO": "iShares S&P/TSX 60 ETF"}
VIX = "^VIX"
PRICES = data.EXTERNAL_DIR / "timing_prices.csv"
ARTIFACT = Path(os.environ.get("WEALTHPILOT_TIMING_PATH",
                               Path(__file__).resolve().parent.parent / "models" / "timing_model.json"))
SOURCE = "Adapted from the team's backtesting engine (nicho-spekt/backtesting-engine, src/ml)"

HORIZON = 5                 # trading days ahead, and holding period of a signal
TARGET_GAIN = 0.02          # the event predicted: more than +2% over 5 days
COSTS = {"main": 0.0005, "zero": 0.0, "fx_cad_account": 0.0155}
COST_NOTE = {"main": "0.05% per side: $0 commission (Wealthsimple, Questrade, Qtrade) plus bid-ask spread and slippage",
             "zero": "no costs (the original backtest's setting)",
             "fx_cad_account": "1.55% per side: U.S.-listed asset traded from a CAD account (1.5% conversion fee)"}
THRESHOLDS = tuple(round(x, 3) for x in np.arange(0.05, 0.501, 0.025))
FIRST_TEST_YEAR = 2010
INNER_YEARS = 2
MIN_TRADES = 5
USABLE_WIN_SHARE = 0.70
USABLE_P = 0.10

FEATURES = ["Return_1", "Return_5", "Return_20", "Volatility_20", "Volume_change", "Volume_vs_avg20",
            "Intraday_range", "Gap", "Ma_spread_pct", "Ma_short_slope", "Ma_long_slope", "Ma_price_to_short",
            "Ma_price_to_long", "Ma_signal", "RSI_value", "RSI_change", "RSI_signal", "BB_percent_b", "BB_bandwidth",
            "BB_distance_middle", "BB_bandwidth_change", "BB_signal", "Breakout_distance_high",
            "Breakout_distance_low", "Breakout_channel_width", "Breakout_signal", "VIX_level", "VIX_change_1",
            "VIX_change_5", "VIX_z20", "ATR_pct", "ATR_change", "ATR_ratio"]


# ----------------------------------------------------------------------------- data and features


def load_prices(path: Path | None = None) -> pd.DataFrame:
    path = path or PRICES
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run scripts/fetch_timing_history.py.")
    return pd.read_csv(path, parse_dates=["date"])


def ohlcv(prices: pd.DataFrame, ticker: str) -> pd.DataFrame:
    d = prices[prices["ticker"] == ticker].set_index("date").sort_index()
    return d[["open", "high", "low", "close", "volume"]].rename(columns=str.capitalize)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / down)


def _hold(enter: pd.Series, exit_: pd.Series) -> pd.Series:
    s = pd.Series(np.nan, index=enter.index)
    s[enter] = 1
    s[exit_ & ~enter] = 0
    return s.ffill().fillna(0)


def features(df: pd.DataFrame, vix: pd.Series) -> pd.DataFrame:
    """The engine's features with fixed settings; every value uses data up to that day only."""
    c, h, lo, v = df["Close"], df["High"], df["Low"], df["Volume"]
    f = pd.DataFrame(index=df.index)
    r1 = c.pct_change()
    f["Return_1"], f["Return_5"], f["Return_20"] = r1, c.pct_change(5), c.pct_change(20)
    f["Volatility_20"] = r1.rolling(20).std()
    f["Volume_change"] = v.pct_change()
    f["Volume_vs_avg20"] = v / v.rolling(20).mean()
    f["Intraday_range"] = (h - lo) / c
    f["Gap"] = df["Open"] / c.shift(1) - 1
    ma_s, ma_l = c.rolling(50).mean(), c.rolling(200).mean()
    f["Ma_spread_pct"] = (ma_s - ma_l) / c
    f["Ma_short_slope"], f["Ma_long_slope"] = ma_s.pct_change(), ma_l.pct_change()
    f["Ma_price_to_short"], f["Ma_price_to_long"] = c / ma_s - 1, c / ma_l - 1
    f["Ma_signal"] = (ma_s > ma_l).astype(float)
    rsi = _rsi(c)
    f["RSI_value"], f["RSI_change"] = rsi, rsi.diff()
    f["RSI_signal"] = _hold(rsi < 30, rsi > 70)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    upper, lower = mid + 2 * sd, mid - 2 * sd
    f["BB_percent_b"] = (c - lower) / (upper - lower)
    f["BB_bandwidth"] = (upper - lower) / mid
    f["BB_distance_middle"] = c / mid - 1
    f["BB_bandwidth_change"] = f["BB_bandwidth"].pct_change()
    f["BB_signal"] = _hold(c < lower, c > mid)
    hi20, lo20 = h.rolling(20).max().shift(1), lo.rolling(20).min().shift(1)
    f["Breakout_distance_high"], f["Breakout_distance_low"] = c / hi20 - 1, c / lo20 - 1
    f["Breakout_channel_width"] = (hi20 - lo20) / c
    f["Breakout_signal"] = _hold(c > hi20, c < lo20)
    vx = vix.reindex(df.index).ffill(limit=3)
    f["VIX_level"], f["VIX_change_1"], f["VIX_change_5"] = vx, vx.pct_change(), vx.pct_change(5)
    f["VIX_z20"] = (vx - vx.rolling(20).mean()) / vx.rolling(20).std()
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    f["ATR_pct"], f["ATR_change"], f["ATR_ratio"] = atr / c, atr.pct_change(), atr / atr.rolling(20).mean()
    fwd = c.shift(-HORIZON) / c - 1
    f["target"] = np.where(fwd.isna(), np.nan, (fwd > TARGET_GAIN).astype(float))
    f["ret_next"] = c.shift(-1) / c - 1          # close-to-close return of the next day (for the backtest)
    return f.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES)


# ----------------------------------------------------------------------------- model and backtest


def make_model():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, C=1.0))


def positions(prob: np.ndarray, threshold: float) -> np.ndarray:
    """Engine's rule: when the probability passes the threshold and no position is held, hold for 5 days."""
    pos, left = np.zeros(len(prob)), 0
    for i, p in enumerate(prob):
        if p >= threshold and left == 0:
            left = HORIZON
        if left > 0:
            pos[i] = 1.0
            left -= 1
    return pos


def backtest(pos: np.ndarray, ret_next: np.ndarray, cost: float) -> np.ndarray:
    """Daily returns: decided at the close of day t, held over day t+1; cost on each change of position."""
    held = np.concatenate([[0.0], pos[:-1]])           # one-day execution delay
    gross = held * np.nan_to_num(np.concatenate([[0.0], ret_next[:-1]]))
    trades = np.abs(np.diff(np.concatenate([[0.0], held])))
    return gross - trades * cost


def stats(daily: np.ndarray, invested: np.ndarray | None = None) -> dict:
    d = np.asarray(daily, dtype=float)
    total = float(np.prod(1 + d) - 1)
    sd = d.std(ddof=1) if len(d) > 1 else 0.0
    sharpe = float(d.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    wealth = np.cumprod(1 + d)
    mdd = float((wealth / np.maximum.accumulate(wealth) - 1).min()) if len(d) else 0.0
    out = {"total_return": total, "sharpe": sharpe, "max_drawdown": mdd}
    if invested is not None:
        out["time_invested"] = float(np.mean(invested))
        out["trades"] = int(np.sum(np.diff(np.concatenate([[0.0], invested])) > 0))
    return out


def hold_returns(ret_next: np.ndarray, cost: float) -> np.ndarray:
    """Buy and hold over the same days: one purchase at the start, one sale at the end."""
    d = np.concatenate([[0.0], np.nan_to_num(ret_next[:-1])])
    d[0] -= cost
    d[-1] -= cost
    return d


def choose_threshold(prob: np.ndarray, ret_next: np.ndarray, cost: float) -> float:
    best, best_sharpe = THRESHOLDS[0], -np.inf
    for t in THRESHOLDS:
        pos = positions(prob, t)
        if np.sum(np.diff(np.concatenate([[0.0], pos])) > 0) < MIN_TRADES:
            continue
        s = stats(backtest(pos, ret_next, cost))["sharpe"]
        if s > best_sharpe:
            best, best_sharpe = t, s
    return best


def _fit(df: pd.DataFrame):
    train = df.dropna(subset=["target"])
    return make_model().fit(train[FEATURES], train["target"].astype(int))


def walk_forward(feat: pd.DataFrame, cost: float, first_year: int = FIRST_TEST_YEAR) -> pd.DataFrame:
    """One test per calendar year; threshold chosen inside the training window only."""
    from sklearn.metrics import roc_auc_score
    rows = []
    years = sorted(y for y in feat.index.year.unique() if y >= first_year)
    for y in years:
        start = pd.Timestamp(y, 1, 1)
        train = feat[feat.index < start].iloc[:-HORIZON]            # purge: targets must be known before the test
        test = feat[(feat.index >= start) & (feat.index < pd.Timestamp(y + 1, 1, 1))]
        if len(test) < 60 or len(train) < 252 * (INNER_YEARS + 3):
            continue
        cut = train.index[-1] - pd.DateOffset(years=INNER_YEARS)
        inner_fit, inner_val = train[train.index <= cut].iloc[:-HORIZON], train[train.index > cut]
        thr = choose_threshold(_fit(inner_fit).predict_proba(inner_val[FEATURES])[:, 1],
                               inner_val["ret_next"].to_numpy(), cost)
        model = _fit(train)
        prob = model.predict_proba(test[FEATURES])[:, 1]
        pos = positions(prob, thr)
        rn = test["ret_next"].to_numpy()
        strat, hold = stats(backtest(pos, rn, cost), pos), stats(hold_returns(rn, cost))
        known = test.dropna(subset=["target"])
        auc = (roc_auc_score(known["target"].astype(int), prob[: len(known)])
               if known["target"].nunique() == 2 else None)
        rows.append({"year": y, "threshold": thr, "auc": auc,
                     **{f"strategy_{k}": v for k, v in strat.items()}, **{f"hold_{k}": v for k, v in hold.items()}})
    return pd.DataFrame(rows)


def summarize(folds: pd.DataFrame) -> dict:
    from scipy.stats import ttest_1samp
    diff = folds["strategy_sharpe"] - folds["hold_sharpe"]
    n = len(folds)
    p = float(ttest_1samp(diff, 0.0, alternative="greater").pvalue) if n > 2 and diff.std() > 0 else float("nan")
    win_sharpe = float((diff > 0).mean())
    win_return = float((folds["strategy_total_return"] > folds["hold_total_return"]).mean())
    usable = win_sharpe >= USABLE_WIN_SHARE and np.isfinite(p) and p < USABLE_P
    comp = lambda col: float(np.prod(1 + folds[col]) - 1)  # noqa: E731
    return {"tests": n, "years": f"{int(folds['year'].min())}-{int(folds['year'].max())}",
            "wins_sharpe": int((diff > 0).sum()), "win_share_sharpe": win_sharpe,
            "wins_return": int((folds["strategy_total_return"] > folds["hold_total_return"]).sum()),
            "win_share_return": win_return, "mean_sharpe_diff": float(diff.mean()), "p_value": p,
            "strategy_compounded": comp("strategy_total_return"), "hold_compounded": comp("hold_total_return"),
            "mean_time_invested": float(folds["strategy_time_invested"].mean()),
            "mean_auc": float(folds["auc"].dropna().mean()) if folds["auc"].notna().any() else None,
            "usable": bool(usable)}


def original_split(feat: pd.DataFrame, cost: float) -> dict:
    """The engine's original protocol (5 equal chunks, 4 validation folds), with the threshold chosen inside each
    training window instead of on the folds. For comparison with the '3 out of 4' result."""
    n = len(feat)
    edges = [int(n * k / 5) for k in range(6)]
    wins = []
    for k in range(1, 5):
        train = feat.iloc[:edges[k]].iloc[:-HORIZON]
        test = feat.iloc[edges[k]:edges[k + 1]]
        cut = train.index[-1] - pd.DateOffset(years=INNER_YEARS)
        inner_fit, inner_val = train[train.index <= cut].iloc[:-HORIZON], train[train.index > cut]
        thr = choose_threshold(_fit(inner_fit).predict_proba(inner_val[FEATURES])[:, 1],
                               inner_val["ret_next"].to_numpy(), cost)
        prob = _fit(train).predict_proba(test[FEATURES])[:, 1]
        pos = positions(prob, thr)
        rn = test["ret_next"].to_numpy()
        s, h = stats(backtest(pos, rn, cost), pos), stats(hold_returns(rn, cost))
        wins.append({"from": str(test.index[0].date()), "to": str(test.index[-1].date()), "threshold": thr,
                     "strategy_return": s["total_return"], "hold_return": h["total_return"],
                     "strategy_sharpe": s["sharpe"], "hold_sharpe": h["sharpe"],
                     "beats_on_return": s["total_return"] > h["total_return"], "beats_on_sharpe": s["sharpe"] > h["sharpe"]})
    return {"folds": wins, "beats_on_return": sum(w["beats_on_return"] for w in wins),
            "beats_on_sharpe": sum(w["beats_on_sharpe"] for w in wins)}


def latest_signal(feat: pd.DataFrame, cost: float) -> dict:
    """Probability today from a model fitted on all known targets, with a threshold chosen the same way."""
    train = feat.dropna(subset=["target"])
    cut = train.index[-1] - pd.DateOffset(years=INNER_YEARS)
    inner_fit, inner_val = train[train.index <= cut].iloc[:-HORIZON], train[train.index > cut]
    thr = choose_threshold(_fit(inner_fit).predict_proba(inner_val[FEATURES])[:, 1],
                           inner_val["ret_next"].to_numpy(), cost)
    model = _fit(train)
    prob = float(model.predict_proba(feat[FEATURES].iloc[[-1]])[:, 1][0])
    return {"as_of": str(feat.index[-1].date()), "probability": prob, "threshold": thr, "signal": prob >= thr,
            "base_rate": float(train["target"].mean())}


def train(prices: pd.DataFrame | None = None) -> dict:
    prices = prices if prices is not None else load_prices()
    vix = ohlcv(prices, VIX)["Close"]
    out = {"trained_on": date.today().isoformat(), "source": SOURCE, "method": __doc__.strip(),
           "costs": {k: {"per_side": v, "note": COST_NOTE[k]} for k, v in COSTS.items()},
           "gate": {"win_share_sharpe": USABLE_WIN_SHARE, "p_value": USABLE_P}, "assets": {}}
    for t, name in ASSETS.items():
        if t not in set(prices["ticker"]):
            continue
        feat = features(ohlcv(prices, t), vix)
        res = {"name": name, "history": f"{feat.index[0].date()} to {feat.index[-1].date()}", "scenarios": {}}
        for scen, cost in COSTS.items():
            if scen == "fx_cad_account" and t.endswith(".TO"):
                continue                                      # CAD-listed: no currency conversion
            folds = walk_forward(feat, cost)
            res["scenarios"][scen] = {"summary": summarize(folds), "folds": folds.round(5).to_dict(orient="records")}
        res["original_protocol"] = {"zero_costs": original_split(feat, 0.0), "main_costs": original_split(feat, COSTS["main"])}
        main = res["scenarios"]["main"]["summary"]
        res["usable"] = main["usable"]
        res["latest"] = latest_signal(feat, COSTS["main"])
        out["assets"][t] = res
    return out


def load_artifact(path: Path | None = None) -> dict | None:
    path = path or ARTIFACT
    return json.loads(path.read_text()) if path.exists() else None
