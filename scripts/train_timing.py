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
    L += ["", "## The investor's question: invest now, spread over 6 months, or wait for the signal?", "",
          "Each month since the first out-of-sample year, $1 invested three ways and valued 12 months later "
          "(0.05% per purchase; cash waiting earns the policy rate; the signal uses out-of-sample probabilities only).", "",
          "| Asset | Start months | Now (avg value) | Spread (avg) | Signal (avg) | Spread beats now | Signal beats now | Median wait |",
          "|---|---|---|---|---|---|---|---|"]
    import numpy as np
    for t, a in art["assets"].items():
        e = a.get("entry")
        if not e:
            continue
        now, sp, sg = map(np.array, (e["now"], e["spread"], e["signal"]))
        L.append(f"| {t} | {len(now)} ({e['starts'][0][:7]} to {e['starts'][-1][:7]}) | {now.mean():.3f} | {sp.mean():.3f} | "
                 f"{sg.mean():.3f} | {pct((sp > now).mean())} | {pct((sg > now).mean())} | {int(np.median(e['waited_days']))} days |")
    L += ["", "## Provenance", "",
          "The model is the backtesting engine's (`src/ml`): same target (+2% within 5 days), same logistic regression, "
          "same features and same 5-day holding rule, reimplemented in `wealthpilot/timing.py` with fixed indicator "
          "settings. `tests/test_timing_parity.py` checks, when `BACKTESTING_ENGINE_PATH` points to the engine, that the "
          "indicator features equal the engine's own `generateFeatures` output. The engine's C++ metrics are ported to "
          "NumPy (`wealthpilot/metrics.py`) and cross-checked against the compiled module with `METRICS_CPP_PATH`.",
          "", "## Reading", "",
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
