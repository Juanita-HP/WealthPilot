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

## rules-v2 (baseline update)
Added opinion cues ("take", "verdict", "thinks", "bets", "calls for", "flags", "warns", "about to", "ways to") after
"Jim Cramer has a strong take on Nvidia" was shown as a fact in the interface. Type accuracy 70% to 77%, predictive
recall 48% to 66% on golden_v0. These cues were chosen after reading the errors on the same set, so the gain is
optimistic; a second, unseen labeled set is needed to confirm it.

## macro-rules-v1 and macro v1 (official texts)
Full texts of official releases (Bank of Canada, Federal Reserve, Statistics Canada). The rule analyzer reads the
decision (policy rate, CPI, unemployment, GDP), the risk factors with exact quotes, and the share of forecast
sentences. It is checked against the official data series the same institutions publish (`scripts/eval_macro.py`,
`docs/macro_eval.md`): 11 of 11 checkable decisions read correctly on the first run (value and direction). The CPI
direction is acceleration versus the previous month, not the sign of the annual rate; the rules were written while
reading recent releases, so later releases are the real test. Prompt `macro_v1.md` gives Claude the same task; quotes
it returns are kept only if found verbatim in the text.

## rules-v3 (baseline update)
Added leadership cues to the management category ("reinstate", "ousted", "fired", "steps down", "departure",
"successor", "leadership") after the NVDA headlines about Jensen Huang's exit were filed under "other". On golden_v0:
category accuracy 34% to 36%, type accuracy unchanged (77%), importance error 1.02 to 1.05. Material categories feed
the devil's advocate's recent-news warning, so missing a leadership change mattered more than the small error change.

## rules-v4 (baseline update)
Broader ESG controversy cues (carbon, oil sands, fossil, pipeline, environmental, lawsuits and fines) so that investors
with ESG preferences see external evidence; the digest now lists up to three ESG or legal/regulatory headlines
(`controversies`). Golden_v0 scores unchanged (type 77%, category 36%). Also: Yahoo's search returns nothing for
suffixed symbols (RY.TO, BTC-USD), so those are now searched by name ("Royal Bank", "Bitcoin").
