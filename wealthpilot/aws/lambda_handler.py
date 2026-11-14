"""AWS Lambda entry point.

The UI (Streamlit or web) invokes this function with IAM credentials (no public
endpoint). Event:

    {"session_id": "abc", "question": "...",
     "profile": {"answers": {...}, "preferences": {...}, "amount": 150000},   # optional
     "portfolio": {"XIU.TO": 0.5, "XBB.TO": 0.5}}                             # optional

Response: the agent answer (text, draft, critique, verification report, trace)
plus the receipts of this turn. State and the full trace are written to DynamoDB.

Environment: DATA_BUCKET, DATA_PREFIX, TRACE_TABLE, AWS_REGION, WEALTHPILOT_LLM
(bedrock by default), WEALTHPILOT_MODEL (default anthropic.claude-opus-5-5).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from .storage import TraceStore, configure_paths, sync_from_s3

ROOT = Path(os.environ.get("WEALTHPILOT_LOCAL_ROOT", "/tmp/wealthpilot"))
_cache: dict = {}


def _clients():
    if "s3" not in _cache:
        import boto3
        _cache["s3"] = boto3.client("s3")
        _cache["table"] = boto3.resource("dynamodb").Table(os.environ["TRACE_TABLE"])
    return _cache["s3"], _cache["table"]


def _prepare(s3) -> None:
    if not _cache.get("synced"):
        sync_from_s3(s3, os.environ["DATA_BUCKET"], os.environ.get("DATA_PREFIX", "wealthpilot"), ROOT)
        configure_paths(ROOT)
        _cache["synced"] = True


def handle(event: dict, s3, table, llm=None) -> dict:
    _prepare(s3)
    from ..agents import Session, ask  # imported after paths are configured
    from ..agents.llm import from_env
    from ..profile import Preferences, build_profile

    store = TraceStore(table)
    session_id = event.get("session_id") or uuid.uuid4().hex[:12]
    state = store.load_state(session_id)
    if event.get("profile"):
        state["profile"] = event["profile"]
    if event.get("portfolio"):
        state["portfolio"] = event["portfolio"]

    session = Session.from_starter()
    if state.get("profile"):
        p = state["profile"]
        prefs = p.get("preferences", {})
        session.profile = build_profile(p["answers"], Preferences(
            esg=prefs.get("esg", "none"), excluded_sectors=tuple(prefs.get("excluded_sectors", ())),
            crypto=prefs.get("crypto", "no"), region=prefs.get("region", "balanced"),
            themes=tuple(prefs.get("themes", ()))))
        session.amount = float(p.get("amount", session.amount))
    if state.get("portfolio"):
        session.portfolio = {k: float(v) for k, v in state["portfolio"].items()}

    answer = ask(session, event["question"], llm or from_env())

    # A profile or allocation built during the turn becomes part of the session state.
    if session.profile is not None and "profile" not in state:
        state["profile"] = {"answers": session.profile.answers, "amount": session.amount,
                            "preferences": {"esg": session.profile.preferences.esg,
                                            "excluded_sectors": list(session.profile.preferences.excluded_sectors),
                                            "crypto": session.profile.preferences.crypto,
                                            "region": session.profile.preferences.region,
                                            "themes": list(session.profile.preferences.themes)}}
    if session.portfolio:
        state["portfolio"] = session.portfolio
    store.save_state(session_id, state)
    receipts = [r.to_dict() for r in session.ledger.receipts]
    turn = store.save_turn(session_id, event["question"], answer.to_dict(), receipts)
    return {"session_id": session_id, "turn": turn, "answer": answer.to_dict(), "receipts": receipts}


def lambda_handler(event, context):
    if "body" in event:  # tolerate an HTTP-style event
        event = json.loads(event["body"] or "{}")
    if not event.get("question"):
        return {"error": "question is required"}
    s3, table = _clients()
    return handle(event, s3, table)
