# Project Overview & Requirements

### 1. Purpose and probleme statement

Investors often struggle to interpret complex financial data and assess whether investment opportunities align with their goals, risk capacity, risk tolerance, and investment horizons. Existing tools may offer generic recommendations without clearly explaining the risks and assumptions involved. WealthPilot addresses this problem through an AI-powered investment decision-support platform that combines public financial data, rule-based investor classification, risk analysis, and explainable AI Agents to provide transparent, goal-based insights through educational simulations.

### 2. Functional Requirements

| ID | Required capability |
|---|---|
| **FR-01** | Validate financial inputs (CAD), goals, horizons, preferences and behavioural responses; support the existing 10-question scoring engine. |
| **FR-02** | Generate an explainable investor Profile, goal-specific risk limits, warnings and allocation constraints. |
| **FR-03** | Analyze public market data; compare simulated allocations, historical performance, risk and diversification. |
| **FR-04** | Display dashboards, charts, backtests and hypothetical scenarios; expose data sources and assumptions. |
| **FR-05** | Run **Advisor → Devil's Advocate → deterministic Verifier**; challenge mismatches and check numeric claims against cited calculation receipts. |

### 3. Investor Classification & Risk Assessment

**Rule-based classification (not ML):** the risk score uses the **lower of Risk Capacity** (financial ability to withstand loss) **and Risk Tolerance** (willingness to bear loss). Each goal's investment horizon can further restrict its risk level.

Five levels are defined in `profile.py`: **1 Conservative · 2 Moderately Conservative · 3 Balanced · 4 Growth · 5 Aggressive**.

**Equity ranges (L1–L5):** 15–35%, 25–50%, 40–65%, 60–80%, 75–95%; **crypto caps:** 0%, 0%, 2%, 5%, 10%. Constraints also restrict single-security exposure and respect eligible preferences.

**Financial metrics:** cumulative return, **CAGR, annualized volatility, Sharpe Ratio, Sortino Ratio, Maximum Drawdown**, inflation-adjusted return and portfolio diversification/concentration.

The risk map covers **market, credit, liquidity, currency, concentration and inflation** risks, with supporting values and explanations.

### 4. Non-Functional Requirements
- **Accuracy & reproducibility:** deterministic calculations; documented currency conversion, publication lags and assumptions; time-aware backtesting.
- **Explainability & reliability:** traceable data sources, agent receipts, verification flags and explicit missing-data/uncertainty notices.
- **Security & usability:** validate inputs, protect credentials and fictional account data; provide understandable, accessible charts and error messages.
- **Performance:** the demonstration should be responsive; **no measured response-time SLA is claimed**.

### 5. Architecture, Project Risks & Boundaries
**Stack:** Streamlit; Python/pandas/NumPy/Plotly; public starter data (31 assets), FX and macro sources; Claude agent clients and AWS Bedrock/Lambda/S3/DynamoDB integration code. **Live AWS deployment is not yet verified.**

**Risks/limits:** five-year market history, survivorship bias, revised data, incomplete ESG coverage, model uncertainty, AWS access/deployment.

**Educational simulation only:** no real trades, brokerage connection, guaranteed returns or regulated financial advice.

### 6. Success Criteria
- Demonstrate **Amira, Mateo and Robert** with coherent, different, explainable outcomes and enforced constraints.
- Validate classification against persona tests and **600 synthetic profiles**; check risk calculations and portfolio rules through automated tests.
- Evaluate estimated methods using **out-of-sample / walk-forward** comparisons; report **MAE** for inflation and **accuracy/precision/recall** for news classification where applicable.
- Demonstrate a functioning browser workflow and **one real AWS-backed agent call** before claiming deployment; deliver README, technical documentation, one-pager and ~5-minute demo video
