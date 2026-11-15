# Model card: 3-month return forecast for crypto and gold

Trained on 2026-11-15 by `scripts/train_asset_forecast.py`.

Return forecast for assets with no statements and no planning assumption (crypto, gold), tested honestly.

Question: can a model predict the next 3 months' return of Bitcoin, Ether or gold better than simply using the
historical average? Most research on asset returns says it rarely can (Welch and Goyal, 2008), so the answer is
measured, shown to the investor, and only used for the gauge if it clearly passes.

## Results (walk-forward, out of sample)

| Asset | Tested | Model | R² vs average | Rating | Direction right | DM p-value |
|---|---|---|---|---|---|---|
| Bitcoin | 2018-12-31 to 2026-08-31 (93 months) | Gradient boosting | -33.5% | Very bad | 55% | 0.94 |
| Bitcoin | 2018-12-31 to 2026-08-31 (93 months) | Ridge | -25.5% | Very bad | 60% | 0.89 |
| Bitcoin | 2018-12-31 to 2026-08-31 (93 months) | Last 3 months repeat | -82.0% | Very bad | 51% | 1.00 |
| Bitcoin | | Historical average (benchmark) | 0.0% | | 58% | |
| Ether | 2022-02-28 to 2026-08-31 (55 months) | Gradient boosting | -2.5% | Bad | 51% | 0.56 |
| Ether | 2022-02-28 to 2026-08-31 (55 months) | Ridge | 14.7% | Very good | 55% | 0.27 |
| Ether | 2022-02-28 to 2026-08-31 (55 months) | Last 3 months repeat | -75.9% | Very bad | 44% | 0.98 |
| Ether | | Historical average (benchmark) | 0.0% | | 51% | |
| Gold (SPDR Gold Shares) | 2009-02-28 to 2026-08-31 (211 months) | Gradient boosting | -7.2% | Very bad | 57% | 0.87 |
| Gold (SPDR Gold Shares) | 2009-02-28 to 2026-08-31 (211 months) | Ridge | -5.7% | Very bad | 58% | 0.77 |
| Gold (SPDR Gold Shares) | 2009-02-28 to 2026-08-31 (211 months) | Last 3 months repeat | -87.3% | Very bad | 53% | 1.00 |
| Gold (SPDR Gold Shares) | | Historical average (benchmark) | 0.0% | | 59% | |

## Use in the interface

The gauge uses the gradient-boosting forecast only when its rating is good or very good and the Diebold-Mariano test against the historical average is significant at 10%. Otherwise the gauge says "Not scored" and the investor sees the R², its rating and the forecast with its range, to judge.

## Limits

- Few independent observations (3-month targets, 10 to 20 years of history): results move with the period.
- Overlapping monthly targets: the test uses a Newey-West variance; hit rates are still optimistic.
- Prices in U.S. dollars (listing currency); the investor's CAD return also moves with the exchange rate.
- Two models compared on the same test period: a small selection effect remains.
