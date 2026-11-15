"""Build the hosted API's Lambda package in build/api (used by scripts/deploy_aws.sh).

Downloads Linux wheels for Python 3.13 (works from any OS or Python version: no Docker needed), copies the
wealthpilot package, and removes test folders and bytecode so the package stays under Lambda's 250 MB limit.

Usage: python3 scripts/build_lambda.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "api"
LIMIT_MB = 250


def size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-cache-dir",
                    "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.13",
                    "--only-binary=:all:", "--target", str(OUT), "-r", str(ROOT / "infra" / "requirements-api-lambda.txt")],
                   check=True)
    shutil.copytree(ROOT / "wealthpilot", OUT / "wealthpilot", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for d in sorted(OUT.rglob("*"), reverse=True):  # deepest first
        if d.is_dir() and d.name in {"tests", "__pycache__"} and d.parent != OUT / "wealthpilot":
            shutil.rmtree(d, ignore_errors=True)
    mb = size_mb(OUT)
    print(f"Lambda package: {OUT} ({mb:.0f} MB unzipped, limit {LIMIT_MB} MB)")
    if mb >= LIMIT_MB:
        sys.exit("The package is over Lambda's size limit.")


if __name__ == "__main__":
    main()
