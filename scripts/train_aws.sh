#!/usr/bin/env bash
# Retrain the three models on Amazon SageMaker and show how the candidates compare with the live models.
#
# Run it in AWS CloudShell, region us-east-1, from the repository folder:
#   bash scripts/train_aws.sh
#
# What it does: packages the training code, deploys/updates the training stack (infra/training.yaml: SageMaker role,
# launcher Lambda, monthly schedule), starts one training job and waits for it (a few minutes, about 1-2 cents).
# The website does NOT change: the new models are candidates until you run scripts/promote_models.sh <job>.
# No access key is created, typed, printed or saved.
#
# Options (environment variables): DATA_BUCKET, DATA_PREFIX (default wealthpilot), FETCH (default true: download
# fresh price histories; false: retrain on the stored data only), STACK_NAME (default wealthpilot-training).
set -euo pipefail

cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK="${STACK_NAME:-wealthpilot-training}"
PREFIX="${DATA_PREFIX:-wealthpilot}"
FETCH="${FETCH:-true}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

step() { printf '\n==> %s\n' "$*"; }
for tool in aws sam python3; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool (AWS CloudShell has all of them)"; exit 1; }
done

if [ -z "${DATA_BUCKET:-}" ]; then
  DATA_BUCKET="$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'wealthpilot-polyfinances')].Name | [0]" --output text)"
fi
if [ -z "$DATA_BUCKET" ] || [ "$DATA_BUCKET" = "None" ]; then
  echo "No data bucket found. Run again with DATA_BUCKET=<bucket name> bash scripts/train_aws.sh"; exit 1
fi
COMMIT="$(git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"
SOURCE="s3://$DATA_BUCKET/$PREFIX/training/source/$COMMIT.tar.gz"

step "1/4 Package the training code (commit $COMMIT)"
python3 scripts/build_training.py
aws s3 cp --only-show-errors build/training_source.tar.gz "$SOURCE"
echo "uploaded $SOURCE"

step "2/4 Deploy the training stack $STACK"
sam deploy \
  --template-file infra/training.yaml \
  --stack-name "$STACK" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "DataBucketName=$DATA_BUCKET" "DataPrefix=$PREFIX" "TrainingSource=$SOURCE" "GitCommit=$COMMIT"

LAUNCHER="$(aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='LauncherFunctionName'].OutputValue" --output text)"

step "3/4 Start the SageMaker training job"
RESULT="$(mktemp)"
aws lambda invoke --function-name "$LAUNCHER" --cli-binary-format raw-in-base64-out \
  --payload "{\"fetch\": $FETCH}" "$RESULT" >/dev/null
JOB="$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('job') or ''); sys.exit(0 if d.get('job') else 1)" "$RESULT")" \
  || { echo "The launcher failed:"; cat "$RESULT"; echo; exit 1; }
echo "Job: $JOB"
echo "Follow it in the console: SageMaker > Training > Training jobs > $JOB"

step "4/4 Wait for the job (usually 3 to 8 minutes, most of it starting the machine)"
aws sagemaker wait training-job-completed-or-stopped --training-job-name "$JOB" || true
aws sagemaker describe-training-job --training-job-name "$JOB" \
  --query "{status: TrainingJobStatus, reason: FailureReason, seconds: TrainingTimeInSeconds, billable_seconds: BillableTimeInSeconds}" \
  --output table
aws sagemaker describe-training-job --training-job-name "$JOB" --query "FinalMetricDataList[].[MetricName, Value]" --output table

STATUS="$(aws sagemaker describe-training-job --training-job-name "$JOB" --query TrainingJobStatus --output text)"
if [ "$STATUS" != "Completed" ]; then
  echo "The job did not complete ($STATUS). Logs: CloudWatch > Log groups > /aws/sagemaker/TrainingJobs > $JOB"; exit 1
fi
bash scripts/promote_models.sh "$JOB" --report-only
printf '\nThe website still uses its current models. To publish these candidates:\n  bash scripts/promote_models.sh %s\n' "$JOB"
