# WealthPilot · Solution architecture

*Explainable, agentic investment simulation: how the parts fit together.* Educational simulation: fictitious allocations, no real trades, not personalized financial advice.

PDF one-pager: [WealthPilot_Solution_Architecture.pdf](architecture/WealthPilot_Solution_Architecture.pdf)

![Solution architecture](architecture/solution-diagram.png)

<details><summary>Mermaid source of this diagram (validated: parses, no label cut)</summary>

```mermaid
%%{init: {"theme": "base", "htmlLabels": false, "themeVariables": {"fontFamily": "Inter, Helvetica, Arial, sans-serif", "fontSize": "14px", "primaryColor": "#fdf8ee", "primaryBorderColor": "#b8935a", "primaryTextColor": "#172025", "lineColor": "#8a8f91", "textColor": "#172025", "edgeLabelBackground": "#ffffff", "clusterBkg": "transparent", "clusterBorder": "#b8935a", "titleColor": "#8a6d3b"}}}%%
flowchart LR
    USER(["Investor"])
    subgraph UI["Interface"]
        WEB["Web interface<br/>React 18 + Vite"]
    end
    API["API service<br/>FastAPI<br/>signed sessions, validation"]
    subgraph AG["Agent layer"]
        ORCH["Orchestrator<br/>fixed order, one revision"]
        ADV["Advisor<br/>LLM + tool calls"]
        DEV["Devil's advocate<br/>LLM + review tools"]
        VER["Verifier<br/>deterministic code"]
        LED["Receipt ledger<br/>R1, R2, ..."]
    end
    subgraph ENG["Decision engine (Python)"]
        PROF["Profile, goals, allocation<br/>risk map, time machine"]
        RULES["Advocate rules, liquidity<br/>news: facts vs opinions"]
        MOD["Forecast models<br/>walk-forward tested"]
    end
    subgraph ST["Storage"]
        DATA[("Market and macro data<br/>prices in CAD")]
        ACC[("Accounts and<br/>audit trail")]
    end
    SRC["Public sources<br/>Yahoo Finance<br/>Bank of Canada, StatCan<br/>FRED, official feeds"]
    LLM["Amazon Bedrock™<br/>Claude Haiku 4.5"]

    USER --> WEB
    WEB -->|"REST JSON"| API
    API -->|"plan, scores, reviews"| PROF
    API -->|"questions"| ORCH
    API --> ACC
    ORCH -->|"1 draft"| ADV
    ORCH -->|"2 challenge"| DEV
    ORCH -->|"3 check"| VER
    ADV -.->|"tool calls"| PROF
    DEV -.->|"review tools"| RULES
    ADV -.->|"prompts"| LLM
    DEV -.->|"prompts"| LLM
    PROF -->|"receipts"| LED
    PROF --> MOD
    VER -.->|"compares"| LED
    MOD --> DATA
    SRC -->|"ingested"| DATA

    classDef ext fill:#ffffff,stroke:#8a8f91,stroke-dasharray:4 3,color:#172025
    class SRC,LLM,USER ext
```

</details>

## Layers

- **Web interface** (React 18 + Vite): profile, plan, time machine, stocks, devil's advocate.
- **API service** (FastAPI): signed sessions, validated inputs, one endpoint per screen.
- **Decision engine** (deterministic Python): profile = lower of risk capacity and tolerance (5 levels); each goal capped by its horizon; rule-based allocation; six-risk map; time machine and shocks; devil's advocate rules; data-coverage and liquidity rules; news facts vs opinions.
- **Forecast models**: inflation (ridge vs simple rules), crypto and gold (gradient boosting vs the historical mean), market timing (logistic regression). Shown only as far as their walk-forward tests, fixed in advance, allow.

## Why each agent exists

- **Advisor** (LLM): turns tool results into an answer at the investor's level. It does not compute: every figure comes from a tool.
- **Devil's advocate** (LLM): challenges the request and the draft (concentration, horizon, recency, hype) and states the counterpoint when the data supports the investor.
- **Verifier** (code, not an LLM): checks every number against its receipt; blocks trade directives, guaranteed returns and certainty. No model approves its own answer.
- **Orchestrator**: fixed order, at most one revision; remaining problems are shown, not hidden.

## One question, end to end

1. The interface sends the question with the signed session.
2. The API loads the investor's profile and simulated plan.
3. The Advisor calls tools; each result is a numbered receipt (R1, R2, ...).
4. The Devil's advocate reviews the draft with its own tools.
5. The Verifier compares every figure with its receipt.
6. Answer, receipts and verification are shown, and stored as an audit trail.

## Data, explainability, limits

- **Data**: Yahoo Finance prices converted to CAD with Bank of Canada rates; Bank of Canada, Statistics Canada and FRED series with publication lags; official news read within robots.txt.
- **Explainability**: facts, planning assumptions (FP Canada/IFP 2026) and scenarios are labelled; a model that fails its test shows "Not scored"; assets without enough data are not reviewed.
- **Limits**: five years of starter prices, survivorship bias, incomplete ESG coverage, model uncertainty.

*Grounded in: web/src, wealthpilot/api.py, wealthpilot/agents/ (orchestrator, tools, verifier, ledger), profile.py, goals.py, strategist.py, risks.py, time_machine.py, advocate.py, coverage.py, news.py, macro_news.py, inflation.py, forecast.py, timing.py, data.py, accounts.py.*
