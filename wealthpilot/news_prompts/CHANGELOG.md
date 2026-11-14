# Prompt versions for the headline classifier

Each version is scored on the same golden dataset with `scripts/eval_news.py`; results go to `models/news_eval.json` and `docs/news_eval.md`. A version is only promoted if it beats the previous one on type accuracy and predictive precision.

## rules-v1 (baseline, no LLM)
Keyword cues. Runs offline; sets the bar every prompt must beat.

## v1
Minimal instructions and the label schema. Written first, on purpose short, to measure what the model does without guidance.

## v2
Changes motivated by the baseline's errors on the golden set (opinion and advice headlines labeled descriptive; loosely related search results counted as news about the asset):
- full definitions from `LABELING_GUIDE.md`, including attributed forecasts, advice, "about to", scheduled events, retrospective questions
- explicit relevance rule and importance 1 for unrelated stories
- why precision on "predictive" matters (it feeds the hype warning)
- four worked examples taken from the 2026-11-14 collection; `evaluate` leaves headlines quoted in the prompt out of the score
