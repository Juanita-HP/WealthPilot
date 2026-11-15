# Model card: market-timing check (ML entry signal vs holding)

Run on 2026-11-15 by `scripts/train_timing.py`. Adapted from the team's backtesting engine (nicho-spekt/backtesting-engine, src/ml).

Market-timing check: can a machine-learning entry signal beat simply holding, after real trading costs?

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

## Results, honest protocol (one test per year, threshold chosen inside each training window)

| Asset | Costs | Tests | Beats holding (Sharpe) | Beats holding (return) | Mean Sharpe gap | p-value | Compounded: model vs holding | Usable |
|---|---|---|---|---|---|---|---|---|
| QQQ | 0.00% per side | 17 (2010-2026) | 6/17 | 5/17 | -0.56 | 1.00 | 140% vs 1512% | no |
| QQQ | 0.05% per side | 17 (2010-2026) | 6/17 | 4/17 | -0.60 | 1.00 | 112% vs 1485% | no |
| QQQ | 1.55% per side | 17 (2010-2026) | 3/17 | 3/17 | -0.90 | 1.00 | -28% vs 847% | no |
| VGT | 0.00% per side | 17 (2010-2026) | 4/17 | 3/17 | -0.47 | 0.98 | 417% vs 1701% | no |
| VGT | 0.05% per side | 17 (2010-2026) | 7/17 | 6/17 | -0.50 | 0.98 | 371% vs 1671% | no |
| VGT | 1.55% per side | 17 (2010-2026) | 7/17 | 7/17 | -0.38 | 0.99 | 309% vs 958% | no |
| SPY | 0.00% per side | 17 (2010-2026) | 7/17 | 5/17 | -0.20 | 0.89 | 188% vs 764% | no |
| SPY | 0.05% per side | 17 (2010-2026) | 7/17 | 5/17 | -0.24 | 0.93 | 173% vs 750% | no |
| SPY | 1.55% per side | 17 (2010-2026) | 1/17 | 1/17 | -1.58 | 1.00 | -84% vs 408% | no |
| XIU.TO | 0.00% per side | 17 (2010-2026) | 9/17 | 9/17 | -0.34 | 0.99 | 102% vs 363% | no |
| XIU.TO | 0.05% per side | 17 (2010-2026) | 8/17 | 7/17 | -0.38 | 0.99 | 88% vs 355% | no |

## Original protocol (5 equal chunks, 4 validation folds), threshold chosen inside each training window

| Asset | Costs | Beats holding on return | Beats holding on Sharpe |
|---|---|---|---|
| QQQ | none | 0/4 | 0/4 |
| QQQ | 0.05% per side | 0/4 | 0/4 |
| VGT | none | 0/4 | 0/4 |
| VGT | 0.05% per side | 1/4 | 1/4 |
| SPY | none | 0/4 | 1/4 |
| SPY | 0.05% per side | 0/4 | 1/4 |
| XIU.TO | none | 2/4 | 2/4 |
| XIU.TO | 0.05% per side | 1/4 | 1/4 |

## Reading

The model has some ranking skill (average AUC above 0.5), but turning it into in-and-out trades misses part of the market's best days: after realistic costs it does not beat simply holding often enough, or significantly. With the threshold picked after seeing the test folds, the original backtest found '3 out of 4' for some thresholds; picked honestly, the advantage disappears. The devil's advocate shows this as evidence that timing entries is hard, and would show the live signal only if an asset passed the gate.
