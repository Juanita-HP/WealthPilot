# WealthPilot — AWS Architecture

**PolyFinances Datathon 2026 · Architecture map · Educational investment simulation**

**Live application:** https://d3pmr84q14pg9z.cloudfront.net/  
**Primary AWS region:** \`us-east-1\`  
**Scope:** Hosting, API, explainable AI, data storage, auditability and model training.

## 1. AWS service map

The diagram shows **where each AWS service fits in the user-facing application**. The Advisor, Devil's Advocate and deterministic Verifier are **application components**; Bedrock provides models, while the orchestration and verification code execute in Lambda.

\`\`\`mermaid
flowchart TB
    USER["Investor<br/>Web browser"]

    subgraph AWS["WEALTHPILOT ON AWS · us-east-1"]
      CF["Amazon CloudFront<br/>HTTPS entry point"]
      SITE["Amazon S3<br/>Private website bucket<br/>React + Vite build"]
      API["AWS Lambda · Function URL<br/>FastAPI + Mangum<br/>Financial tools + agent orchestration<br/>Deterministic verifier"]
      DATA["Amazon S3<br/>Market data + FX + macro series<br/>Published model artifacts"]
      USERS["Amazon DynamoDB<br/>Accounts and investor profiles"]
      BEDROCK["Amazon Bedrock<br/>Advisor + Devil's Advocate<br/>Claude Haiku 4.5 · Nova fallback"]
      AUDIT["Amazon DynamoDB<br/>Session state + agent traces<br/>Calculation receipts"]
      LOG["Amazon CloudWatch<br/>Lambda and training logs"]

      CF -->|"Static web pages"| SITE
      CF -->|"/api/* HTTPS"| API
      API -->|"Load datasets / models"| DATA
      API <-->|"Account and profile data"| USERS
      API -->|"Model requests"| BEDROCK
      API -->|"Receipts and verification records"| AUDIT
      API -.->|"Execution logs"| LOG
    end

    USER -->|"HTTPS"| CF

    classDef primary fill:#fff7e6,stroke:#c21807,color:#171717,stroke-width:2px
    classDef storage fill:#ffffff,stroke:#d5a027,color:#171717,stroke-width:1.5px
    classDef observer fill:#f7f7f7,stroke:#737373,color:#171717
    class CF,API,BEDROCK primary
    class SITE,DATA,USERS,AUDIT storage
    class LOG observer
\`\`\`

### How one investor request is handled

1. **CloudFront** serves the React interface from a **private S3 website bucket**. Requests to \`/api/*\` go to a Lambda Function URL, which hosts the **FastAPI** backend through **Mangum**.
2. **Lambda** retrieves investor context from **DynamoDB**, reads the necessary data and published model files from **S3**, and runs Python-based financial calculations.
3. **Amazon Bedrock** powers the **Advisor** and **Devil's Advocate**. They interpret evidence and challenge assumptions; the Python **Verifier** checks numerical statements against tool-generated calculation receipts.
4. **DynamoDB** stores session/audit records, including receipts and verification results. **CloudWatch** provides operational logs.

**Important distinction:** the Verifier is deterministic **Python code in Lambda**, not a separate AWS service or an LLM that approves its own answers.

## 2. Model training and publication

The platform separates **model retraining** from **production use**. Training candidates do not automatically replace the live models.

\`\`\`mermaid
flowchart LR
    SCHED["Amazon EventBridge Scheduler<br/>Monthly schedule configured"]
    MANUAL["Manual AWS CloudShell<br/>train_aws.sh"]
    LAUNCH["AWS Lambda<br/>Training launcher"]
    INPUT["Amazon S3<br/>Datasets + source package"]
    SM["Amazon SageMaker<br/>Managed training job"]
    CAND["Amazon S3<br/>Candidate models + evaluation"]
    CHECK{"Human review<br/>and approval"}
    LIVE["Amazon S3<br/>Published models"]
    API["AWS Lambda API<br/>Loads published models"]

    SCHED --> LAUNCH
    MANUAL --> LAUNCH
    INPUT --> SM
    LAUNCH --> SM
    SM --> CAND
    CAND --> CHECK
    CHECK -->|"Approved via promote_models.sh"| LIVE
    LIVE --> API

    classDef primary fill:#fff7e6,stroke:#c21807,color:#171717,stroke-width:2px
    classDef storage fill:#ffffff,stroke:#d5a027,color:#171717,stroke-width:1.5px
    class SCHED,LAUNCH,SM,API primary
    class INPUT,CAND,LIVE storage
\`\`\`

- **SageMaker Training Jobs** retrain the inflation, asset forecasting and market-timing models using time-aware evaluation. The jobs write **candidate** artifacts and metrics to S3.
- **EventBridge Scheduler** is configured for a monthly trigger; the team can also start training on demand.
- **Human approval** is required before \`scripts/promote_models.sh\` publishes a candidate to the live model location in S3. There is **no always-on SageMaker inference endpoint**; model artifacts are loaded by the Python API.

## 3. AWS services and their responsibilities

| AWS service | Responsibility in WealthPilot |
|---|---|
| **Amazon CloudFront** | Public HTTPS distribution; routes website traffic and API requests |
| **Amazon S3** | Private React website hosting; separate storage for financial datasets and model files |
| **AWS Lambda** | Runs the FastAPI API, financial tools, agent workflow and deterministic verification; separate training launcher |
| **Amazon Bedrock** | LLM inference for Advisor and Devil's Advocate; Claude Haiku 4.5 with Amazon Nova fallback |
| **Amazon DynamoDB** | Investor accounts/profiles and separate trace/session audit data |
| **Amazon SageMaker** | Managed training jobs and evaluated candidate models |
| **Amazon EventBridge Scheduler** | Configured recurring model retraining trigger |
| **AWS IAM** | Execution roles and service-to-service permissions |
| **Amazon CloudWatch** | Operational logs for Lambda and model training |

## 4. Security, governance and limitations

- **Private website origin:** CloudFront reads the private S3 site bucket through **Origin Access Control**. The browser does not receive unrestricted access to the bucket.
- **API access:** the Lambda Function URL is configured with \`AuthType: NONE\` and is routed through CloudFront. It is **not private by virtue of CloudFront**; protected user operations use application-level signed authentication.
- **IAM permissions:** Lambda receives the permissions required to read S3, use the relevant DynamoDB tables and invoke Bedrock. No AWS access keys should be stored in the repository.
- **Financial accountability:** calculated values and agent claims are checked against traceable receipts; forecasts, assumptions and historical observations remain clearly distinct.
- **External data:** Yahoo Finance, the Bank of Canada and FRED are **data providers**, not AWS services. The Jupyter EDA report is research evidence, **not** a claim that EDA runs inside SageMaker.
- **Scope:** WealthPilot is an educational prototype. It does **not** execute trades or provide regulated investment advice.

## 5. Implementation references

This map is grounded in the repository's AWS configuration and application code:

- [Website infrastructure (CloudFront, S3, Lambda, DynamoDB)](../infra/hosting.yaml)
- [Agent-oriented AWS stack](../infra/template.yaml)
- [SageMaker training and scheduling stack](../infra/training.yaml)
- [AWS integration notes and operational status](../infra/aws.md)
- [API Lambda entry point](../wealthpilot/aws/api_handler.py)
- [Agent Lambda entry point](../wealthpilot/aws/lambda_handler.py)
- [Training launcher](../wealthpilot/aws/training.py)
- [Deployment script](../scripts/deploy_aws.sh) · [Training script](../scripts/train_aws.sh) · [Manual model promotion](../scripts/promote_models.sh)

*Evidence note:* This is an **architecture-as-configured** document. The repository's AWS notes report end-to-end checks for Bedrock, S3 and DynamoDB; this diagram itself is **not** an independent live AWS account audit.
