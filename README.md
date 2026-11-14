
# WealthPilot

### AI-powered investment guidance, tailored to every investor.

WealthPilot is a **hackathon-stage AI-powered investment advisory prototype** designed to help users explore investment strategies based on their personal profiles.

By combining a short investor questionnaire, data analysis, and AI-generated explanations, WealthPilot aims to make portfolio recommendations easier to understand—especially for people who are new to investing.

> **Project Status:** In Development | FinTech & AI Hackathon

## The Problem

New investors often struggle to understand their risk tolerance, choose an appropriate asset allocation, and interpret financial information.

Traditional advisory services may be difficult to access, while generic investing content rarely reflects an individual's circumstances.

## Our Solution

WealthPilot provides a guided, personalized investment experience.

Users answer **10 multiple-choice questions** about their investment profile, and the platform uses their responses to suggest an illustrative portfolio allocation with an AI-powered explanation.

Our goal is to support **financial education and informed decision-making**, not replace licensed financial advisers.

## Planned MVP Features

- **Investor Profiling:** A 10-question questionnaire covering financial goals, investment horizon, experience, and risk tolerance.
- **Risk Assessment:** Structured investor profiles based on questionnaire responses.
- **Portfolio Recommendations:** Illustrative asset allocations aligned with the user's profile.
- **AI-Powered Explanations:** Clear descriptions of suggested allocations, trade-offs, and investment risks.
- **User-Friendly Interface:** An accessible experience designed for investors of different experience levels.

## How It Works

1. **Complete the Questionnaire**
   - Answer 10 multiple-choice questions.

2. **Build an Investor Profile**
   - Identify financial goals, investment experience, time horizon, and risk tolerance.

3. **Analyze the Profile**
   - Apply recommendation logic and supporting financial data.

4. **Generate Portfolio Suggestions**
   - Present an illustrative asset allocation based on the investor's profile.

5. **Explain the Results**
   - Use AI to explain the suggested allocation, potential risks, and limitations.

## Technology Stack

The following technologies are planned for development:

| Component | Technology |
|-----------|------------|
| Programming Language | Python |
| Data Analysis | pandas, NumPy |
| Recommendation Engine | Rule-based logic / Machine Learning |
| AI Integration | Large Language Models (LLMs) |
| Cloud Infrastructure | Amazon Web Services (AWS) |
| Frontend | To Be Determined |
| Version Control | Git & GitHub |
| Project Management | GitHub Projects |

**Note:** The technical architecture and integrations are still being finalized.

## Data, Transparency & Safety

WealthPilot prioritizes responsible AI and transparent financial recommendations.

- Use appropriately licensed public or synthetic financial datasets.
- Avoid collecting sensitive banking credentials.
- Separate portfolio recommendation logic from AI-generated explanations.
- Explain potential investment risks and uncertainties.
- Validate recommendations against investor profiles.
- Clearly communicate that investment returns are not guaranteed.

## MVP Development Roadmap

- [ ] Define the project requirements and objectives.
- [ ] Design the 10-question investor questionnaire.
- [ ] Establish investor profiling and risk assessment logic.
- [ ] Select and explore the financial dataset.
- [ ] Perform Data Cleaning and Exploratory Data Analysis (EDA).
- [ ] Develop the portfolio recommendation engine.
- [ ] Integrate an LLM for AI-powered explanations.
- [ ] Develop the user interface.
- [ ] Integrate AWS cloud services.
- [ ] Test and validate the complete workflow.
- [ ] Prepare the final project presentation and demonstration.

## Project Scope

### In Scope
- Investor profiling
- Risk tolerance assessment
- Illustrative portfolio allocation
- AI-generated investment explanations
- Financial data analysis
- Functional MVP demonstration

### Out of Scope
- Real-money trading
- Brokerage account integration
- Guaranteed investment returns
- Tax or legal advisory services
- Fully automated investment management

## Getting Started (development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Copy the organizers' starter files (`prices_daily.csv`, `fx_usdcad_daily.csv`, `macro_rates.csv`, `assets_universe.csv`, `corporate_actions.csv`) into `data/starter/`, or rebuild them with `python scripts/build_dataset.py`. The CSVs are git-ignored because Yahoo-derived data has redistribution limits. The yfinance cache (`data/cache/`) is git-ignored for the same reason.

```bash
pytest
```

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

To cross-check the NumPy metrics against the original C++ engine, build `metrics_cpp` for your platform and run `METRICS_CPP_PATH=<build dir> pytest`.

## Team

Developed collaboratively as part of a FinTech and AI hackathon.

Team members and their responsibilities will be added as development progresses.

## Disclaimer

**WealthPilot is an educational prototype and is not a registered investment advisory service.**

All generated portfolio suggestions are illustrative and do not constitute regulated financial advice or a recommendation to buy or sell specific securities.

Investment decisions involve financial risk. Users should consult a qualified financial professional before making investment decisions.
