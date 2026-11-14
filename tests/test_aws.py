import json
import shutil
from pathlib import Path

import pytest

from tests.conftest import requires_starter
from tests.test_profile import ROBERT
from wealthpilot.agents.llm import ScriptedLLM
from wealthpilot.aws import storage

ROOT = Path(__file__).resolve().parent.parent
LOCAL = {"starter": ROOT / "data" / "starter", "external": ROOT / "data" / "external", "models": ROOT / "models"}


class FakeS3:
    def __init__(self):
        self.downloads = []

    def download_file(self, bucket, key, target):
        rel = key.split("/", 1)[1]
        folder, name = rel.split("/", 1)
        shutil.copy(LOCAL[folder] / name, target)
        self.downloads.append(key)


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def put_item(self, Item):
        self.items[(Item["pk"], Item["sk"])] = Item


def _all_local_files_exist():
    return all((LOCAL[r.split("/")[0]] / r.split("/", 1)[1]).exists() for r in storage.DATA_FILES)


needs_files = pytest.mark.skipif(not _all_local_files_exist(), reason="data files or model artifact missing")


@needs_files
def test_sync_downloads_once(tmp_path):
    s3 = FakeS3()
    first = storage.sync_from_s3(s3, "bucket", "wealthpilot", tmp_path)
    second = storage.sync_from_s3(s3, "bucket", "wealthpilot", tmp_path)
    assert sorted(first) == sorted(storage.DATA_FILES) and second == []
    assert all(k.startswith("wealthpilot/") for k in s3.downloads)


def test_trace_store_round_trip():
    store = storage.TraceStore(FakeTable())
    store.save_state("s1", {"portfolio": {"XIU.TO": 0.5}})
    assert store.load_state("s1") == {"portfolio": {"XIU.TO": 0.5}}
    sk = store.save_turn("s1", "q", {"report": {"coverage": 1.0}}, [{"id": "R1"}])
    assert sk.startswith("TURN#")


@needs_files
@requires_starter
def test_lambda_turn_persists_state_and_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("WEALTHPILOT_LOCAL_ROOT", str(tmp_path))
    monkeypatch.setenv("DATA_BUCKET", "bucket")
    from wealthpilot.aws import lambda_handler as lh
    monkeypatch.setattr(lh, "ROOT", tmp_path)
    lh._cache.clear()
    table = FakeTable()
    answers = [{"question": k, "answer": v} for k, v in ROBERT.items()]
    llm = ScriptedLLM([
        [("build_profile", {"answers": answers, "esg": "none", "excluded_sectors": [], "crypto": "no",
                            "region": "balanced", "themes": [], "amount": 150000, "simplicity": False, "values": []})],
        [("propose_allocation", {})],
        "Your allocation is ready {R?} {R?}.",
        "No major objection.",
        "Debate: nothing to resolve.",
    ])
    out = lh.handle({"session_id": "demo", "question": "Build my plan"}, FakeS3(), table, llm=llm)
    assert out["session_id"] == "demo" and len(out["receipts"]) == 2
    state = json.loads(table.items[("demo", "STATE")]["state"])
    assert state["profile"]["answers"]["horizon"] == "3to5" and state["portfolio"]
    turns = [k for k in table.items if k[1].startswith("TURN#")]
    assert len(turns) == 1

    # second turn: the profile and portfolio come back from DynamoDB, no rebuild needed
    llm2 = ScriptedLLM([[("review_allocation", {"weights": []})], "Reviewed {R?}.", "Nothing to add.",
                        "Debate: nothing to resolve."])
    out2 = lh.handle({"session_id": "demo", "question": "Any risk in my plan?"}, FakeS3(), table, llm=llm2)
    assert out2["receipts"][0]["tool"] == "review_allocation" and out2["receipts"][0]["error"] is None
