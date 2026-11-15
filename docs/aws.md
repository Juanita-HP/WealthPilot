# AWS integration

| Service | Role in the flow | Why this service |
|---|---|---|
| Amazon Bedrock (`bedrock-runtime` Converse API: `global.anthropic.claude-haiku-4-5-20251001-v1:0`, fallback `global.amazon.nova-2-lite-v1:0`) | Runs the advisor and devil's advocate agents | Converse API with deterministic tool use inside the AWS security boundary (`us-east-1`) |
| AWS Lambda (container image) | Runs one agent turn: tools, agents, verifier | Pay per question, scales to zero; container image because pandas/numpy exceed the zip limit |
| Amazon S3 (`wealthpilot-polyfinances-008971659304`) | Data files and trained models (`inflation_model.json`, `asset_forecast.json`, `timing_model.json`) | Versioned bucket: the data behind a result can be identified; synced to local `/tmp` once per container |
| Amazon DynamoDB (`wealthpilot-traces`) | Session state (`STATE`) and the audit trail (`TURN#<timestamp>` with every receipt and verification report) | Any number shown to a user can be traced to the tool call that produced it |
| IAM | Least-privilege role; the UI/API invokes Bedrock, S3, and DynamoDB with scoped permissions | `bedrock:InvokeModel`, read-only S3 (`s3:GetObject`, `s3:ListBucket`), CRUD on `wealthpilot-traces` |
| CloudWatch / CloudTrail | Logs of Lambda and Bedrock calls | Operational trace in addition to the DynamoDB audit trail |

Refusal & throttling resilience: `BedrockLLM` in `wealthpilot/agents/llm.py` automatically falls back from `global.anthropic.claude-haiku-4-5-20251001-v1:0` to `global.amazon.nova-2-lite-v1:0` on model refusal, and translates tool-use turns across model families.

## Deploy & Sync

Prerequisites: AWS account in `us-east-1` with Bedrock access, AWS CLI / SAM CLI.

Upload the starter dataset and trained model artifacts to S3:

```bash
python scripts/upload_data.py wealthpilot-polyfinances-008971659304
```

Build and deploy the SAM stack (`infra/template.yaml`):

```bash
sam build -t infra/template.yaml
sam deploy --guided --stack-name wealthpilot --region us-east-1
```

Invoke a turn on Lambda:

```bash
aws lambda invoke --function-name <FunctionName> --cli-binary-format raw-in-base64-out --payload '{"session_id":"demo","question":"Can I put 30% of my savings in Tesla?"}' out.json
```

## Running the FastAPI + React app with live AWS services

```bash
export AWS_REGION=us-east-1
export WEALTHPILOT_LLM=bedrock
export WEALTHPILOT_MODEL=global.anthropic.claude-haiku-4-5-20251001-v1:0
export TRACE_TABLE=wealthpilot-traces
python -m wealthpilot.api
```

## Hosted website (permanent): CloudFront + S3 + Lambda

```
browser ──https──> CloudFront ──/*──────> S3 (private): React build (web/dist)
                              └─/api/*──> Lambda Function URL: FastAPI (wealthpilot.aws.api_handler, Mangum)
                                            ├─ S3 data bucket (starter CSVs, models)  → /tmp on cold start
                                            ├─ DynamoDB users table (accounts, profiles, token key)
                                            ├─ DynamoDB wealthpilot-traces (agent audit trail)
                                            └─ Amazon Bedrock (agents)
```

Template: `infra/hosting.yaml` (stack `wealthpilot-web`, separate from the agent-only stack in `infra/template.yaml`).
One address serves both the interface and the API, so the browser needs no CORS rules.

**Deploy or update** from AWS CloudShell (console top bar, `>_`), region `us-east-1`:

```bash
git clone https://github.com/Juanita-HP/wealthpilot.git && cd wealthpilot && bash scripts/deploy_aws.sh
```

The script checks that the starter CSVs are in the data bucket, uploads the models from git, builds the Lambda package
from Linux wheels (`scripts/build_lambda.py`, no Docker), deploys the stack, builds and uploads the React app, and
prints the website address. Re-running it updates the same stack and keeps the address.

**No access keys.** CloudShell runs as the signed-in console user; the Lambda function uses its IAM role. No key is
created, typed, printed, committed or stored in an environment variable. Never paste keys in chat or in the repo.

Design choices and limits, stated plainly:

- Accounts live in DynamoDB (`WEALTHPILOT_USERS_TABLE`) because Lambda's disk does not persist; the token signing
  key is generated once and stored in the same table, so every Lambda container accepts the same sign-in.
  Locally, without that variable, accounts stay in SQLite as before.
- The Lambda package excludes scikit-learn and SciPy: models are trained offline and the API only reads their JSON
  artifacts (154 MB unzipped, limit 250 MB).
- CloudFront waits at most 60 seconds for the API; an agent question that takes longer returns a 504.
- The function URL is public (CloudFront forwards to it). Everything personal still requires a signed sign-in token.
- Live quotes go through the Yahoo relay from AWS IP addresses; Yahoo may rate-limit them. The plan, time machine,
  scores and advocate use the stored starter data and keep working.
- Cost: pay per request (Lambda, DynamoDB on demand, CloudFront). Idle cost is close to zero.

## Local development without AWS

`WEALTHPILOT_LLM=anthropic` uses the first-party Claude API with the same code. Automated tests use a scripted model (`ScriptedLLM`) and fake S3/DynamoDB (`tests/test_aws.py`), so `pytest` needs no credentials.

## Status

Live AWS integration in `us-east-1` is provisioned and verified end-to-end:
- **Amazon S3**: bucket `wealthpilot-polyfinances-008971659304` stores all starter CSVs and trained model JSON artifacts (`models/inflation_model.json`, `models/asset_forecast.json`, `models/timing_model.json`).
- **Amazon DynamoDB**: table `wealthpilot-traces` (`pk`, `sk`, `PAY_PER_REQUEST`) records live multi-agent turns (`TURN#<epoch-ms>`) with tool receipts and verifier coverage reports.
- **Amazon Bedrock**: live multi-agent Advisor + Devil's Advocate tool-use orchestration verified via `BedrockLLM` (`global.anthropic.claude-haiku-4-5-20251001-v1:0` and `global.amazon.nova-2-lite-v1:0`).

