# WealthPilot

**AI-Powered Investment Decision Support | AlphaForge AI — Datathon 2026**

WealthPilot is an AI-powered prototype designed to help users explore simulated investment decisions based on their financial goals, experience, risk tolerance, investment horizon, and preferences.

Through an **Investor Profile Questionnaire**, WealthPilot creates an investor profile and uses AI Agents to analyze public financial data, compare investment options, and provide transparent, explainable insights.

## Key Features

- Investor onboarding and profile assessment
- Financial Data Cleaning, EDA, and risk analysis
- Personalized investment scenario simulations
- Explainable AI Agents with transparent sources and constraints
- AWS Integration and scenario testing

## Tech Stack

- **Data Science:** Python, pandas, NumPy, Jupyter Notebook
- **Visualization:** Chart.js (interface), Matplotlib (analysis)
- **AI & Cloud:** Claude on Amazon Bedrock, AWS Lambda, S3, DynamoDB
- **Frontend:** React 18 + Vite (`web/`)
- **API:** FastAPI (`wealthpilot/api.py`)
- **Project Management:** GitHub Projects, Scrumban

## Project Deliverables

Working prototype, source code, technical documentation, demo video, and one-page project summary.

## Getting Started (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Copy the organizers' starter files (`prices_daily.csv`, `fx_usdcad_daily.csv`, `macro_rates.csv`, `assets_universe.csv`, `corporate_actions.csv`) into `data/starter/`, or rebuild them with `python scripts/build_dataset.py`. The CSVs are git-ignored because Yahoo-derived data has redistribution limits. The yfinance cache (`data/cache/`) is git-ignored for the same reason.

```bash
python scripts/fetch_macro_history.py   # macro history since 1995
python scripts/fetch_international.py   # international stock funds (XEF.TO, XEC.TO) for the global split
python scripts/fetch_long_history.py    # long price history of gold and crypto (forecast model)
python scripts/train_asset_forecast.py  # crypto and gold forecast, tested out of sample (models/model_card_asset_forecast.md)
python scripts/fetch_timing_history.py && python scripts/train_timing.py  # ML market-timing check (models/model_card_timing.md)
python scripts/train_inflation.py        # inflation model + model card
pytest
```

### Demo interface (React + FastAPI)

Needs Node.js 18+ for the interface. Build it once, then one Python process serves both the API and the interface:

```bash
cd web && npm install && npm run build && cd ..
python -m wealthpilot.api
```

Open http://127.0.0.1:8000. For development with hot reload, run the API and the Vite dev server side by side
(Vite forwards `/api` to port 8000), then open http://localhost:5173:

```bash
uvicorn wealthpilot.api:app --reload --port 8000
```

```bash
cd web && npm run dev
```

Create a (fictional) account, then answer the questionnaire, one question per page, with amounts in dollars (work situation, income and spending, assets and debts, goals with their horizons, comfort with risk, experience, themes and preferences, summary); the profile is saved and reloaded at the next login. Pages: stock research (search with suggestions, price chart, fundamentals, and two gauges: fit with your profile and unbiased measured growth, with the explanation behind each), watchlist, my plan (one sub-portfolio per goal, official news mapped to the portfolio, six risks), time machine, devil's advocate (plus the Claude agents), profile. My plan also answers "invest now, spread it out, or wait for a good moment?" with the investor's own money, the team's ML timing model being the "wait" contender, and, for experienced investors, a trading-rule tester. The browser cannot call Yahoo Finance directly (CORS), so the API relays the market-data requests of the stock page. Demo personas (Amira, Mateo, Robert) prefill the onboarding. Accounts are stored locally (`data/users/`, git-ignored) with salted PBKDF2 hashes; Amazon Cognito would replace this in a deployment. The agents need `WEALTHPILOT_LLM=bedrock` (AWS credentials) or `WEALTHPILOT_LLM=anthropic`.

### Hosted version on AWS

The website runs on AWS: CloudFront serves the React build from S3 and sends `/api/*` to the FastAPI app on Lambda
(accounts in DynamoDB, agents on Amazon Bedrock). Deploy or update it from AWS CloudShell with
`bash scripts/deploy_aws.sh`; no access keys are needed (see `infra/aws.md`). The models are retrained monthly in
Amazon SageMaker training jobs (`bash scripts/train_aws.sh`); a new model reaches the site only after
`scripts/promote_models.sh` and a confirmation.

### Core modules

| Module | What it does |
|---|---|
| `wealthpilot/data.py` | Loads the starter data, aligns all assets on one business-day calendar, converts USD to CAD (Bank of Canada rate), applies publication lags to macro series, builds a risk-free rate from the BoC overnight target |
| `wealthpilot/metrics.py` | NumPy port of the C++ `MetricsEngine` from [nicho-spekt/backtesting-engine](https://github.com/nicho-spekt/backtesting-engine), plus risk-free Sharpe, Sortino, CAGR, Calmar, real return, drawdown dates |
| `wealthpilot/portfolio.py` | Multi-asset backtest with target weights, periodic rebalancing, transaction costs, fees and an execution delay; side-by-side comparison of allocations |
| `wealthpilot/exposure.py` | Exposure by currency/sector/asset class, risk contributions, and concentration alerts tied to explicit thresholds |
| `wealthpilot/assumptions.py` | Long-term planning assumptions from the FP Canada / Institute of Financial Planning 2026 Projection Assumption Guidelines (stated hypotheses, not forecasts) |
| `wealthpilot/profile.py` | 10-question questionnaire scored on risk capacity and risk tolerance, risk level (lower of the two, capped by short horizons), constraints per level, goal analysis, allocation checker |
| `wealthpilot/ticker.py` | Ticker dashboard backend: overview with provenance for every number, chart series per timeframe, growth score (from financial statements) and profile-fit score, each with its factor breakdown. Sources: `YFinanceSource` (live, cached) or `StarterSource` (offline) |
| `wealthpilot/strategist.py`, `time_machine.py`, `validation.py` | Policy allocation with a reason per weight; replay in the investor's dollars and hypothetical shocks; out-of-sample validation |
| `wealthpilot/inflation.py` | Canadian CPI forecaster validated walk-forward (see `models/model_card_inflation.md`) |
| `wealthpilot/timing.py` | The backtesting engine's ML timing model (logistic regression on its technical indicators and the VIX; features checked against the engine by `tests/test_timing_parity.py`), tested year by year with realistic broker costs and a threshold chosen on training data only; answers "invest now, spread it out, or wait?" in My plan and the agents' `invest_now_or_wait` tool |
| `wealthpilot/lab.py` | Strategy lab adapted from nicho-spekt/backtesting-engine, always against buy-and-hold and out of sample |
| `wealthpilot/advocate.py` | Devil's advocate: evidence-based challenges with honest counterpoints |
| `wealthpilot/macro_news.py`, `wealthpilot/webtext.py` | Global news read in full from official sources (Bank of Canada, Federal Reserve, Statistics Canada) with BeautifulSoup where robots.txt allows AI agents: decision and quotes, risk factors, share of the investor's portfolio exposed, past similar events, matching stress test; checked against official series (`scripts/eval_macro.py`, `models/macro_eval.md`) |
| `wealthpilot/news.py`, `wealthpilot/news_prompts/` | News as data: source trust tiers, descriptive vs predictive classification (rule baseline and versioned Claude prompts scored on a golden set, `scripts/eval_news.py`), relevance filter, hype share used by the devil's advocate |
| `wealthpilot/goals.py`, `risks.py`, `whatif.py` | One sub-portfolio per goal with its own horizon; six kinds of risk; what would change the answer |
| `wealthpilot/onboarding.py`, `wealthpilot/accounts.py` | Numeric onboarding: capacity from emergency months, share of assets invested, debt to income, savings rate, employment and dependents; flags (cushion short, savings over-committed, high debt); demo accounts |
| `wealthpilot/agents/` | Advisor and devil's advocate agents (Claude on Amazon Bedrock), tools with receipts, deterministic verifier |
| `wealthpilot/api.py`, `web/` | HTTP API (FastAPI) and React interface; every text the API returns is plain English, ready to display |
| `wealthpilot/coverage.py` | Which investments the devil's advocate can review (stated data rules: type, CAD/USD, 3+ years of prices, volume, known sector or fund type inferred from prices), live data for assets outside the stored universe, liquidity measure |
| `wealthpilot/markets.py` | Search page overview: popular investments and today's biggest moves (our stated rule), with daily charts |
| `wealthpilot/aws/`, `infra/` | Lambda handlers (agents, hosted API), S3 data sync, DynamoDB audit trail, SAM templates (see `infra/aws.md`) |

Architecture, agents, validation and limits: [`infra/architecture.md`](infra/architecture.md).

To cross-check the NumPy metrics against the original C++ engine, build `metrics_cpp` for your platform and run `METRICS_CPP_PATH=<build dir> pytest`.

## Disclaimer

WealthPilot is an educational simulation. It does not execute real transactions, guarantee returns, or provide regulated personalized financial advice.
