"""Package the SageMaker training code (used by scripts/train_aws.sh). Python 3.9+ (AWS CloudShell).

Writes:
    build/training_source.tar.gz  entry.py + wealthpilot/ + the two price-fetch scripts + requirements.txt
                                  (the managed scikit-learn image installs requirements.txt, then runs entry.py)
    build/trainer/                the launcher Lambda's code (three small files; boto3 ships with Lambda)
"""

from __future__ import annotations

import io
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
# The image already has numpy, pandas, scikit-learn and SciPy: only add what the data refresh needs.
REQUIREMENTS = "yfinance>=0.2\n"


def _skip(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def source_tarball() -> Path:
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "training_source.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(ROOT / "training" / "entry.py", arcname="entry.py")
        for p in sorted((ROOT / "wealthpilot").rglob("*")):
            if p.is_file() and not _skip(p):
                tar.add(p, arcname=str(p.relative_to(ROOT)))
        for name in ("fetch_long_history.py", "fetch_timing_history.py"):
            tar.add(ROOT / "scripts" / name, arcname=f"scripts/{name}")
        data = REQUIREMENTS.encode()
        info = tarfile.TarInfo("requirements.txt")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return out


def launcher() -> Path:
    out = BUILD / "trainer"
    if out.exists():
        shutil.rmtree(out)
    for rel in ("wealthpilot/__init__.py", "wealthpilot/aws/__init__.py", "wealthpilot/aws/training.py"):
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, out / rel)
    return out


if __name__ == "__main__":
    print(f"Training code: {source_tarball()}")
    print(f"Launcher: {launcher()}")
