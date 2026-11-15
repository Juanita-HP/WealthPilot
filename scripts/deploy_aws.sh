#!/usr/bin/env bash
# Deploy (or update) the hosted WealthPilot website: React on S3 + CloudFront, FastAPI on Lambda.
#
# Run it in AWS CloudShell (console, top bar ">_" icon), region us-east-1:
#   git clone https://github.com/Juanita-HP/wealthpilot.git && cd wealthpilot && bash scripts/deploy_aws.sh
#
# CloudShell is already signed in as you: no access key is created, typed, printed or saved by this script.
# Re-running it updates the same stack and keeps the same website address.
#
# Optional environment variables: DATA_BUCKET (S3 bucket with the starter data), DATA_PREFIX (default wealthpilot),
# STACK_NAME (default wealthpilot-web), TRACE_TABLE (default wealthpilot-traces).
set -euo pipefail

cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
STACK="${STACK_NAME:-wealthpilot-web}"
PREFIX="${DATA_PREFIX:-wealthpilot}"
TRACE="${TRACE_TABLE:-wealthpilot-traces}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

step() { printf '\n==> %s\n' "$*"; }
for tool in aws sam python3 npm; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool (AWS CloudShell has all of them)"; exit 1; }
done

step "1/6 Data bucket"
if [ -z "${DATA_BUCKET:-}" ]; then
  DATA_BUCKET="$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'wealthpilot-polyfinances')].Name | [0]" --output text)"
fi
if [ -z "$DATA_BUCKET" ] || [ "$DATA_BUCKET" = "None" ]; then
  echo "No data bucket found. Run again with DATA_BUCKET=<bucket name> bash scripts/deploy_aws.sh"; exit 1
fi
echo "Using s3://$DATA_BUCKET/$PREFIX/"
# The organizers' starter CSVs are not in git (Yahoo redistribution limits): they must already be in the bucket,
# or in data/starter/ here (upload them to CloudShell with Actions > Upload file).
for f in assets_universe.csv prices_daily.csv corporate_actions.csv fx_usdcad_daily.csv macro_rates.csv; do
  if ! aws s3api head-object --bucket "$DATA_BUCKET" --key "$PREFIX/starter/$f" >/dev/null 2>&1; then
    if [ -f "data/starter/$f" ]; then
      aws s3 cp --only-show-errors "data/starter/$f" "s3://$DATA_BUCKET/$PREFIX/starter/$f"
      echo "uploaded starter/$f"
    else
      echo "Missing s3://$DATA_BUCKET/$PREFIX/starter/$f and data/starter/$f."
      echo "Upload the starter CSVs to that S3 folder (S3 console > bucket > Upload), then run this script again."
      exit 1
    fi
  fi
done
# Files that are in git (models, macro history, international fund list): keep the bucket in step with the code.
for rel in models/inflation_model.json models/asset_forecast.json models/timing_model.json; do
  aws s3 cp --only-show-errors "$rel" "s3://$DATA_BUCKET/$PREFIX/$rel"
done
for f in macro_history.csv assets_universe_extra.csv; do
  aws s3 cp --only-show-errors "data/external/$f" "s3://$DATA_BUCKET/$PREFIX/external/$f"
done
if [ -f data/external/extra_prices.csv ]; then
  aws s3 cp --only-show-errors data/external/extra_prices.csv "s3://$DATA_BUCKET/$PREFIX/external/extra_prices.csv"
fi
aws s3api head-object --bucket "$DATA_BUCKET" --key "$PREFIX/external/extra_prices.csv" >/dev/null 2>&1 \
  || echo "Note: no international fund prices (external/extra_prices.csv): plans use Canada and the U.S. only, and say so."

step "2/6 Lambda package (Linux wheels, no Docker)"
python3 scripts/build_lambda.py

step "3/6 Deploy the stack $STACK (first run: about 5 minutes, CloudFront takes the longest)"
sam deploy \
  --template-file infra/hosting.yaml \
  --stack-name "$STACK" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides "DataBucketName=$DATA_BUCKET" "DataPrefix=$PREFIX" "TraceTableName=$TRACE"

out() { aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
SITE_BUCKET="$(out SiteBucketName)"
DISTRIBUTION="$(out DistributionId)"
URL="$(out WebsiteUrl)"

step "4/6 Build the React interface"
(cd web && npm ci --no-audit --no-fund --loglevel=error && npm run build)

step "5/6 Upload the interface"
# Hashed files never change: cache them for a year. index.html is checked on every visit, so updates show at once.
aws s3 sync --only-show-errors --delete web/dist "s3://$SITE_BUCKET" --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp --only-show-errors web/dist/index.html "s3://$SITE_BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/index.html" "/" >/dev/null

step "6/6 Check"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/api/meta" || true)"
if [ "$code" = "200" ]; then echo "API answers through CloudFront (HTTP 200)."
else echo "API check returned HTTP $code. A first deployment can take a few more minutes; open the site again shortly."; fi

printf '\nWealthPilot is online: %s\n' "$URL"
