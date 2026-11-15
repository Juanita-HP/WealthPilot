# WealthPilot: architecture, agents and validation

WealthPilot is an educational investment simulation. It builds an investor profile, proposes a fictional allocation, replays it through real market history, challenges the investor's requests and its own proposals, and shows where every number comes from. It never executes trades and never tells anyone to buy or sell.

## What the BNC workshops asked for, and where it is

| Point raised (finance workshop and case kick-off) | In WealthPilot |
|---|---|
| People invest for goals; one portfolio holds several horizons; horizon is the goal's, not the person's age | `goals.py`: a sub-portfolio and account suggestion per goal, level capped by the goal's horizon, cash-only under 2 years, emergency fund always cash-like |
| Capacity to absorb risk is not tolerance | `onboarding.py`: capacity measured from the investor's own numbers (cushion in months, share of assets invested, debt/income, savings rate, job stability, dependents); tolerance from behaviour questions asked in their dollars; the level follows the lower |
| Preferences sit inside constraints, never above | `profile.constraints_for`: preferences (ESG, values, crypto interest, simplicity) are applied within the level's limits and flagged when a limit wins |
| Kinds of risk: market, credit, liquidity, currency, concentration, inflation | `risks.py`: risk map with level, number and reason for each |
| Diversify across asset classes, regions, sectors, management style | strategist sleeves, exposure alerts, risk map |
| Explain data used, why this choice, limits, and what would change the answer | advisor answer structure; `whatif.py` computes the conditions |
| Data quality: date, currency, revenue vs earnings, fund type, missing data and hypotheses | every value carries provenance (`ticker.py`), CAD conversion, point-in-time rules, "Known data issues" below |
| Amira: high risk is not "anything goes" | level 5 still caps stocks at 95%, crypto at 10%, one stock at 15%; diversification alerts |
| Mateo: non-financial criteria beyond ESG | values (e.g. no fossil fuels), simplicity preference, ESG-screened fund, home-region preference |
| Robert: check coherence, question the request or the profile | devil's advocate with counterpoint, tipping points, more-conservative-only level override |
| Agents with clear roles; a debate agent can arbitrate | advisor, devil's advocate, debate (arbitration), verifier |
| Say when the answer is uncertain; separate facts, hypotheses, scenarios | answer sections, labeled hypotheses, verifier, model card showing the ML model lost to simple rules |

## Design principle

**Numbers come from tested code; the language model orchestrates and explains.** Every figure in an answer is produced by a deterministic tool, recorded as a numbered receipt, cited in the answer, and checked by a verifier written in code. A model cannot invent a justification after the fact without the verifier noticing.

## Flow of one question

```
Investor question
      │
      ▼
Advisor agent (Claude on Amazon Bedrock) ──calls──► tools (Python) ──► receipts R1, R2, ...
      │ draft answer citing [R#]
      ▼
Devil's advocate agent (Claude) ──calls──► review tools ──► receipts
      │ challenges + counterpoint + question
      ▼
Verifier (code): every number vs its receipt; governance rules
      │ problems? ──► one revision by the advisor, then remaining problems are shown, not hidden
      ▼
Answer + verification line + disclaimer; state and trace saved in DynamoDB
```

## Agents and why each exists

| Component | Kind | Role | Value it adds |
|---|---|---|---|
| Advisor | LLM + tools | Understands the question, gathers evidence, drafts the answer at the investor's level | Turns calculations into an explanation adapted to experience |
| Devil's advocate | LLM + review tools | Challenges the request and the draft: profile breaches, risk jump, recency bias, horizon mismatch, overfitting | Contradicts the investor when needed (the Robert test) and critiques WealthPilot's own proposals; always states the counterpoint |
| Verifier | Code | Checks every number against the cited receipt (English and French formats, rounding); blocks directives to trade, guaranteed returns, certain predictions | Explainability that can be audited, not just asserted; cannot be talked out of a failure |

Explainability and governance, the two "possibilities" of the brief, are built into the receipts and the verifier rather than added as extra agents.

## Tools (all tested Python)

| Module | What it computes | Validation |
|---|---|---|
| `data.py` | One business-day calendar, CAD conversion (Bank of Canada FX), publication lags for macro data, risk-free rate | Real-data regression checks (SPY 2022 return, CPI availability dates) |
| `metrics.py` | Return, CAGR, volatility, Sharpe and Sortino with risk-free, drawdown dates, real return | Equal to the original C++ `MetricsEngine` to 1e-12 |
| `portfolio.py` | Multi-asset backtest: weights, rebalancing, costs, fees, next-day execution | Hand-computed cases |
| `exposure.py` | Exposure by currency, sector, asset class; risk contributions; concentration alerts | Synthetic portfolios with known answers |
| `profile.py` | 10-question questionnaire: risk capacity, risk tolerance, required return; level = lower of capacity and tolerance, capped by short horizons; constraints (Graham 25-75% band for levels 2-4) | Three brief personas with expected results, 600 synthetic profiles checked for invariants, level never falls with a longer horizon |
| `strategist.py` | Policy allocation on index ETFs with a written reason for every weight; statistics in reasons computed from data | Equity share inside the level range for every level; out-of-sample comparison with an estimated variant |
| `time_machine.py` | Historical replay in the investor's dollars (worst fall, worst 12 months, real value after CPI); labeled hypothetical shocks | Real-data checks |
| `validation.py` | Level ladder (risk rises with level on real data); walk-forward of inverse-volatility weights vs rules | Monotonicity test; no-look-ahead test |
| `inflation.py` | Canadian CPI forecast: ridge vs mean reversion vs no change vs 2% target, walk-forward since 2008 | See `docs/model_card_inflation.md`; method with lowest out-of-sample error is used and named |
| `lab.py` | Strategy lab adapted from nicho-spekt/backtesting-engine: optimize on 70%, test on 30%, always against buy-and-hold | Indicators equal to the `ta` library; backtester equal to the compiled C++ engine; causality test |
| `advocate.py` | Evidence-based challenges with honest counterpoints | Robert + 30% TSLA flagged; small quality position not blocked; own allocation reviewed |
| `ticker.py` | Ticker overview, chart series, growth score (financial statements), profile-fit score | Fake data source, mocked yfinance cache, real-data checks |

## Results worth knowing

- **Inflation**: the ridge model on macro features did not beat simple rules out of sample. Partial reversion toward 2% won at 3, 6 and 12 months; 80% intervals covered 77-82% of outcomes. The application uses the winning method and says so.
- **Allocation method**: estimating weights from past volatility beat the fixed rules in 2 of 4 test years with a negligible return difference, so the simpler, explainable rules stay.
- **Strategy lab**: optimized rules often look strong in sample and fade out of sample (for example a breakout rule on NVDA: Sharpe 1.36 in sample, 0.11 out of sample after 74 trials); the lab reports this instead of hiding it.
- **Honesty about counterpoints**: adding 30% TSLA to Robert's allocation would have raised the 2021-2026 return; the advocate says so, then shows the drawdown rising from about 11% to about 30%.

## Data

| Source | Content | Use |
|---|---|---|
| Organizers' starter dataset (Yahoo Finance via yfinance, Bank of Canada, FRED), retrieved 2026-11-13 | 31 assets, daily prices 2021-11 to 2026-11, dividends, FX, rates | All market calculations |
| Bank of Canada Valet API and FRED via `scripts/fetch_macro_history.py` | CPI index and y/y, core CPI, yields, oil, FX, U.S. CPI and unemployment since 1995 | Inflation model, real-terms values |
| FP Canada / Institute of Financial Planning, Projection Assumption Guidelines 2026 | Long-term planning returns and inflation | Goal feasibility (labeled as assumptions) |
| Yahoo Finance via yfinance (live, cached with retrieval time) | Fundamentals, analyst estimates | Ticker dashboard; analyst figures labeled as third-party opinion |
| Yahoo Finance search endpoint via yfinance (headlines, publisher, time, related tickers; no article bodies) | Recent news, 308 headlines collected 2026-11-14 | News digest and hype challenge; 64 headlines hand-labeled as a golden set (`data/news/golden_v0.jsonl`, labeling guide in `wealthpilot/news_prompts/`) |
| Official press releases, full text: Bank of Canada, Federal Reserve (RSS) and Statistics Canada's The Daily (Atom), read with BeautifulSoup where robots.txt allows AI agents | Rate decisions, CPI, jobs, GDP, trade, retail; refreshed every 12 hours | "The news and your portfolio": what was announced (exact quotes), exposed share of the portfolio, past similar events, matching stress test |
| FRED `DFEDTARU` | Upper limit of the federal funds target range since 2008 | Dates of past Fed decisions for the event study; checking the analyzer |

Point-in-time rules: monthly macro data is usable from the first day of the second month after its reference month; daily data from the next business day; trading decisions execute at the next close.

## News pipeline

| Step | How | Why |
|---|---|---|
| Collect | Yahoo Finance search endpoint (headlines only: its robots.txt excludes AI agents from article pages) | Public, documented, respects access terms |
| Trust | Five documented tiers (official 1.0, wire 0.85, media 0.65, aggregator 0.45, promotional 0.3) | Weight facts by where they come from |
| Relevance | Company names and tickers in the headline | Search returns loosely related stories |
| Classify | Rule baseline (offline) and Claude with versioned prompts (`v1`, `v2`); same labeling guide for humans and prompts | Separate facts from forecasts and opinions |
| Evaluate | `scripts/eval_news.py` on the golden set; prompt examples excluded from scoring; results in `models/news_eval.json` | Each prompt version must beat the previous one |
| Use | Digest per ticker (facts first, opinions apart, hype share); devil's advocate HYPE challenge with facts as counterpoint; agent tool `news_digest` | News explain and challenge; they never predict prices |

Baseline result: rules-v2 gets 77% type accuracy and finds 66% of predictive headlines (see `docs/news_eval.md`). The prompt versions are scored with the same script once Bedrock access is available.

### Article texts: who allows what

Headlines alone are too thin to justify anything, so the text behind each item is read when the site allows it. `wealthpilot/webtext.py` downloads a page only if the site's robots.txt allows both our user agent and the AI agents (`ClaudeBot`, `anthropic-ai`), since the text is analysed by a model; it waits the site's crawl delay, caches pages for 7 days, never bypasses a CAPTCHA or a paywall, and gives every item a status (text read, site excludes AI agents, subscribers only, page unreachable). Yahoo Finance's robots.txt excludes AI agents, so its headlines stay context and are never used as evidence; the interface says so under each ticker's news.

### Global news and the portfolio (`wealthpilot/macro_news.py`)

Recommendations are diversified portfolios, so the news that matters moves whole asset classes. Official sources publish their full texts and allow them to be read.

| Step | How | Why |
|---|---|---|
| Collect | RSS/Atom feeds of the Bank of Canada, the Federal Reserve and Statistics Canada (major releases only: CPI, Labour Force Survey, GDP, merchandise trade, retail) | Official, complete, allowed |
| Read | BeautifulSoup extraction of the main text; boilerplate removed | Evidence is the text, not a headline |
| Analyse | Decision and figure (policy rate, CPI, unemployment, GDP), risk factors (rates, inflation, currency, energy, growth, trade) with exact sentences, share of forecast sentences; rule analyzer `macro-rules-v1`, Claude prompt `macro_v1` (quotes kept only if found verbatim) | Facts apart from the source's forecasts, every claim with its sentence |
| Check | `scripts/eval_macro.py` compares each decision read with the official series of the same institution (V39079, DFEDTARU, total CPI y/y): 11 of 11 correct on the first run | No hand labels needed for decisions |
| Map | Documented rules per factor and region: direct (e.g. Canadian bonds for a Bank of Canada decision), indirect (rate-sensitive sectors, foreign bonds), not exposed | The unexposed share is what diversification buys |
| Compare | Returns of each holding over the 20 business days after past similar events (rate hikes, cuts, CPI accelerations) vs the usual 20-day return; "clear" only beyond two standard errors | Measured history, labeled as association |
| Stress | Rate hike: rates up 1 point (bond durations); inflation acceleration: stocks and bonds down | Turns the news into a concrete "what if" |
| Use | Box "L'actualité et votre portefeuille" in the plan tab; devil's advocate NEWS_EXPOSURE when a request makes the portfolio depend 10+ points more on a factor in the news; agent tool `macro_news_impact` | News explain; they never change the allocation (market timing) |

On the current data, no past-event difference is "clear": with 10 Bank of Canada hikes in the 2021-2026 window, Canadian bonds averaged -1.0% over the next 20 days against +0.1% usually, 1.9 standard errors. The interface says "no clear effect" rather than overstating it.

## Known data issues

- CNQ.TO shows a 1.021 "split" on 2022-08-22 next to a special dividend; it is not a real share split (organizers' note). Adjusted prices are used for returns.
- Yahoo's adjusted closes are back-adjusted and change when re-downloaded; the starter snapshot is dated 2026-11-13.
- No FX rate on Canadian holidays: the last rate is carried forward.
- ETF trading volume understates ETF liquidity, so volume-based liquidity tests apply to individual stocks only.
- yfinance histories can start a day after a 5-year window; returns use the first available price (found on live data, tested).
- Financial statements of banks make debt/equity meaningless (deposits); the growth score does not score it for financials.

## Limits

- Five years of prices: one full cycle at most; long-horizon profiles are judged on a short sample.
- Survivorship bias: the universe was chosen in 2026 among today's large companies.
- No ESG scores or controversy data: ESG preferences work through investor-chosen sector exclusions and an ESG-screened fund whose holdings are not checked.
- FRED series are latest revised values (Canadian CPI is not revised).
- Hypothetical shocks are stylized; they test sensitivity, they do not forecast.
- The verifier checks that each number exists in the cited receipt, not that the sentence interprets it correctly; the advocate and the structure of the answer address interpretation.
