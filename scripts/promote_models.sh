#!/usr/bin/env bash
# Compare a SageMaker training job's candidate models with the live ones, and (after you confirm) publish them.
#
# Run it in AWS CloudShell from the repository folder:
#   bash scripts/promote_models.sh <job name>                 # shows the comparison, asks before publishing
#   bash scripts/promote_models.sh <job name> --report-only   # comparison only
#
# Publishing copies the candidates to <prefix>/models/ in the data bucket (tagged with the job name) and refreshes the
# website's API so its next requests load them. To go back to the models in git:
#   FORCE_GIT_MODELS=1 bash scripts/deploy_aws.sh
set -euo pipefail

cd "$(dirname "$0")/.."
JOB="${1:?Usage: bash scripts/promote_models.sh <training job name> [--report-only]}"
MODE="${2:-}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
PREFIX="${DATA_PREFIX:-wealthpilot}"
WEB_STACK="${WEB_STACK_NAME:-wealthpilot-web}"
export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"

if [ -z "${DATA_BUCKET:-}" ]; then
  DATA_BUCKET="$(aws s3api list-buckets --query "Buckets[?starts_with(Name, 'wealthpilot-polyfinances')].Name | [0]" --output text)"
fi

WORK="$(mktemp -d)"
aws s3 cp --only-show-errors "s3://$DATA_BUCKET/$PREFIX/training/$JOB/output/model.tar.gz" "$WORK/model.tar.gz"
tar -xzf "$WORK/model.tar.gz" -C "$WORK"

python3 - "$WORK/report.json" <<'EOF'
import json, sys
r = json.load(open(sys.argv[1]))
p = r["provenance"]
print(f"\nJob {r['job']} - commit {r['git_commit']} - Python {p['python']}, scikit-learn {p['libraries']['scikit-learn']}, "
      f"pandas {p['libraries']['pandas']}")
print("Data used: " + ", ".join(f"{k} ({v['bytes'] // 1000} kB)" for k, v in p["data"].items()))
def fmt(v):
    return "-" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
for name, m in r["models"].items():
    print(f"\n{name}: {m['status']}" + (f" ({m.get('error')})" if m["status"] != "ok" else ""))
    cand, cur = m.get("candidate") or {}, m.get("current") or {}
    for key in cand:
        c, l = cand[key], cur.get(key, {})
        cells = [f"{k} {fmt(l.get(k))} -> {fmt(v)}" for k, v in c.items()]
        print(f"  {key:8} " + " | ".join(cells))
print("\n(live -> candidate)")
EOF

if [ "$MODE" = "--report-only" ]; then exit 0; fi
if python3 -c "import json,sys; r=json.load(open(sys.argv[1])); sys.exit(0 if all(m['status']=='ok' for m in r['models'].values()) else 1)" "$WORK/report.json"; then :; else
  echo "At least one model failed: nothing published."; exit 1
fi

read -r -p "Publish these models to the live website? [y/N] " answer
case "$answer" in y|Y|yes|oui) ;; *) echo "Nothing published."; exit 0 ;; esac

for f in inflation_model.json asset_forecast.json timing_model.json; do
  aws s3 cp --only-show-errors "$WORK/$f" "s3://$DATA_BUCKET/$PREFIX/models/$f" --metadata "promoted-from=$JOB"
  echo "published models/$f"
done
API="$(aws cloudformation describe-stacks --stack-name "$WEB_STACK" --query "Stacks[0].Outputs[?OutputKey=='ApiFunctionName'].OutputValue" --output text 2>/dev/null || true)"
if [ -n "$API" ] && [ "$API" != "None" ]; then
  # Any configuration change starts fresh API instances, which download the new models on their first request.
  aws lambda update-function-configuration --function-name "$API" --description "models from $JOB" >/dev/null
  echo "Website API refreshed: it now uses the models from $JOB."
fi
