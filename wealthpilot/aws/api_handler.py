"""AWS Lambda entry point for the hosted website's API (the same FastAPI app as ``python -m wealthpilot.api``).

CloudFront serves the React build from S3 and sends ``/api/*`` to this function's URL. On a cold start the
function copies the data files from the S3 data bucket to /tmp (the only writable folder on Lambda), points the
loaders at them, then hands every request to FastAPI through Mangum.

Environment (set by infra/hosting.yaml): DATA_BUCKET, DATA_PREFIX, WEALTHPILOT_USERS_TABLE (accounts),
TRACE_TABLE (agent audit trail), WEALTHPILOT_LLM=bedrock, WEALTHPILOT_MODEL, WEALTHPILOT_FALLBACK_MODEL.
No credentials are stored anywhere: the function uses its IAM role.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("WEALTHPILOT_LOCAL_ROOT", "/tmp/wealthpilot"))
_state: dict = {}


def _prepare(s3=None) -> None:
    """Sync the data once per container and configure every writable path under /tmp (before importing the app)."""
    from .storage import configure_paths, sync_from_s3

    ROOT.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)  # relative caches (yfinance responses in data/cache) land in /tmp
    os.environ.setdefault("HOME", str(ROOT))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))
    os.environ["WEALTHPILOT_NEWS_DIR"] = str(ROOT / "news")
    os.environ.setdefault("WEALTHPILOT_WEB_DIST", str(ROOT / "no-web"))  # CloudFront serves the interface
    if s3 is None:
        import boto3
        s3 = boto3.client("s3")
    sync_from_s3(s3, os.environ["DATA_BUCKET"], os.environ.get("DATA_PREFIX", "wealthpilot"), ROOT)
    configure_paths(ROOT)


def _handler():
    if "handler" not in _state:
        _prepare()
        from mangum import Mangum

        from ..api import app  # imported after the paths are configured

        _state["handler"] = Mangum(app, lifespan="off")
    return _state["handler"]


def handler(event, context):
    return _handler()(event, context)
