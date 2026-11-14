"""Fetch long macro history (1995 onward) for the inflation model and real-terms calculations.

The starter dataset covers 2021-11 to 2026-11 only: 58 monthly CPI points, one
inflation regime. Training a forecaster on that would mostly learn 2022. This
script adds 30 years of public data from the same two official sources.

Output: data/external/macro_history.csv (long format, same columns as the
starter macro_rates.csv plus retrieved_on).

Usage: python scripts/fetch_macro_history.py
"""

from __future__ import annotations

import io
import json
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "data" / "external" / "macro_history.csv"
START = "1995-01-01"
TODAY = date.today().isoformat()

BOC = {  # series_id: (label, unit, frequency)
    "V41690973": ("Canada CPI, all items (index 2002=100, not seasonally adjusted)", "index", "monthly"),
    "STATIC_TOTALCPICHANGE": ("Canada total CPI, % change y/y (unadjusted)", "percent", "monthly"),
    "CPIW": ("Canada CPIW core inflation, % change y/y", "percent", "monthly"),
    "V39079": ("Bank of Canada target for the overnight rate", "percent", "daily"),
    "BD.CDN.2YR.DQ.YLD": ("Government of Canada benchmark bond yield, 2-year", "percent", "business daily"),
    "BD.CDN.10YR.DQ.YLD": ("Government of Canada benchmark bond yield, 10-year", "percent", "business daily"),
}
FRED = {
    "CPIAUCSL": ("U.S. CPI, all urban consumers (index 1982-84=100, SA)", "index", "monthly"),
    "UNRATE": ("U.S. unemployment rate (SA)", "percent", "monthly"),
    "DCOILWTICO": ("Crude oil price, West Texas Intermediate", "USD per barrel", "daily"),
    "DEXCAUS": ("Canadian dollars to one U.S. dollar (noon/close)", "CAD per USD", "daily"),
}


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def boc(series_id: str) -> pd.DataFrame:
    data = json.loads(get(f"https://www.bankofcanada.ca/valet/observations/{series_id}/json?start_date={START}"))
    rows = [(o["d"], o[series_id]["v"]) for o in data["observations"]
            if series_id in o and o[series_id].get("v") not in (None, "")]
    return pd.DataFrame(rows, columns=["date", "value"]).astype({"value": float})


def fred(series_id: str) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}")))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna()


def main() -> None:
    frames = []
    for sid, (label, unit, freq) in BOC.items():
        d = boc(sid)
        d["series_id"], d["label"], d["unit"], d["frequency"] = sid, label, unit, freq
        d["source"] = "Bank of Canada Valet API"
        frames.append(d)
    for sid, (label, unit, freq) in FRED.items():
        d = fred(sid)
        d["series_id"], d["label"], d["unit"], d["frequency"] = sid, label, unit, freq
        d["source"] = "FRED, Federal Reserve Bank of St. Louis"
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    out["retrieved_on"] = TODAY
    out = out[["date", "series_id", "value", "unit", "frequency", "label", "source", "retrieved_on"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.sort_values(["series_id", "date"]).to_csv(OUT, index=False)
    for sid, g in out.groupby("series_id"):
        print(f"{sid:22} {len(g):6}  {g['date'].min()} .. {g['date'].max()}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
