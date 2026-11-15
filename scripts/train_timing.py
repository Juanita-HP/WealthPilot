"""Run the market-timing check and write models/timing_model.json and models/model_card_timing.md.

Usage: python scripts/fetch_timing_history.py && python scripts/train_timing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import timing  # noqa: E402
from wealthpilot.agents.ledger import jsonable  # noqa: E402


def pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def main() -> None:
    art = jsonable(timing.train())
    timing.ARTIFACT.parent.mkdir(exist_ok=True)
    timing.ARTIFACT.write_text(json.dumps(art, indent=2))
    L = ["# Model card: market-timing check (ML entry signal vs holding)", "",
         f"Run on {art['trained_on']} by `scripts/train_timing.py`. {art['source']}.", "", art["method"], "",
         "## Results, honest protocol (one test per year, threshold chosen inside each training window)", "",
         "| Asset | Costs | Tests | Beats holding (Sharpe) | Beats holding (return) | Mean Sharpe gap | p-value | Compounded: model vs holding | Usable |",
         "|---|---|---|---|---|---|---|---|---|"]
    for t, a in art["assets"].items():
        for scen in ("zero", "main", "fx_cad_account"):
            if scen not in a["scenarios"]:
                continue
            s = a["scenarios"][scen]["summary"]
            L.append(f"| {t} | {art['costs'][scen]['per_side'] * 100:.2f}% per side | {s['tests']} ({s['years']}) | "
                     f"{s['wins_sharpe']}/{s['tests']} | {s['wins_return']}/{s['tests']} | {s['mean_sharpe_diff']:+.2f} | "
                     f"{s['p_value']:.2f} | {pct(s['strategy_compounded'])} vs {pct(s['hold_compounded'])} | "
                     f"{'yes' if s['usable'] else 'no'} |")
    L += ["", "## Original protocol (5 equal chunks, 4 validation folds), threshold chosen inside each training window", "",
          "| Asset | Costs | Beats holding on return | Beats holding on Sharpe |", "|---|---|---|---|"]
    for t, a in art["assets"].items():
        for k, label in (("zero_costs", "none"), ("main_costs", "0.05% per side")):
            o = a["original_protocol"][k]
            L.append(f"| {t} | {label} | {o['beats_on_return']}/4 | {o['beats_on_sharpe']}/4 |")
    L += ["", "## Reading", "",
          "The model has some ranking skill (average AUC above 0.5), but turning it into in-and-out trades misses part of "
          "the market's best days: after realistic costs it does not beat simply holding often enough, or significantly. "
          "With the threshold picked after seeing the test folds, the original backtest found '3 out of 4' for some "
          "thresholds; picked honestly, the advantage disappears. The devil's advocate shows this as evidence that "
          "timing entries is hard, and would show the live signal only if an asset passed the gate."]
    (ROOT / "models" / "model_card_timing.md").write_text("\n".join(L) + "\n")
    print("\n".join(L[7:7 + 3 * len(art["assets"]) + 2]))
    print("\n".join(L[-(2 * len(art["assets"]) + 6):-4]))


if __name__ == "__main__":
    main()
