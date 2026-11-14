"""Evidence ledger: every tool call becomes a numbered receipt.

Agents must cite a receipt id (``[R3]``) after every number they state. The
verifier then checks each cited number against the receipt's recorded output.
The ledger is the observable execution trace the brief asks for.
"""

from __future__ import annotations

import dataclasses
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd


def jsonable(x):
    """Convert results (dataclasses, numpy, pandas, timestamps) into plain JSON types."""
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return jsonable(x.to_dict() if hasattr(x, "to_dict") else dataclasses.asdict(x))
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [jsonable(v) for v in x]
    if isinstance(x, datetime):  # includes pd.Timestamp
        midnight = x.hour == x.minute == x.second == 0 and x.microsecond == 0
        return x.date().isoformat() if midnight else x.isoformat()
    if isinstance(x, date):
        return x.isoformat()
    if isinstance(x, pd.DataFrame):
        return jsonable(x.reset_index().to_dict(orient="records"))
    if isinstance(x, pd.Series):
        return jsonable(x.to_dict())
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    return str(x)


@dataclass
class Receipt:
    id: str
    tool: str
    agent: str
    inputs: dict
    output: dict
    created_at: str
    error: str | None = None

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class Ledger:
    session_id: str
    receipts: list[Receipt] = field(default_factory=list)

    def record(self, tool: str, agent: str, inputs: dict, output=None, error: str | None = None) -> Receipt:
        r = Receipt(f"R{len(self.receipts) + 1}", tool, agent, jsonable(inputs), jsonable(output) if output is not None else {},
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), error)
        self.receipts.append(r)
        return r

    def get(self, rid: str) -> Receipt | None:
        return next((r for r in self.receipts if r.id == rid), None)

    def to_json(self) -> str:
        return json.dumps({"session_id": self.session_id, "receipts": [r.to_dict() for r in self.receipts]}, indent=1)


def numbers_in(obj) -> list[float]:
    """Every numeric value inside a receipt output, including numbers inside strings."""
    import re
    out: list[float] = []

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, str):
            for tok in re.findall(r"-?\d[\d,]*\.?\d*", v):
                try:
                    out.append(float(tok.replace(",", "")))
                except ValueError:
                    pass
        elif isinstance(v, dict):
            for w in v.values():
                walk(w)
        elif isinstance(v, list):
            for w in v:
                walk(w)

    walk(obj)
    return out
