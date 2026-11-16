<div align="center">

# WealthPilot

### EXPLAINABLE AI FOR INVESTMENT DECISION SUPPORT

**Understand the decision. Challenge the assumptions. Verify the numbers.**

Palantir Associates · PolyFinances Datathon 2026 · AlphaForge AI Challenge

**[Explore the live demo](https://d3pmr84q14pg9z.cloudfront.net/)** &nbsp; · &nbsp; **[One-pager (PDF)](docs/WealthPilot_One_Pager.pdf)** &nbsp; · &nbsp; **[AWS architecture (PDF)](docs/WealthPilot_AWS_Architecture.pdf)** &nbsp; · &nbsp; **[Data report (PDF)](docs/Data_Report.pdf)**

</div>

---

## Investment decisions deserve more than a chart.

Investors face an overwhelming mix of prices, headlines and economic indicators. Making sense of it all takes time, and generic information does not account for personal goals, financial capacity or risk tolerance.

**WealthPilot** turns market evidence and an investor's profile into **explainable, hypothetical investment scenarios**. It shows the trade-offs, questions risky assumptions and makes clear *why* an option may or may not fit.

## Try WealthPilot in 60 seconds

1. **Choose a demo persona:** Amira (growth), Mateo (balanced) or Robert (conservative).
2. **Open “My Plan”:** explore goal-specific portfolios, diversification and risks.
3. **Ask the “Devil's Advocate”:** challenge a concentrated investment and see the evidence and counterarguments.

**[Launch WealthPilot](https://d3pmr84q14pg9z.cloudfront.net/)**

## Install and run it locally

**You need:** Python 3.10 or newer, Node.js 18 or newer, Git.

**1. Get the code and the Python packages**

```bash
git clone https://github.com/Juanita-HP/WealthPilot.git
cd WealthPilot
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**2. Add the market data.** Copy the organizers' five starter files (`assets_universe.csv`, `prices_daily.csv`,
`corporate_actions.csv`, `fx_usdcad_daily.csv`, `macro_rates.csv`) into `data/starter/`, or rebuild them from Yahoo
Finance with `python scripts/build_dataset.py`. They are not in Git because Yahoo-derived data cannot be redistributed.
The macro history and the trained models are already in the repository.

**3. Build the interface and start the app**

```bash
cd web
npm install
npm run build
cd ..
python -m wealthpilot.api
```

Open **http://127.0.0.1:8000** and click a demo persona (Amira, Mateo or Robert). If port 8000 is taken, start with
another one: `PORT=8001 python -m wealthpilot.api` (Windows PowerShell: `$env:PORT=8001; python -m wealthpilot.api`).

**Optional**

- **AI agents** ("Ask the advisor"): they run on Amazon Bedrock. If AWS credentials with Bedrock access are configured
  on your machine (`pip install boto3`), the app uses them automatically. Without them, everything else works and the
  page says the agents are off.
- **Tests:** `pytest` (no AWS account needed).
- **Deploy to AWS** (CloudFront, S3, Lambda, DynamoDB) and retrain the models on SageMaker:
  see [infra/aws.md](infra/aws.md). The developer guide, with every script, is in
  [docs/technical/DEVELOPMENT.md](docs/technical/DEVELOPMENT.md).

## What makes it different

**Explainability is part of the workflow—not a paragraph added at the end.**

> **Investor question → Advisor → Devil's Advocate → Verifier → Explained result**

- **Advisor** connects the user's financial constraints with traceable calculations and market context.
- **Devil's Advocate** identifies conflicts, concentration risk and questionable assumptions.
- **Verifier** compares numerical claims with calculation receipts and flags unsupported statements.

Risk classification is **rule-based**: the more conservative of *risk capacity* and *risk tolerance* governs, and each goal's investment horizon can impose stricter limits. It is **not** a market-price-trained risk prediction model.

## Data, with provenance

The supplied research dataset includes:

| Dataset | Coverage | Why it matters |
|---|---:|---|
| Yahoo Finance market prices | 40,049 records | Historical performance and risk |
| Bank of Canada + FRED macro data | 8,281 observations | Inflation, rates and economic context |
| Bank of Canada FX data | 1,245 records | USD-to-CAD comparisons |
| Organizer asset universe | 31 assets | Consistent asset, sector and currency mapping |

The [data report](docs/Data_Report.pdf) documents source selection, preprocessing, exploratory analysis, charts and limitations. The macroeconomic notebook's documented quality checks found **zero missing values and zero duplicate date/indicator records**; that finding applies to the inspected macro dataset, not every project component.

## Built with

**Interface:** React 18 + Vite · **Backend:** FastAPI · **Analytics:** Python, pandas, NumPy · **AI:** Amazon Bedrock agents with deterministic verification · **Cloud:** AWS CloudFront, S3, Lambda and DynamoDB.

## Review only what you need

| Start here | Contents |
|---|---|
| **[Live prototype](https://d3pmr84q14pg9z.cloudfront.net/)** | Product experience and demo personas |
| **[Technical documentation (PDF)](docs/WealthPilot_Technical_Documentation.pdf)** | Architecture choices with the focus on AWS, agents and explainability, data and methods, validation, limits (7 pages) |
| **[One-pager (PDF)](docs/WealthPilot_One_Pager.pdf)** ([web version](docs/ONE_PAGER.md)) | Problem, approach, originality, data, explainability, validation and user value on one page |
| **[Data report](docs/Data_Report.pdf)** | Sources, EDA, methodology and limitations |
| **[Solution architecture one-pager](docs/WealthPilot_Solution_Architecture.pdf)** ([web version](docs/SOLUTION_ARCHITECTURE.md)) | Architecture diagram: interface, API, agents, decision engine, data |
| **[AWS architecture one-pager](docs/WealthPilot_AWS_Architecture.pdf)** ([web version](docs/AWS_ARCHITECTURE.md)) | AWS diagram: Amazon CloudFront™, Amazon S3™, AWS Lambda™, Amazon Bedrock™, Amazon DynamoDB™, Amazon SageMaker AI™ |
| [Technical architecture](infra/architecture.md) | Agent workflow, validation and design choices |
| [Developer guide](docs/technical/DEVELOPMENT.md) | Setup, commands, code map and deployment details |

<details>
<summary><strong>Code structure for technical reviewers</strong></summary>

| Directory | Purpose |
|---|---|
| [web/](web/) | Frontend |
| [wealthpilot/](wealthpilot/) | Backend, financial engines and agents |
| [data/](data/) and [notebooks/](notebooks/) | Data and EDA |
| [models/](models/) | Model artifacts, cards and evaluations |
| [tests/](tests/) | Automated validation |
| [scripts/](scripts/), [training/](training/), [infra/](infra/) | Data pipelines, training and AWS infrastructure |

</details>

---

**Responsible use:** WealthPilot is an educational simulation. It executes no real trades, offers no guaranteed returns and does not provide regulated personalized investment advice. Historical evidence and model outputs are not certain forecasts.
