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

## Local development without AWS

`WEALTHPILOT_LLM=anthropic` uses the first-party Claude API with the same code. Automated tests use a scripted model (`ScriptedLLM`) and fake S3/DynamoDB (`tests/test_aws.py`), so `pytest` needs no credentials.

## Status

Live AWS integration in `us-east-1` is provisioned and verified end-to-end:
- **Amazon S3**: bucket `wealthpilot-polyfinances-008971659304` stores all starter CSVs and trained model JSON artifacts (`models/inflation_model.json`, `models/asset_forecast.json`, `models/timing_model.json`).
- **Amazon DynamoDB**: table `wealthpilot-traces` (`pk`, `sk`, `PAY_PER_REQUEST`) records live multi-agent turns (`TURN#<epoch-ms>`) with tool receipts and verifier coverage reports.
- **Amazon Bedrock**: live multi-agent Advisor + Devil's Advocate tool-use orchestration verified via `BedrockLLM` (`global.anthropic.claude-haiku-4-5-20251001-v1:0` and `global.amazon.nova-2-lite-v1:0`).

