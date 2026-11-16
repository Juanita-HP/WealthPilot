# WealthPilot

*Explainable AI for investment decision support. Understand the decision, challenge the assumptions, verify the numbers.*

PDF: [WealthPilot_One_Pager.pdf](WealthPilot_One_Pager.pdf)

## The problem

Investors are not short of data. They struggle to judge whether an investment fits their goals, horizon, finances and tolerance for loss, and most tools give an answer without the reasons, the assumptions or the limits.

## Our solution

An educational simulation that builds a fictitious allocation for each of the investor's goals, explains every figure, challenges risky ideas with evidence, and says when it does not know.

## How it works

1. **Profile**: Rules, not a black box: the lower of risk capacity and risk tolerance sets one of 5 levels; each goal's horizon can lower it.
2. **Plan**: One portfolio per goal, built by stated rules; six-risk map; time machine replays 5 years and compares the plan with inflation.
3. **Devil's advocate**: Deterministic rules challenge an idea: concentration, risk jump, horizon, recency, hype, liquidity, values. Always with the counterpoint.
4. **Agents**: On Amazon Bedrock™: an Advisor drafts, a Devil's advocate challenges, a Verifier written in code checks every number against its receipt (R1, R2, ...).

## It adapts to the investor

- **Robert, 59, retires in 4 years**: wants 25% in Tesla: "Reconsider". 25% against a 7.5% single-stock limit, 86% of the portfolio's risk, worst fall from 8.9% to 25.0%, and Tesla took 2.9 years to recover from a 71% fall.
- **Amira, 26, growth**: 15% in bitcoin goes above her crypto limit; her plan keeps a small, capped bitcoin share inside a diversified portfolio.
- **Mateo, 41, balanced, ESG**: 10% in Exxon goes against his values: his plan uses an ESG-screened U.S. fund and excludes the sectors he chose.

## Data, with its limits

Yahoo Finance prices for 33 assets (stocks, ETFs, gold, crypto), converted to CAD with Bank of Canada rates; Bank of Canada, Statistics Canada and FRED series used only after their publication date; official news (Bank of Canada, Federal Reserve, Statistics Canada) read within robots.txt; headlines labelled fact or opinion. Limits: five years of starter prices, survivorship bias, incomplete ESG coverage, model uncertainty.

## What is original

- No model approves its own answer: the verifier is code.
- It refuses to guess: "Not scored", assets without enough data are not offered for review.
- It contradicts the investor when the data says so, and agrees when the data supports them.
- Facts, planning assumptions (FP Canada/IFP 2026) and scenarios are labelled separately.

## Validated, and reported honestly

- Inflation: a simple mean-reversion rule beat our ridge model out of sample (12-month error 1.04 vs 1.43 points). The app uses the rule and says so.
- Crypto and gold: gradient boosting does worse than the historical average out of sample (R² −34% bitcoin, −3% ether, −7% gold), so the gauge shows "Not scored".
- Market timing: after realistic costs, the ML signal beats holding in only 5 to 7 of 17 test years, never significantly. It is shown as evidence that timing is hard.
- 243 automated tests; agent answers are checked against receipts before they are shown.

## On AWS

Amazon CloudFront™, Amazon S3™, AWS Lambda™, Amazon Bedrock™, Amazon DynamoDB™, Amazon SageMaker AI™, Amazon EventBridge Scheduler™, Amazon CloudWatch™ and AWS IAM™, in us-east-1. Details: AWS architecture one-pager.

## User value

Understand why an option fits or not, see the trade-offs in dollars, test an idea before acting, and learn the reasoning, with no real money at stake.

*Educational simulation: fictitious allocations, no real trades, not personalized financial advice.*

<sub>Amazon Web Services, AWS, Amazon CloudFront, Amazon S3, AWS Lambda, Amazon Bedrock, Amazon DynamoDB, Amazon SageMaker AI, Amazon EventBridge, Amazon CloudWatch, AWS Identity and Access Management, AWS CloudFormation, AWS CloudShell and Amazon Nova are trademarks of Amazon.com, Inc. or its affiliates. Claude is a trademark of Anthropic, PBC. Names are used to identify services; no endorsement is implied.</sub>
