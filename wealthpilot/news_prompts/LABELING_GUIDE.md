# Headline labeling guide (shared by human labelers and prompts)

The golden dataset (`data/news/golden_v0.jsonl`) and every prompt version follow these rules. Change the guide first, then the labels or the prompt, and record the change in `CHANGELOG.md`.

## type

- **descriptive**: reports something that happened or is scheduled (results, a filing, a launch, a price move, an appointment, a lawsuit, a vote calendar). A retrospective question ("Could you have held X through its falls?") is descriptive.
- **predictive**: the headline's main content is about the FUTURE or is an OPINION: a forecast, a target, a recommendation, advice ("6 ways to protect"), a "should you buy", a "better buy", a "take", "about to", risks someone "flags", or what something "could" do. This holds even when the forecast is attributed to someone ("X calls for", "X hopes the IPO will").

## category

`earnings` (results, guidance, dividends), `product`, `legal_regulatory`, `deal` (M&A, IPO, stake), `management` (executives, board, insider trades), `macro` (rates, inflation, elections, debt), `analyst_rating` (ratings, targets, pundit takes, stock picks), `market_move` (prices, flows), `esg_controversy`, `other`.

## sentiment

From -1 (clearly bad for the asset) to +1 (clearly good). 0 when neutral or unclear. Judge the asset's perspective, not the market's.

## importance (1 to 5)

5 = could change the investment case (major merger, fraud, guidance cut); 4 = material (earnings, regulatory action, key macro data); 3 = notable; 2 = minor; 1 = noise or not about the asset.

## relevant

True only if the headline is about the asset itself (or, for broad funds, about what the fund holds or tracks). Search results often include loosely related stories; those are not relevant.
