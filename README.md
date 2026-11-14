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
- **Visualization:** Plotly / Matplotlib
- **AI & Cloud:** AWS (Amazon Bedrock under consideration)
- **Frontend:** Streamlit (proposed)
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
python scripts/train_inflation.py        # inflation model + model card
pytest
```

### Demo interface

```bash
streamlit run app/streamlit_app.py
```

Six tabs: profile, goals, time machine, ticker dashboard, strategy lab, devil's advocate. The agents tab needs `WEALTHPILOT_LLM=bedrock` (AWS credentials) or `WEALTHPILOT_LLM=anthropic`.

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
| `wealthpilot/inflation.py` | Canadian CPI forecaster validated walk-forward (see `docs/model_card_inflation.md`) |
| `wealthpilot/lab.py` | Strategy lab adapted from nicho-spekt/backtesting-engine, always against buy-and-hold and out of sample |
| `wealthpilot/advocate.py` | Devil's advocate: evidence-based challenges with honest counterpoints |
| `wealthpilot/agents/` | Advisor and devil's advocate agents (Claude on Amazon Bedrock), tools with receipts, deterministic verifier |
| `wealthpilot/aws/`, `infra/` | Lambda handler, S3 data sync, DynamoDB audit trail, SAM template (see `docs/aws.md`) |

Architecture, agents, validation and limits: [`docs/architecture.md`](docs/architecture.md).

To cross-check the NumPy metrics against the original C++ engine, build `metrics_cpp` for your platform and run `METRICS_CPP_PATH=<build dir> pytest`.

## Disclaimer

WealthPilot is an educational simulation. It does not execute real transactions, guarantee returns, or provide regulated personalized financial advice.
