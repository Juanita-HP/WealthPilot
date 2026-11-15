"""Start a SageMaker training job that retrains the three models (training/entry.py).

Runs as a small Lambda function (infra/training.yaml), started once a month by EventBridge Scheduler and on demand
by scripts/train_aws.sh. The job uses AWS's managed scikit-learn image, reads the data bucket and writes CANDIDATE
models under <prefix>/training/<job>/; the website keeps its current models until scripts/promote_models.sh.

Environment: TRAINING_ROLE_ARN, DATA_BUCKET, DATA_PREFIX, TRAINING_SOURCE (s3 URI of the code tarball),
GIT_COMMIT, TRAINING_INSTANCE (default ml.m5.large).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

# AWS-managed scikit-learn training images (sagemaker-scikit-learn:1.4-2-cpu-py3: scikit-learn 1.9, pandas 2.2).
# Registry account per region, from the SageMaker Python SDK's image configuration.
IMAGE_TAG = "1.4-2-cpu-py3"
IMAGE_ACCOUNTS = {"us-east-1": "683313688378", "us-east-2": "257758044811", "us-west-2": "246618743249",
                  "ca-central-1": "341280168497", "ca-west-1": "190319476487", "eu-west-1": "141502667606"}
ENTRY = "entry.py"
METRICS = ["inflation_mae_3m", "inflation_mae_6m", "inflation_mae_12m", "r2_oos_btc", "r2_oos_eth", "r2_oos_gld",
           "timing_usable_qqq", "timing_usable_vgt", "timing_usable_spy", "timing_usable_xiu"]


def image_uri(region: str) -> str:
    if region not in IMAGE_ACCOUNTS:
        raise ValueError(f"No managed scikit-learn image configured for {region}. Use one of: {', '.join(IMAGE_ACCOUNTS)}.")
    return f"{IMAGE_ACCOUNTS[region]}.dkr.ecr.{region}.amazonaws.com/sagemaker-scikit-learn:{IMAGE_TAG}"


def job_name(now: datetime | None = None) -> str:
    return "wealthpilot-train-" + (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")


def job_request(name: str, *, role_arn: str, bucket: str, prefix: str, source: str, region: str,
                git_commit: str = "unknown", instance: str = "ml.m5.large", fetch: bool = True) -> dict:
    """Arguments of sagemaker.create_training_job (script mode: the toolkit runs entry.py from the tarball)."""
    base = f"s3://{bucket}/{prefix.strip('/')}"
    image = image_uri(region)

    def channel(name_: str, folder: str) -> dict:
        return {"ChannelName": name_, "InputMode": "File", "DataSource": {"S3DataSource": {
            "S3DataType": "S3Prefix", "S3Uri": f"{base}/{folder}/", "S3DataDistributionType": "FullyReplicated"}}}

    # Script-mode hyperparameters are JSON-encoded strings (as the SageMaker Python SDK sends them).
    hp = {"sagemaker_program": ENTRY, "sagemaker_submit_directory": source, "sagemaker_region": region,
          "sagemaker_container_log_level": 20, "fetch": "true" if fetch else "false", "git_commit": git_commit}
    return {
        "TrainingJobName": name,
        "RoleArn": role_arn,
        "AlgorithmSpecification": {
            "TrainingImage": image, "TrainingInputMode": "File",
            "MetricDefinitions": [{"Name": m, "Regex": rf"metric {m}=(-?[0-9.]+)"} for m in METRICS],
        },
        "HyperParameters": {k: json.dumps(v) for k, v in hp.items()},
        "InputDataConfig": [channel("external", "external"), channel("models", "models")],
        "OutputDataConfig": {"S3OutputPath": f"{base}/training/"},
        "ResourceConfig": {"InstanceType": instance, "InstanceCount": 1, "VolumeSizeInGB": 5},
        "StoppingCondition": {"MaxRuntimeInSeconds": 3600},
        "Environment": {"WEALTHPILOT_TRAINING_IMAGE": image},
        "Tags": [{"Key": "project", "Value": "wealthpilot"}, {"Key": "git_commit", "Value": git_commit[:128]}],
    }


def launch_handler(event, context, client=None) -> dict:
    """Lambda entry point. event may override {"fetch": false} (retrain on the stored data only)."""
    event = event or {}
    region = os.environ.get("AWS_REGION", "us-east-1")
    name = job_name()
    request = job_request(
        name, role_arn=os.environ["TRAINING_ROLE_ARN"], bucket=os.environ["DATA_BUCKET"],
        prefix=os.environ.get("DATA_PREFIX", "wealthpilot"), source=os.environ["TRAINING_SOURCE"], region=region,
        git_commit=os.environ.get("GIT_COMMIT", "unknown"),
        instance=os.environ.get("TRAINING_INSTANCE", "ml.m5.large"), fetch=bool(event.get("fetch", True)))
    if client is None:
        import boto3
        client = boto3.client("sagemaker", region_name=region)
    client.create_training_job(**request)
    return {"job": name, "output": request["OutputDataConfig"]["S3OutputPath"] + name + "/output/"}
