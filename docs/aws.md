# AWS integration

| Service | Role in the flow | Why this service |
|---|---|---|
| Amazon Bedrock (Claude in Amazon Bedrock, `bedrock-mantle`, model `anthropic.claude-opus-5-5`) | Runs the advisor and devil's advocate agents | Messages API with tool use inside the AWS security boundary; `ca-central-1` is a supported region, so prompts can stay in Canada |
| AWS Lambda (container image) | Runs one agent turn: tools, agents, verifier | Pay per question, scales to zero; container image because pandas/numpy exceed the zip limit |
| Amazon S3 | Data files and the trained inflation model | Versioned bucket: the data behind a result can be identified; copied to /tmp once per container |
| Amazon DynamoDB | Session state and the audit trail (every turn with its receipts and verification report) | Any number shown to a user can be traced to the tool call that produced it |
| IAM | Least-privilege role; the UI invokes the function with IAM, no public endpoint | `bedrock-mantle:CreateInference`, read-only S3, CRUD on one table |
| CloudWatch / CloudTrail | Logs of Lambda and Bedrock calls | Operational trace in addition to the DynamoDB audit trail |

Refusal handling: server-side fallbacks are not available on Bedrock, so the client registers the SDK's `BetaRefusalFallbackMiddleware` (fallback `anthropic.claude-opus-4-8`).

## Deploy

Prerequisites: AWS account with Bedrock access to Claude Opus 5.5 (and Opus 4.8 for fallback) in your region, AWS SAM CLI, Docker.

```bash
sam build -t infra/template.yaml
```

```bash
sam deploy --guided --stack-name wealthpilot --region ca-central-1
```

```bash
python scripts/upload_data.py <DataBucketName from the outputs>
```

Invoke a turn:

```bash
aws lambda invoke --function-name <FunctionName> --cli-binary-format raw-in-base64-out --payload '{"session_id":"demo","question":"Can I put 30% of my savings in Tesla?"}' out.json
```

## Local development without AWS

`WEALTHPILOT_LLM=anthropic` uses the first-party Claude API with the same code (server-side refusal fallback enabled). Tests use a scripted model and fake S3/DynamoDB, so `pytest` needs no credentials.

## Status

The template, container and handler are written and tested with fakes. They have not been deployed from the build environment (no AWS credentials there); deploying and running one live turn is the next step for the team.
