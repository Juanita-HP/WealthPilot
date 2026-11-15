"""Train and evaluate the return forecast for crypto and gold; write the artifact and the model card.

Output: models/asset_forecast.json (metrics, forecast, feature importance; no raw prices) and
models/model_card_asset_forecast.md.

Usage: python scripts/fetch_long_history.py && python scripts/train_asset_forecast.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import forecast  # noqa: E402


def pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def main() -> None:
    art = forecast.train()
    forecast.ARTIFACT.parent.mkdir(exist_ok=True)
    forecast.ARTIFACT.write_text(json.dumps(art, indent=2))
    lines = ["# Model card: 3-month return forecast for crypto and gold", "",
             f"Trained on {art['trained_on']} by `scripts/train_asset_forecast.py`.", "", art["method"], "",
             "## Results (walk-forward, out of sample)", "",
             "| Asset | Tested | Model | R² vs average | Rating | Direction right | DM p-value |",
             "|---|---|---|---|---|---|---|"]
    for t, a in art["assets"].items():
        for k, label in (("gradient_boosting", "Gradient boosting"), ("ridge", "Ridge"), ("last_3m", "Last 3 months repeat")):
            m = a["models"][k]
            lines.append(f"| {a['name']} | {a['tested']} ({a['n_predictions']} months) | {label} | {pct(m['r2_oos'])} | "
                         f"{m['rating']['label']} | {pct(m['hit_rate'], 0)} | {m['dm_p']:.2f} |")
        lines.append(f"| {a['name']} | | Historical average (benchmark) | 0.0% | | {pct(a['baselines']['hit_rate_mean'], 0)} | |")
    lines += ["", "## Use in the interface", "",
              "The gauge uses the gradient-boosting forecast only when its rating is good or very good and the "
              "Diebold-Mariano test against the historical average is significant at 10%. Otherwise the gauge says "
              "\"Not scored\" and the investor sees the R², its rating and the forecast with its range, to judge.", "",
              "## Limits", "",
              "- Few independent observations (3-month targets, 10 to 20 years of history): results move with the period.",
              "- Overlapping monthly targets: the test uses a Newey-West variance; hit rates are still optimistic.",
              "- Prices in U.S. dollars (listing currency); the investor's CAD return also moves with the exchange rate.",
              "- Two models compared on the same test period: a small selection effect remains."]
    path = ROOT / "models" / "model_card_asset_forecast.md"
    path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines[6:6 + 4 * len(art["assets"]) + 2]))


if __name__ == "__main__":
    main()
