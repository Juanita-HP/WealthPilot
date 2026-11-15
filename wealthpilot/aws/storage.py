"""AWS storage: data in S3, session state and execution traces in DynamoDB.

* S3 holds the data files (starter CSVs, macro history, inflation model). The
  Lambda copies them to /tmp on a cold start, so the code reads the same files
  locally and in the cloud.
* DynamoDB holds, per session: the investor's state (answers, preferences,
  portfolio) and every turn with its receipts and verification report. This is
  the audit trail: any number shown to a user can be traced to the tool call
  that produced it.

boto3 clients are injected, so tests run with fakes and no AWS account.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DATA_FILES = {
    "starter/assets_universe.csv", "starter/prices_daily.csv", "starter/corporate_actions.csv",
    "starter/fx_usdcad_daily.csv", "starter/macro_rates.csv", "external/macro_history.csv",
    "models/inflation_model.json",
}
# International funds (scripts/fetch_international.py): synced when present, optional.
OPTIONAL_FILES = {"external/assets_universe_extra.csv", "external/extra_prices.csv"}


def sync_from_s3(s3, bucket: str, prefix: str, dest: Path) -> list[str]:
    """Download the data files once per container. Returns the keys fetched."""
    fetched = []
    for rel in sorted(DATA_FILES):
        target = dest / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, f"{prefix.rstrip('/')}/{rel}", str(target))
        fetched.append(rel)
    for rel in sorted(OPTIONAL_FILES):
        target = dest / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            s3.download_file(bucket, f"{prefix.rstrip('/')}/{rel}", str(target))
            fetched.append(rel)
        except Exception:  # not uploaded: the plan falls back to Canada and the U.S. only, and says so
            target.unlink(missing_ok=True)
    return fetched


def configure_paths(root: Path) -> None:
    """Point the data and model loaders at a synced directory (before importing them)."""
    os.environ["WEALTHPILOT_DATA_DIR"] = str(root / "starter")
    os.environ["WEALTHPILOT_MODEL_PATH"] = str(root / "models" / "inflation_model.json")
    os.environ.setdefault("WEALTHPILOT_NEWS_DIR", str(root / "news"))  # writable cache for headlines and official texts


class TraceStore:
    """DynamoDB table with partition key ``pk`` (session) and sort key ``sk``.

    Items: ``STATE`` (latest investor state) and ``TURN#<epoch ms>`` (one per question).
    Payloads are stored as JSON strings to keep floats exact and avoid Decimal conversion.
    """

    def __init__(self, table):
        self.table = table

    def load_state(self, session_id: str) -> dict:
        item = self.table.get_item(Key={"pk": session_id, "sk": "STATE"}).get("Item")
        return json.loads(item["state"]) if item else {}

    def save_state(self, session_id: str, state: dict) -> None:
        self.table.put_item(Item={"pk": session_id, "sk": "STATE", "state": json.dumps(state)})

    def save_turn(self, session_id: str, question: str, answer: dict, receipts: list[dict]) -> str:
        sk = f"TURN#{int(time.time() * 1000)}"
        self.table.put_item(Item={
            "pk": session_id, "sk": sk, "question": question,
            "answer": json.dumps(answer), "receipts": json.dumps(receipts),
            "coverage": str(answer.get("report", {}).get("coverage")),
        })
        return sk
