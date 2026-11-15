"""Upload the data files and the inflation model to the S3 bucket created by infra/template.yaml.

Usage: python scripts/upload_data.py <bucket> [prefix]
"""

from __future__ import annotations

import sys
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot.aws.storage import DATA_FILES, OPTIONAL_FILES  # noqa: E402

LOCAL = {"starter": ROOT / "data" / "starter", "external": ROOT / "data" / "external", "models": ROOT / "models"}


def main() -> None:
    bucket = sys.argv[1]
    prefix = sys.argv[2] if len(sys.argv) > 2 else "wealthpilot"
    s3 = boto3.client("s3")
    for rel in sorted(DATA_FILES | OPTIONAL_FILES):
        folder, name = rel.split("/", 1)
        path = LOCAL[folder] / name
        if rel in OPTIONAL_FILES and not path.exists():
            print(f"skipped {rel} (optional, not present)")
            continue
        s3.upload_file(str(path), bucket, f"{prefix}/{rel}")
        print(f"uploaded s3://{bucket}/{prefix}/{rel}")


if __name__ == "__main__":
    main()
