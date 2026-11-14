"""Score the headline classifiers on the golden dataset and record the results.

Usage:
    python scripts/eval_news.py                      # rule baseline only (offline)
    WEALTHPILOT_LLM=bedrock python scripts/eval_news.py v1 v2   # plus prompt versions on Claude

Writes models/news_eval.json (all runs, appended) and docs/news_eval.md (latest table).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wealthpilot import news  # noqa: E402

OUT = ROOT / "models" / "news_eval.json"
DOC = ROOT / "docs" / "news_eval.md"
METRICS = ["type_accuracy", "predictive_precision", "predictive_recall", "category_accuracy",
           "sentiment_sign_accuracy", "importance_mae", "relevance_accuracy", "n"]


def main(versions: list[str]) -> None:
    golden = news.load_jsonl(news.NEWS_DIR / "golden_v0.jsonl")
    runs = [news.evaluate(news.RuleClassifier(), golden)]
    if versions:
        from wealthpilot.agents.llm import from_env
        llm = from_env()
        for v in versions:
            clf = news.LLMClassifier(llm, v)
            runs.append(news.evaluate(clf, golden, exclude_text=clf.system))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    history = json.loads(OUT.read_text()) if OUT.exists() else []
    history += [{"at": stamp, **{k: r[k] for k in ["classifier"] + METRICS}} for r in runs]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(history, indent=1))
    def fmt(key, x):
        if x is None:
            return "n/a"
        if key in {"n"}:
            return str(x)
        return f"{x:.2f}" if key == "importance_mae" else f"{x:.0%}"
    lines = [f"# Headline classifier evaluation ({stamp})", "",
             f"Golden dataset: `data/news/golden_v0.jsonl` ({len(golden)} headlines, draft labels to be reviewed).", "",
             "| Classifier | " + " | ".join(METRICS) + " |", "|---|" + "---|" * len(METRICS)]
    for r in runs:
        lines.append(f"| {r['classifier']} | " + " | ".join(fmt(k, r[k]) for k in METRICS) + " |")
    DOC.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
