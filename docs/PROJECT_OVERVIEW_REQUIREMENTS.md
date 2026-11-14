# WealthPilot — Project Overview & Requirements

**AlphaForge AI · Datathon 2026 | Educational investment simulation**

### 1. Overview & Problem
Investors struggle to connect scattered financial data with personal goals, risk capacity and preferences. **WealthPilot** is a Streamlit prototype that builds investor profiles, compares fictional portfolios using public data, and explains results with verifiable evidence.

### 2. User Journey & Inputs/Outputs
**Fictional account → six-step onboarding → risk classification → goal-based plan → charts and scenarios → AI explanations.**

Inputs: financial situation (CAD), goals, horizons, behavioural responses, experience and preferences.

Outputs: five-level risk profile, constraints, simulated allocations, warnings and sourced explanations.

### 3. Functional Requirements

| ID | Requirement |
|---|---|
| **FR-01** | Validate onboarding inputs and support a 10-question risk-scoring engine. |
| **FR-02** | Classify by **Risk Capacity** and **Risk Tolerance** (use the lower score); cap risk separately for each goal's horizon. |
| **FR-03** | Analyze historical returns, volatility, Sharpe/Sortino, drawdowns and diversification. |
| **FR-04** | Display goal-based allocations, backtests, scenarios and interactive charts. |
| **FR-05** | **Advisor → Devil's Advocate → code-based Verifier:** challenge mismatches, cite calculation receipts and flag unsupported claims. |

### 4. Data & Technical Architecture
**Frontend:** Streamlit. **Backend:** Python, pandas, NumPy and financial engines.

**Data:** official starter dataset (31 assets, prices, FX and macro series) plus documented public sources; CAD conversion and publication lags prevent misleading comparisons.

**AWS:** Bedrock, Lambda, S3 and DynamoDB are implemented in code with mock tests; **live deployment is not yet confirmed**.

### 5. Quality, Risks & Boundaries
Requirements: clear UX, traceable calculations, reproducible results, input validation and protected credentials. Flag concentration, horizon conflicts and uncertainty.

**Simulation only:** no trades, brokerage connections, real financial advice or guaranteed returns.

### 6. Acceptance Criteria & Delivery
- Demonstrate distinct, explainable outcomes for **Amira, Mateo and Robert**.
- Check rule-based classification with persona/synthetic tests; validate financial metrics, agent receipts and out-of-sample performance.
- Verify a working browser-accessible demo **and a live AWS-backed agent call** before claiming deployment.
- Deliver code + README, concise technical documentation, one-pager and ~5-minute demo video. Manage tasks using **Scrumban / GitHub Projects**.

**Technical references:** [Architecture](https://github.com/Juanita-HP/WealthPilot/blob/main/docs/architecture.md) · [AWS](https://github.com/Juanita-HP/WealthPilot/blob/main/docs/aws.md) · [Repository](https://github.com/Juanita-HP/WealthPilot)
