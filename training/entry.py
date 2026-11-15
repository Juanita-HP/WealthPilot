"""Amazon SageMaker training job: retrain WealthPilot's three models and write CANDIDATE artifacts.

Runs inside AWS's managed scikit-learn container (see wealthpilot/aws/training.py). The same code as
scripts/train_*.py, so the protocol does not change: walk-forward validation, thresholds fixed in advance.

Inputs (SageMaker channels):
    external  s3://<data bucket>/<prefix>/external/  macro history (+ price histories, refreshed below)
    models    s3://<data bucket>/<prefix>/models/    the models the website uses now, for comparison

Outputs:
    /opt/ml/model/        inflation_model.json, asset_forecast.json, timing_model.json, report.json
                          (SageMaker uploads them as model.tar.gz under <prefix>/training/<job>/output/)
    /opt/ml/output/data/  the exact data used (snapshot), for reproducibility

Nothing here touches the live website: the candidates are published only by scripts/promote_models.sh.
Run locally (no AWS): python training/entry.py --fetch false --external data/external --models models --out /tmp/x
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "wealthpilot").exists() else HERE.parent  # tarball root in SageMaker, repo root locally
sys.path.insert(0, str(ROOT))

MODELS = ("inflation", "asset_forecast", "timing")
FILES = {"inflation": "inflation_model.json", "asset_forecast": "asset_forecast.json", "timing": "timing_model.json"}


def _bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y"}


def _args(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--fetch", default="true", help="download fresh price histories from Yahoo Finance")
    p.add_argument("--models", default=",".join(MODELS))
    p.add_argument("--git_commit", default="unknown")
    p.add_argument("--external", default=os.environ.get("SM_CHANNEL_EXTERNAL", str(ROOT / "data" / "external")))
    p.add_argument("--current", default=os.environ.get("SM_CHANNEL_MODELS", str(ROOT / "models")))
    p.add_argument("--out", default=os.environ.get("SM_MODEL_DIR"))
    p.add_argument("--snapshot", default=os.environ.get("SM_OUTPUT_DATA_DIR"))
    args, _ = p.parse_known_args(argv)  # SageMaker may pass extra arguments
    return args


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def job_name() -> str:
    name = os.environ.get("TRAINING_JOB_NAME")
    if not name and os.environ.get("SM_TRAINING_ENV"):
        name = json.loads(os.environ["SM_TRAINING_ENV"]).get("job_name")
    return name or "local"


def metric(name: str, value) -> None:
    """One line per metric: SageMaker reads them from the log (MetricDefinitions) and charts them."""
    if value is not None:
        print(f"metric {name}={float(value):.6f}", flush=True)


# ----------------------------------------------------------------------------- headline numbers per model


def summary_inflation(art: dict) -> dict:
    out = {}
    for h, spec in art["horizons"].items():
        used = spec["method_used"]
        out[f"{h}m"] = {"method_used": used, "mae": spec["evaluation"]["methods"][used]["mae"]}
    return out


def summary_asset_forecast(art: dict) -> dict:
    from wealthpilot import forecast
    out = {}
    for t, a in art["assets"].items():
        gb = a["models"]["gradient_boosting"]
        shown = gb["rating"]["label"] in ("Good", "Very good") and gb["dm_p"] is not None \
            and gb["dm_p"] < forecast.SIGNIFICANCE
        out[t] = {"r2_oos": gb["r2_oos"], "rating": gb["rating"]["label"], "dm_p": gb["dm_p"], "gauge_shown": shown}
    return out


def summary_timing(art: dict) -> dict:
    out = {}
    for t, a in art["assets"].items():
        s = a["scenarios"]["main"]["summary"]
        out[t] = {"usable": bool(a["usable"]), "wins_sharpe": f"{s['wins_sharpe']}/{s['tests']}", "p_value": s["p_value"]}
    return out


SUMMARY = {"inflation": summary_inflation, "asset_forecast": summary_asset_forecast, "timing": summary_timing}


def log_metrics(name: str, s: dict) -> None:
    if name == "inflation":
        for h, v in s.items():
            metric(f"inflation_mae_{h}", v["mae"])
    elif name == "asset_forecast":
        for t, v in s.items():
            metric(f"r2_oos_{t.replace('-USD', '').lower()}", v["r2_oos"])
    else:
        for t, v in s.items():
            metric(f"timing_usable_{t.replace('.TO', '').lower()}", 1.0 if v["usable"] else 0.0)


# ----------------------------------------------------------------------------- training


def train_one(name: str, external: Path):
    if name == "inflation":
        import pandas as pd
        from wealthpilot import inflation
        return inflation.train(pd.read_csv(external / "macro_history.csv", parse_dates=["date"]))
    if name == "asset_forecast":
        from wealthpilot import forecast
        return forecast.train()
    from wealthpilot import timing
    from wealthpilot.agents.ledger import jsonable
    return jsonable(timing.train())


def fetch_prices() -> None:
    """Fresh daily histories from Yahoo Finance, with the same scripts as on a laptop."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import fetch_long_history
    import fetch_timing_history
    fetch_long_history.main()
    fetch_timing_history.main()


def main(argv=None) -> int:
    args = _args(argv)
    out = Path(args.out or tempfile.mkdtemp(prefix="wealthpilot-train-"))
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="wealthpilot-data-"))
    external = work / "external"
    shutil.copytree(args.external, external)
    os.environ["WEALTHPILOT_DATA_DIR"] = str(work / "starter")  # data.EXTERNAL_DIR = <work>/external (set before import)

    started = time.time()
    print(f"WealthPilot training job {job_name()} · commit {args.git_commit} · Python {platform.python_version()}",
          flush=True)
    if _bool(args.fetch):
        fetch_prices()

    import numpy
    import pandas
    import scipy
    import sklearn
    data_files = sorted(p for p in external.glob("*.csv"))
    provenance = {
        "trained_by": "Amazon SageMaker training job" if job_name() != "local" else "local run of training/entry.py",
        "job": job_name(), "git_commit": args.git_commit,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "image": os.environ.get("WEALTHPILOT_TRAINING_IMAGE"), "python": platform.python_version(),
        "libraries": {"numpy": numpy.__version__, "pandas": pandas.__version__, "scikit-learn": sklearn.__version__,
                      "scipy": scipy.__version__},
        "data": {p.name: {"sha256": sha256(p), "bytes": p.stat().st_size} for p in data_files},
    }
    if args.snapshot:  # the exact inputs, kept next to the models (output.tar.gz)
        snap = Path(args.snapshot) / "data"
        snap.mkdir(parents=True, exist_ok=True)
        for p in data_files:
            shutil.copy(p, snap / p.name)

    report = {"job": job_name(), "git_commit": args.git_commit, "provenance": provenance, "models": {}}
    failed = []
    for name in [m.strip() for m in args.models.split(",") if m.strip()]:
        t0 = time.time()
        entry = {"file": FILES[name]}
        try:
            art = train_one(name, external)
            art["provenance"] = provenance
            (out / FILES[name]).write_text(json.dumps(art, indent=2), encoding="utf-8")
            entry["candidate"] = SUMMARY[name](art)
            log_metrics(name, entry["candidate"])
            current = Path(args.current) / FILES[name]
            if current.exists():
                entry["current"] = SUMMARY[name](json.loads(current.read_text(encoding="utf-8")))
            entry["status"] = "ok"
        except Exception as e:  # keep going: one failed model must not hide the others' results
            traceback.print_exc()
            entry.update(status="failed", error=f"{type(e).__name__}: {e}")
            failed.append(name)
        entry["seconds"] = round(time.time() - t0, 1)
        report["models"][name] = entry
        print(f"{name}: {entry['status']} in {entry['seconds']} s", flush=True)

    report["seconds"] = round(time.time() - started, 1)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: {kk: v.get(kk) for kk in ("status", "candidate", "current")} for k, v in report["models"].items()},
                     indent=2), flush=True)
    print(f"Candidates written to {out}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
