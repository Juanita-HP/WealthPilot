<div align="center">

# WealthPilot

### EXPLAINABLE AI FOR INVESTMENT DECISION SUPPORT

**Understand the decision. Challenge the assumptions. Verify the numbers.**

Palantir Associates · PolyFinances Datathon 2026 · AlphaForge AI Challenge

**[Explore the live demo](https://d3pmr84q14pg9z.cloudfront.net/)** &nbsp; · &nbsp; **[View the one-pager](docs/One_pager_wealthpilot.png)** &nbsp; · &nbsp; **[Data report (PDF)](docs/Data_Report.pdf)**

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
| **[Project one-pager](docs/One_pager_wealthpilot.png)** | Visual overview of the problem, solution and approach |
| **[Data report](docs/Data_Report.pdf)** | Sources, EDA, methodology and limitations |
| [Technical architecture](infra/architecture.md) | Agent workflow, validation and design choices |
| [Technical specifications](docs/technical/project_overview_requirements.md) | Requirements, constraints and scope |
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
