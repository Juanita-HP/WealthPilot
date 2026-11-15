"""SageMaker training: job request, launcher, entry script (offline) and the code package."""

import json
import re
import sys
import tarfile
from pathlib import Path

import pytest

from wealthpilot.aws import training

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "s3://bucket/wealthpilot/training/source/abc.tar.gz"


def request(**kw):
    return training.job_request("wealthpilot-train-20261115-120000", role_arn="arn:aws:iam::123:role/r", bucket="bucket",
                                prefix="wealthpilot", source=SOURCE, region="us-east-1", git_commit="abc", **kw)


def test_job_uses_the_managed_image_and_script_mode():
    r = request()
    assert r["AlgorithmSpecification"]["TrainingImage"] == \
        "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.4-2-cpu-py3"
    hp = {k: json.loads(v) for k, v in r["HyperParameters"].items()}  # every value is JSON-encoded, as the SDK does
    assert hp["sagemaker_program"] == "entry.py" and hp["sagemaker_submit_directory"] == SOURCE
    assert hp["fetch"] == "true" and json.loads(request(fetch=False)["HyperParameters"]["fetch"]) == "false"
    assert {c["ChannelName"]: c["DataSource"]["S3DataSource"]["S3Uri"] for c in r["InputDataConfig"]} == {
        "external": "s3://bucket/wealthpilot/external/", "models": "s3://bucket/wealthpilot/models/"}
    assert r["OutputDataConfig"]["S3OutputPath"] == "s3://bucket/wealthpilot/training/"  # candidates, not models/
    assert r["ResourceConfig"]["InstanceType"] == "ml.m5.large"
    with pytest.raises(ValueError):
        training.image_uri("ap-south-2")


def test_metric_regexes_match_what_the_entry_script_prints(capsys):
    sys.path.insert(0, str(ROOT / "training"))
    import entry
    entry.log_metrics("asset_forecast", {"BTC-USD": {"r2_oos": -0.33}, "GLD": {"r2_oos": 0.01}})
    entry.log_metrics("timing", {"XIU.TO": {"usable": False}})
    entry.log_metrics("inflation", {"12m": {"mae": 1.04}})
    out = capsys.readouterr().out
    found = {d["Name"] for d in request()["AlgorithmSpecification"]["MetricDefinitions"] if re.search(d["Regex"], out)}
    assert found == {"r2_oos_btc", "r2_oos_gld", "timing_usable_xiu", "inflation_mae_12m"}


def test_launcher_starts_one_job(monkeypatch):
    calls = []

    class Client:
        def create_training_job(self, **kw):
            calls.append(kw)

    for k, v in {"TRAINING_ROLE_ARN": "arn:aws:iam::123:role/r", "DATA_BUCKET": "bucket", "TRAINING_SOURCE": SOURCE,
                 "AWS_REGION": "us-east-1", "GIT_COMMIT": "abc"}.items():
        monkeypatch.setenv(k, v)
    out = training.launch_handler({"fetch": False}, None, client=Client())
    assert len(calls) == 1 and calls[0]["TrainingJobName"] == out["job"] and out["job"].startswith("wealthpilot-train-")
    assert out["output"].endswith(f"/training/{out['job']}/output/")


def test_entry_trains_inflation_offline_and_matches_the_live_model(tmp_path, monkeypatch):
    import os
    monkeypatch.setattr(os, "environ", os.environ.copy())  # the entry script points the data loaders at its folder
    sys.path.insert(0, str(ROOT / "training"))
    import entry
    code = entry.main(["--fetch", "false", "--models", "inflation", "--out", str(tmp_path / "model"),
                       "--snapshot", str(tmp_path / "data")])
    assert code == 0
    report = json.loads((tmp_path / "model" / "report.json").read_text())
    inf = report["models"]["inflation"]
    assert inf["status"] == "ok" and inf["candidate"] == inf["current"]  # same data and code: same model
    art = json.loads((tmp_path / "model" / "inflation_model.json").read_text())
    assert art["provenance"]["data"]["macro_history.csv"]["sha256"] and art["provenance"]["libraries"]["scikit-learn"]
    assert (tmp_path / "data" / "data" / "macro_history.csv").exists()  # snapshot of the exact inputs


def test_code_package_has_the_entry_point_at_its_root(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_training
    monkeypatch.setattr(build_training, "BUILD", tmp_path)
    with tarfile.open(build_training.source_tarball()) as tar:
        names = set(tar.getnames())
    assert {"entry.py", "requirements.txt", "wealthpilot/timing.py", "scripts/fetch_long_history.py"} <= names
    assert not any("__pycache__" in n for n in names)
    launcher = build_training.launcher()
    assert sorted(p.name for p in launcher.rglob("*.py")) == ["__init__.py", "__init__.py", "training.py"]
