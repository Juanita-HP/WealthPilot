"""Source of the two architecture one-pagers (solution and AWS): diagrams, text, and the files built from them.

    python docs/architecture/onepagers.py          # writes the Markdown pages and the HTML pages
    node docs/architecture/render.js <mermaid.min.js>   # validates, renders the PDFs and the diagram images

Mermaid 11.4.1: ``npm pack mermaid@11.4.1 && tar xzf mermaid-11.4.1.tgz`` gives package/dist/mermaid.min.js.
render.js needs Playwright with Chromium. It fails if a diagram does not parse, if any label is cut or outside its
box (light and dark themes, and inside the one-pager), or if a one-pager is longer than one page.

Diagrams are Mermaid flowcharts: boxes are parts of the system, frames group them by layer (or the AWS Region),
solid arrows carry requests or data, dashed arrows are calls to tools, models or logs. Every element names a real
part of the code or of the AWS templates (see the "Grounded in" lines).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# Fixed colours: readable on GitHub's light and dark themes alike.
INIT = ('%%{init: {"theme": "base", "htmlLabels": false, "themeVariables": {'
        '"fontFamily": "Inter, Helvetica, Arial, sans-serif", "fontSize": "14px", '
        '"primaryColor": "#fdf8ee", "primaryBorderColor": "#b8935a", "primaryTextColor": "#172025", '
        '"lineColor": "#8a8f91", "textColor": "#172025", "edgeLabelBackground": "#ffffff", '
        '"clusterBkg": "transparent", "clusterBorder": "#b8935a", "titleColor": "#8a6d3b"}}}%%')

SOLUTION_DIAGRAM = INIT + '''
flowchart LR
    USER(["Investor"])
    subgraph UI["Interface"]
        WEB["Web interface<br/>React 18 + Vite"]
    end
    API["API service<br/>FastAPI<br/>signed sessions, validation"]
    subgraph AG["Agent layer"]
        ORCH["Orchestrator<br/>fixed order, one revision"]
        ADV["Advisor<br/>LLM + tool calls"]
        DEV["Devil's advocate<br/>LLM + review tools"]
        VER["Verifier<br/>deterministic code"]
        LED["Receipt ledger<br/>R1, R2, ..."]
    end
    subgraph ENG["Decision engine (Python)"]
        PROF["Profile, goals, allocation<br/>risk map, time machine"]
        RULES["Advocate rules, liquidity<br/>news: facts vs opinions"]
        MOD["Forecast models<br/>walk-forward tested"]
    end
    subgraph ST["Storage"]
        DATA[("Market and macro data<br/>prices in CAD")]
        ACC[("Accounts and<br/>audit trail")]
    end
    SRC["Public sources<br/>Yahoo Finance<br/>Bank of Canada, StatCan<br/>FRED, official feeds"]
    LLM["Amazon Bedrock™<br/>Claude Haiku 4.5"]

    USER --> WEB
    WEB -->|"REST JSON"| API
    API -->|"plan, scores, reviews"| PROF
    API -->|"questions"| ORCH
    API --> ACC
    ORCH -->|"1 draft"| ADV
    ORCH -->|"2 challenge"| DEV
    ORCH -->|"3 check"| VER
    ADV -.->|"tool calls"| PROF
    DEV -.->|"review tools"| RULES
    ADV -.->|"prompts"| LLM
    DEV -.->|"prompts"| LLM
    PROF -->|"receipts"| LED
    PROF --> MOD
    VER -.->|"compares"| LED
    MOD --> DATA
    SRC -->|"ingested"| DATA

    classDef ext fill:#ffffff,stroke:#8a8f91,stroke-dasharray:4 3,color:#172025
    class SRC,LLM,USER ext
'''

AWS_DIAGRAM = INIT + '''
flowchart TB
    USER(["Investor browser"])
    subgraph REG["AWS Cloud · Region us-east-1"]
        CF["Amazon CloudFront™<br/>HTTPS distribution"]
        S3W["Amazon S3™<br/>private website bucket<br/>React build"]
        API["AWS Lambda™<br/>API function: FastAPI,<br/>tools, agents, verifier"]
        BR["Amazon Bedrock™<br/>Claude Haiku 4.5<br/>Amazon Nova 2 Lite fallback"]
        DDBU[("Amazon DynamoDB™<br/>users table")]
        DDBT[("Amazon DynamoDB™<br/>traces table")]
        S3D[("Amazon S3™<br/>data bucket: data,<br/>models, training")]
        CW["Amazon CloudWatch™<br/>logs"]
        subgraph TRAIN["Monthly model training"]
            EB["Amazon EventBridge<br/>Scheduler™"]
            LL["AWS Lambda™<br/>training launcher"]
            SM["Amazon SageMaker AI™<br/>training job"]
        end
        IAM["AWS IAM™<br/>least-privilege roles"]
    end
    OPS["AWS CloudShell™ and<br/>AWS CloudFormation™<br/>deploy, no access keys"]

    USER --> CF
    CF -->|"pages"| S3W
    CF -->|"/api/*"| API
    API -->|"Converse API"| BR
    API <-->|"accounts"| DDBU
    API -->|"receipts"| DDBT
    API -->|"data, models"| S3D
    API -.->|"logs"| CW
    EB -->|"1st of month"| LL
    LL -->|"starts"| SM
    SM -->|"candidates"| S3D
    IAM -.->|"roles"| API
    OPS -.->|"stacks"| CF

    classDef ext fill:#ffffff,stroke:#8a8f91,stroke-dasharray:4 3,color:#172025
    class USER,OPS ext
'''

DISCLAIMER = "Educational simulation: fictitious allocations, no real trades, not personalized financial advice."

# ----------------------------------------------------------------------------- solution page text

SOLUTION = {
    "title": "WealthPilot · Solution architecture",
    "subtitle": "Explainable, agentic investment simulation: how the parts fit together.",
    "cards": [
        ("Layers", [
            "<b>Web interface</b> (React 18 + Vite): profile, plan, time machine, stocks, devil's advocate.",
            "<b>API service</b> (FastAPI): signed sessions, validated inputs, one endpoint per screen.",
            "<b>Decision engine</b> (deterministic Python): profile = lower of risk capacity and tolerance "
            "(5 levels); each goal capped by its horizon; rule-based allocation; six-risk map; time machine and "
            "shocks; devil's advocate rules; data-coverage and liquidity rules; news facts vs opinions.",
            "<b>Forecast models</b>: inflation (ridge vs simple rules), crypto and gold (gradient boosting vs "
            "the historical mean), market timing (logistic regression). Shown only as far as their walk-forward "
            "tests, fixed in advance, allow.",
        ]),
        ("Why each agent exists", [
            "<b>Advisor</b> (LLM): turns tool results into an answer at the investor's level. It does not "
            "compute: every figure comes from a tool.",
            "<b>Devil's advocate</b> (LLM): challenges the request and the draft (concentration, horizon, "
            "recency, hype) and states the counterpoint when the data supports the investor.",
            "<b>Verifier</b> (code, not an LLM): checks every number against its receipt; blocks trade "
            "directives, guaranteed returns and certainty. No model approves its own answer.",
            "<b>Orchestrator</b>: fixed order, at most one revision; remaining problems are shown, not hidden.",
        ]),
        ("One question, end to end", [
            "1. The interface sends the question with the signed session.",
            "2. The API loads the investor's profile and simulated plan.",
            "3. The Advisor calls tools; each result is a numbered receipt (R1, R2, ...).",
            "4. The Devil's advocate reviews the draft with its own tools.",
            "5. The Verifier compares every figure with its receipt.",
            "6. Answer, receipts and verification are shown, and stored as an audit trail.",
        ]),
        ("Data, explainability, limits", [
            "<b>Data</b>: Yahoo Finance prices converted to CAD with Bank of Canada rates; Bank of Canada, "
            "Statistics Canada and FRED series with publication lags; official news read within robots.txt.",
            "<b>Explainability</b>: facts, planning assumptions (FP Canada/IFP 2026) and scenarios are labelled; "
            "a model that fails its test shows \"Not scored\"; assets without enough data are not reviewed.",
            "<b>Limits</b>: five years of starter prices, survivorship bias, incomplete ESG coverage, model "
            "uncertainty.",
        ]),
    ],
    "grounded": "Grounded in: web/src, wealthpilot/api.py, wealthpilot/agents/ (orchestrator, tools, verifier, "
                "ledger), profile.py, goals.py, strategist.py, risks.py, time_machine.py, advocate.py, "
                "coverage.py, news.py, macro_news.py, inflation.py, forecast.py, timing.py, data.py, accounts.py.",
}

# ----------------------------------------------------------------------------- AWS page text

TM = "™"
AWS_SERVICES = [
    (f"Amazon CloudFront{TM}", "HTTPS entry point: serves the interface, routes /api/* to AWS Lambda",
     "One address for site and API, no CORS"),
    (f"Amazon Simple Storage Service (Amazon S3{TM})", "Private website bucket; data bucket with market and macro "
     "data, published models, training outputs", "Private and versioned; read through origin access control"),
    (f"AWS Lambda{TM}", "API function (FastAPI via Mangum, Python 3.13, function URL); training launcher",
     "Pays per request, scales to zero"),
    (f"Amazon Bedrock{TM}", "Advisor and Devil's advocate through the Converse API: Anthropic Claude Haiku 4.5, "
     "Amazon Nova 2 Lite as fallback", "Managed models inside the AWS boundary, no model API keys"),
    (f"Amazon DynamoDB{TM}", "Users table (accounts, profiles, token key); traces table (agent turns, receipts, "
     "verification)", "Persists across Lambda containers; audit trail"),
    (f"Amazon SageMaker AI{TM}", "Monthly training jobs (scikit-learn container, ml.m5.large) writing candidate "
     "models", "Each model traceable to its commit, data hash and metrics"),
    (f"Amazon EventBridge Scheduler{TM}", "Starts the training launcher on the 1st of each month",
     "Serverless schedule"),
    (f"Amazon CloudWatch{TM}", "Logs of the Lambda functions and training jobs", "Operations and debugging"),
    (f"AWS Identity and Access Management (IAM){TM}", "One role per function and for SageMaker, least privilege",
     "No access keys anywhere"),
    (f"AWS CloudFormation{TM} with AWS SAM, AWS CloudShell{TM}", "Stacks wealthpilot-web and wealthpilot-training, "
     "deployed from CloudShell", "Reproducible; credentials never leave AWS"),
]
AWS = {
    "title": "WealthPilot on AWS",
    "subtitle": "Region us-east-1 (US East, N. Virginia). The services behind the live demo.",
    "notes": [
        ("Security", "CloudFront reads the private site bucket through origin access control. The function URL is "
                     "public behind CloudFront, but every personal endpoint needs a signed session; passwords are "
                     "stored as salted PBKDF2 hashes. No access key is stored in code or configuration."),
        ("Model governance", "SageMaker writes candidates only. scripts/promote_models.sh shows live vs candidate "
                             "results and publishes after a human yes. No always-on endpoint: the API reads the "
                             "published model files."),
        ("Cost", "Pay per request (CloudFront, Lambda, DynamoDB on demand, Bedrock tokens). A training job costs "
                 "about 1 to 2 US cents. Idle cost is close to zero."),
    ],
    "grounded": "Grounded in: infra/hosting.yaml, infra/training.yaml, wealthpilot/aws/ (api_handler, storage, "
                "training), wealthpilot/agents/llm.py, scripts/deploy_aws.sh, train_aws.sh, promote_models.sh.",
    "trademark": "Amazon Web Services, AWS, Amazon CloudFront, Amazon S3, AWS Lambda, Amazon Bedrock, Amazon "
                 "DynamoDB, Amazon SageMaker AI, Amazon EventBridge, Amazon CloudWatch, AWS Identity and Access "
                 "Management, AWS CloudFormation, AWS CloudShell and Amazon Nova are trademarks of Amazon.com, Inc. "
                 "or its affiliates. Claude is a trademark of Anthropic, PBC. Names are used to identify services; "
                 "no endorsement is implied.",
}

# ----------------------------------------------------------------------------- Markdown (GitHub)


def _md_text(s: str) -> str:
    return s.replace("<b>", "**").replace("</b>", "**")


def solution_md() -> str:
    out = [f"# {SOLUTION['title']}", "", f"*{SOLUTION['subtitle']}* {DISCLAIMER}",
           "", "PDF one-pager: [WealthPilot_Solution_Architecture.pdf](WealthPilot_Solution_Architecture.pdf)",
           "", "![Solution architecture](architecture/solution-diagram.png)", "",
           "<details><summary>Mermaid source of this diagram (validated: parses, no label cut)</summary>", "",
           "```mermaid", SOLUTION_DIAGRAM.strip(), "```", "", "</details>", ""]
    for title, items in SOLUTION["cards"]:
        out += [f"## {title}", ""] + [f"- {_md_text(i)}" if not i[:2].rstrip(".").isdigit() else _md_text(i)
                                     for i in items] + [""]
    out += [f"*{SOLUTION['grounded']}*", ""]
    return "\n".join(out)


def aws_md() -> str:
    out = [f"# {AWS['title']}", "", f"*{AWS['subtitle']}* {DISCLAIMER}",
           "", "PDF one-pager: [WealthPilot_AWS_Architecture.pdf](WealthPilot_AWS_Architecture.pdf)",
           "", "Live demo: https://d3pmr84q14pg9z.cloudfront.net/", "", "![AWS architecture](architecture/aws-diagram.png)", "",
           "<details><summary>Mermaid source of this diagram (validated: parses, no label cut)</summary>", "",
           "```mermaid", AWS_DIAGRAM.strip(), "```", "", "</details>", "",
           "## Services", "", "| AWS service | Role in WealthPilot | Why |", "|---|---|---|"]
    out += [f"| **{a}** | {b} | {c} |" for a, b, c in AWS_SERVICES]
    out += [""] + sum(([f"## {t}", "", x, ""] for t, x in AWS["notes"]), [])
    out += [f"*{AWS['grounded']}*", "", f"<sub>{AWS['trademark']}</sub>", ""]
    return "\n".join(out)


# ----------------------------------------------------------------------------- HTML (one printed page)

CSS = """
@page { size: Letter; margin: 0.42in 0.5in; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, Helvetica, Arial, sans-serif; color: #172025; font-size: 7.6pt; line-height: 1.38; }
header { display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 2px solid #172025; padding-bottom: 6px; }
.brand { display: flex; align-items: center; gap: 8px; }
.logo { display: flex; gap: 2px; align-items: flex-end; height: 22px; }
.logo i { display: block; width: 5px; background: #c5ad83; }
.logo i:nth-child(1) { height: 10px; } .logo i:nth-child(2) { height: 16px; } .logo i:nth-child(3) { height: 22px; }
h1 { font-size: 17pt; letter-spacing: -0.4px; margin: 0; }
.sub { color: #5d666a; font-size: 8pt; margin-top: 2px; }
.tag { font-size: 6.6pt; text-transform: uppercase; letter-spacing: 1px; color: #8a6d3b; text-align: right; }
.diagram { margin: 8px auto 6px; text-align: center; font-size: 14px; line-height: normal; }
.diagram svg { max-width: 100% !important; width: auto; height: auto; max-height: var(--dh); }
.cap { text-align: center; color: #5d666a; font-size: 6.6pt; margin-bottom: 6px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px 12px; }
.card { border: 1px solid #e5e2dc; border-radius: 6px; padding: 6px 9px; background: #fffdf9; }
.card h2 { font-size: 8.6pt; margin: 0 0 3px; color: #172025; }
.card p { margin: 0 0 3px; }
table { width: 100%; border-collapse: collapse; font-size: 7pt; }
th { text-align: left; background: #172025; color: #fff; padding: 3px 6px; font-weight: 600; }
td { border-bottom: 1px solid #e5e2dc; padding: 2.6px 6px; vertical-align: top; }
td:first-child { font-weight: 600; width: 27%; }
.notes { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 7px; }
.notes h2 { font-size: 8.2pt; margin: 0 0 2px; }
.notes p { margin: 0; }
footer { margin-top: 7px; border-top: 1px solid #e5e2dc; padding-top: 4px; color: #6b7275; font-size: 6.2pt; }
footer p { margin: 0 0 2px; }
"""


def _page(title, subtitle, tag, diagram, caption, body, footer, height="4.6in") -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body style="--dh: {height}">
<header><div><div class="brand"><div class="logo"><i></i><i></i><i></i></div><h1>{html.escape(title)}</h1></div>
<div class="sub">{html.escape(subtitle)}</div></div><div class="tag">PolyFinances Datathon 2026<br>AlphaForge AI · National Bank × AWS</div></header>
<div class="diagram"><pre class="mermaid">{html.escape(diagram)}</pre></div>
<div class="cap">{caption}</div>
{body}
<footer>{footer}</footer>
</body></html>"""


def solution_html() -> str:
    cards = "".join(f'<div class="card"><h2>{t}</h2>' + "".join(f"<p>{i}</p>" for i in items) + "</div>"
                    for t, items in SOLUTION["cards"])
    caption = ("Solid arrows: requests and data. Dashed arrows: tool calls, model prompts, checks. "
               "1-2-3: the order the orchestrator runs the agents for one question.")
    footer = f"<p>{SOLUTION['grounded']}</p><p><b>{DISCLAIMER}</b> Live demo: d3pmr84q14pg9z.cloudfront.net</p>"
    return _page(SOLUTION["title"], SOLUTION["subtitle"], "", SOLUTION_DIAGRAM, caption,
                 f'<div class="grid">{cards}</div>', footer, height="4.9in")


def aws_html() -> str:
    rows = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td></tr>"
                   for a, b, c in AWS_SERVICES)
    notes = "".join(f"<div><h2>{t}</h2><p>{html.escape(x)}</p></div>" for t, x in AWS["notes"])
    caption = ("Everything inside the frame runs in the AWS Region us-east-1. Solid arrows: requests and data. "
               "Dashed arrows: logs, permissions, deployment.")
    body = (f"<table><thead><tr><th>AWS service</th><th>Role in WealthPilot</th><th>Why this choice</th></tr></thead>"
            f"<tbody>{rows}</tbody></table><div class=\"notes\">{notes}</div>")
    footer = (f"<p>{AWS['grounded']}</p><p><b>{DISCLAIMER}</b> Live demo: d3pmr84q14pg9z.cloudfront.net</p>"
              f"<p>{AWS['trademark']}</p>")
    return _page(AWS["title"], AWS["subtitle"], "", AWS_DIAGRAM, caption, body, footer, height="3.9in")



# ----------------------------------------------------------------------------- solution one-pager (deliverable 4)
# Every figure below comes from the repository: models/*.json (evaluations) and the devil's advocate on the demo
# personas (python: api.devils_advocate). Re-check them when the models are retrained.

ONE_PAGER = {
    "title": "WealthPilot",
    "subtitle": "Explainable AI for investment decision support. Understand the decision, challenge the assumptions, "
                "verify the numbers.",
    "problem": "Investors are not short of data. They struggle to judge whether an investment fits their goals, horizon, "
               "finances and tolerance for loss, and most tools give an answer without the reasons, the assumptions or "
               "the limits.",
    "solution": "An educational simulation that builds a fictitious allocation for each of the investor's goals, "
                "explains every figure, challenges risky ideas with evidence, and says when it does not know.",
    "flow": [("Profile", "Rules, not a black box: the lower of risk capacity and risk tolerance sets one of 5 levels; "
                         "each goal's horizon can lower it."),
             ("Plan", "One portfolio per goal, built by stated rules; six-risk map; time machine replays 5 years and "
                      "compares the plan with inflation."),
             ("Devil's advocate", "Deterministic rules challenge an idea: concentration, risk jump, horizon, recency, "
                                  "hype, liquidity, values. Always with the counterpoint."),
             ("Agents", "On Amazon Bedrock™: an Advisor drafts, a Devil's advocate challenges, a Verifier written in "
                        "code checks every number against its receipt (R1, R2, ...).")],
    "personas": [
        ("Robert, 59, retires in 4 years", "wants 25% in Tesla: \"Reconsider\". 25% against a 7.5% single-stock limit, "
                                           "86% of the portfolio's risk, worst fall from 8.9% to 25.0%, and Tesla took "
                                           "2.9 years to recover from a 71% fall."),
        ("Amira, 26, growth", "15% in bitcoin goes above her crypto limit; her plan keeps a small, capped bitcoin share "
                              "inside a diversified portfolio."),
        ("Mateo, 41, balanced, ESG", "10% in Exxon goes against his values: his plan uses an ESG-screened U.S. fund and "
                                     "excludes the sectors he chose."),
    ],
    "data": "Yahoo Finance prices for 33 assets (stocks, ETFs, gold, crypto), converted to CAD with Bank of Canada "
            "rates; Bank of Canada, Statistics Canada and FRED series used only after their publication date; official "
            "news (Bank of Canada, Federal Reserve, Statistics Canada) read within robots.txt; headlines labelled fact "
            "or opinion.",
    "validation": [
        "Inflation: a simple mean-reversion rule beat our ridge model out of sample (12-month error 1.04 vs 1.43 "
        "points). The app uses the rule and says so.",
        "Crypto and gold: gradient boosting does worse than the historical average out of sample (R² −34% bitcoin, "
        "−3% ether, −7% gold), so the gauge shows \"Not scored\".",
        "Market timing: after realistic costs, the ML signal beats holding in only 5 to 7 of 17 test years, never "
        "significantly. It is shown as evidence that timing is hard.",
        "243 automated tests; agent answers are checked against receipts before they are shown.",
    ],
    "original": [
        "No model approves its own answer: the verifier is code.",
        "It refuses to guess: \"Not scored\", assets without enough data are not offered for review.",
        "It contradicts the investor when the data says so, and agrees when the data supports them.",
        "Facts, planning assumptions (FP Canada/IFP 2026) and scenarios are labelled separately.",
    ],
    "value": "Understand why an option fits or not, see the trade-offs in dollars, test an idea before acting, and "
             "learn the reasoning, with no real money at stake.",
    "aws": "Amazon CloudFront™, Amazon S3™, AWS Lambda™, Amazon Bedrock™, Amazon DynamoDB™, Amazon SageMaker AI™, "
           "Amazon EventBridge Scheduler™, Amazon CloudWatch™ and AWS IAM™, in us-east-1. Details: AWS architecture "
           "one-pager.",
}

ONE_PAGER_CSS = """
body { font-size: 8.7pt; line-height: 1.42; }
.tag { white-space: nowrap; }
.lead { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 9px; }
.lead div { border-left: 3px solid #c5ad83; padding: 2px 0 2px 9px; }
.lead h2, .sec h2 { font-size: 9.4pt; margin: 0 0 2px; text-transform: uppercase; letter-spacing: .6px; color: #8a6d3b; }
.lead p { margin: 0; font-size: 9.6pt; }
.flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; margin: 10px 0 4px; }
.step { position: relative; background: #fdf8ee; border: 1px solid #e3d6bd; padding: 6px 9px 6px 12px; margin-right: 12px; }
.step:not(:last-child)::after { content: "→"; position: absolute; right: -12px; top: 38%; font-weight: 700; color: #8a6d3b; }
.step b { display: block; font-size: 9.4pt; margin-bottom: 2px; }
.sec { margin-top: 11px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 14px; }
.persona { margin: 0 0 3px; }
ul { margin: 2px 0 0; padding-left: 14px; }
li { margin-bottom: 2px; }
.value { margin-top: 12px; font-size: 9.4pt; background: #172025; color: #fff; padding: 7px 10px; border-radius: 6px; }
.value b { color: #c5ad83; }
"""


def one_pager_html() -> str:
    o = ONE_PAGER
    flow = "".join(f'<div class="step"><b>{t}</b>{html.escape(x)}</div>' for t, x in o["flow"])
    personas = "".join(f'<p class="persona"><b>{html.escape(n)}</b>: {html.escape(x)}</p>' for n, x in o["personas"])
    li = lambda items: "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"  # noqa: E731
    body = f"""
<div class="lead"><div><h2>The problem</h2><p>{html.escape(o['problem'])}</p></div>
<div><h2>Our solution</h2><p>{html.escape(o['solution'])}</p></div></div>
<div class="sec"><h2>How it works</h2><div class="flow">{flow}</div></div>
<div class="sec"><h2>It adapts to the investor (live demo personas)</h2>{personas}</div>
<div class="two">
  <div class="sec"><h2>Data, with its limits</h2><p>{html.escape(o['data'])} Limits: five years of starter prices,
  survivorship bias, incomplete ESG coverage, model uncertainty.</p>
  <h2 style="margin-top:6px">What is original</h2>{li(o['original'])}</div>
  <div class="sec"><h2>Validated, and reported honestly</h2>{li(o['validation'])}
  <h2 style="margin-top:6px">On AWS</h2><p>{html.escape(o['aws'])}</p></div>
</div>
<div class="value"><b>User value.</b> {html.escape(o['value'])}</div>"""
    footer = (f"<p><b>{DISCLAIMER}</b> No confidential banking data. Live demo: d3pmr84q14pg9z.cloudfront.net · "
              "Code: github.com/Juanita-HP/WealthPilot</p><p>" + AWS["trademark"] + "</p>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>WealthPilot one-pager</title>
<style>{CSS}{ONE_PAGER_CSS}</style></head><body>
<header><div><div class="brand"><div class="logo"><i></i><i></i><i></i></div><h1>{o['title']}</h1></div>
<div class="sub">{html.escape(o['subtitle'])}</div></div><div class="tag">PolyFinances Datathon 2026<br>AlphaForge AI · National Bank × AWS</div></header>
{body}
<footer>{footer}</footer>
</body></html>"""


def one_pager_md() -> str:
    o = ONE_PAGER
    out = [f"# {o['title']}", "", f"*{o['subtitle']}*", "", "PDF: [WealthPilot_One_Pager.pdf](WealthPilot_One_Pager.pdf)",
           "", "## The problem", "", o["problem"], "", "## Our solution", "", o["solution"], "", "## How it works", ""]
    out += [f"{i}. **{t}**: {x}" for i, (t, x) in enumerate(o["flow"], 1)]
    out += ["", "## It adapts to the investor", ""] + [f"- **{n}**: {x}" for n, x in o["personas"]]
    out += ["", "## Data, with its limits", "", o["data"] + " Limits: five years of starter prices, survivorship bias, "
            "incomplete ESG coverage, model uncertainty.", "", "## What is original", ""] + [f"- {i}" for i in o["original"]]
    out += ["", "## Validated, and reported honestly", ""] + [f"- {i}" for i in o["validation"]]
    out += ["", "## On AWS", "", o["aws"], "", "## User value", "", o["value"], "", f"*{DISCLAIMER}*", "",
            f"<sub>{AWS['trademark']}</sub>", ""]
    return "\n".join(out)


def main() -> None:
    (ROOT / "docs" / "SOLUTION_ARCHITECTURE.md").write_text(solution_md(), encoding="utf-8")
    (ROOT / "docs" / "AWS_ARCHITECTURE.md").write_text(aws_md(), encoding="utf-8")
    (HERE / "solution.html").write_text(solution_html(), encoding="utf-8")
    (HERE / "aws.html").write_text(aws_html(), encoding="utf-8")
    (HERE / "diagrams.json").write_text(json.dumps({"solution": SOLUTION_DIAGRAM, "aws": AWS_DIAGRAM}), encoding="utf-8")
    (ROOT / "docs" / "ONE_PAGER.md").write_text(one_pager_md(), encoding="utf-8")
    (HERE / "onepager.html").write_text(one_pager_html(), encoding="utf-8")
    print("wrote docs/ONE_PAGER.md, docs/SOLUTION_ARCHITECTURE.md, docs/AWS_ARCHITECTURE.md and the HTML pages")


if __name__ == "__main__":
    main()
