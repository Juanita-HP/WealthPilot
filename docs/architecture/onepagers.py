"""Source of the two architecture one-pagers (solution and AWS): diagrams, text, and the files built from them.

    python docs/architecture/onepagers.py          # writes the Markdown pages and the HTML pages
    node docs/architecture/render.js <mermaid.min.js>   # validates, renders the PDFs and the diagram images

Mermaid 11.4.1: ``npm pack mermaid@11.4.1 && tar xzf mermaid-11.4.1.tgz`` gives package/dist/mermaid.min.js.
render.js needs Playwright with Chromium. It fails if a diagram does not parse, if any label is cut or outside its
box (light and dark themes, and inside the one-pager), or if a one-pager is longer than one page.

Diagrams are Mermaid class diagrams used with UML notation: stereotypes («component», «agent», «datastore»,
«executionEnvironment», ...), dependencies (dashed arrows), composition (filled diamond) and associations
(solid arrows, labelled with the protocol or the data exchanged). Every element names a real part of the code or of
the AWS templates (see the "Grounded in" lines).
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
classDiagram
    direction LR
    class Web["Web interface"] {
        <<component>>
        React 18 + Vite
        Profile, plan, time machine
        Stocks, devil's advocate
    }
    class API["API service"] {
        <<component>>
        FastAPI
        Signed sessions
        Input validation
    }
    namespace Agent_layer {
        class Orchestrator["Agent orchestrator"] {
            <<component>>
            Advisor, then advocate
            Verifier, one revision
        }
        class Advisor["Advisor"] {
            <<agent>>
            LLM with tool calls
            Answer cites receipts
        }
        class Critic["Devil's advocate"] {
            <<agent>>
            LLM with review tools
            Challenge and counterpoint
        }
        class Verifier["Verifier"] {
            <<component>>
            Deterministic code
            Each number vs receipt
            Blocks trade directives
        }
        class Ledger["Receipt ledger"] {
            <<component>>
            Receipts R1, R2, ...
        }
    }
    namespace Decision_engine {
        class Engine["Decision engine"] {
            <<component>>
            Profile, goals, allocation
            Risk map and metrics
            Time machine, scenarios
            Advocate rules, liquidity
            News: facts vs opinions
        }
        class Models["Forecast models"] {
            <<component>>
            Inflation, crypto and gold
            Market timing
            Walk-forward validated
        }
    }
    namespace Storage {
        class Data["Market and macro data"] {
            <<datastore>>
            Prices in CAD
            Publication lags
        }
        class Stores["Accounts and traces"] {
            <<datastore>>
            Profiles, audit trail
        }
    }
    class Providers["Public data sources"] {
        <<external>>
        Yahoo Finance
        Bank of Canada, StatCan
        FRED, official feeds
    }
    class LLM["LLM service"] {
        <<external>>
        Amazon Bedrock
    }

    Web ..> API : REST JSON
    API ..> Engine : plan, scores, reviews
    API ..> Orchestrator : questions
    API ..> Stores : profiles, traces
    Orchestrator *-- Advisor
    Orchestrator *-- Critic
    Orchestrator *-- Verifier
    Advisor ..> Engine : tool calls
    Critic ..> Engine : review tools
    Orchestrator ..> LLM : agent prompts
    Engine --> Ledger : receipts
    Verifier ..> Ledger : checks
    Engine ..> Models : forecasts
    Engine ..> Data : reads
    Data ..> Providers : sourced from
'''

AWS_DIAGRAM = INIT + '''
classDiagram
    direction TB
    class Browser["Investor browser"] {
        <<device>>
    }
    namespace AWS_Cloud_us_east_1 {
        class CloudFront["Amazon CloudFront"] {
            <<edge service>>
            HTTPS distribution
            /api/* to AWS Lambda
            Other paths to Amazon S3
        }
        class Site["Amazon S3 website bucket"] {
            <<storage>>
            artifact: React build
            Private, origin access control
        }
        class ApiFn["AWS Lambda API function"] {
            <<executionEnvironment>>
            Python 3.13, function URL
            artifact: FastAPI app
            Tools, agents, verifier
        }
        class Bedrock["Amazon Bedrock"] {
            <<AI service>>
            Converse API
            Claude Haiku 4.5
            Amazon Nova 2 Lite fallback
        }
        class Users["Amazon DynamoDB users"] {
            <<table>>
            Accounts, profiles
        }
        class Traces["Amazon DynamoDB traces"] {
            <<table>>
            Agent turns, receipts
        }
        class DataBucket["Amazon S3 data bucket"] {
            <<storage>>
            Market and macro data
            Published models
            Training outputs
        }
        class Logs["Amazon CloudWatch"] {
            <<monitoring>>
            Logs
        }
        class Scheduler["Amazon EventBridge Scheduler"] {
            <<scheduler>>
            Monthly
        }
        class Launcher["AWS Lambda training launcher"] {
            <<executionEnvironment>>
            CreateTrainingJob
        }
        class Training["Amazon SageMaker AI training job"] {
            <<executionEnvironment>>
            scikit-learn container
            ml.m5.large
            Candidate models
        }
    }

    Browser --> CloudFront : HTTPS
    CloudFront --> Site : pages
    CloudFront --> ApiFn : HTTPS /api
    ApiFn --> Users : read, write
    ApiFn --> Traces : write
    ApiFn --> DataBucket : read
    ApiFn --> Bedrock : Converse
    ApiFn ..> Logs : logs
    Scheduler --> Launcher : monthly
    Launcher --> Training : starts
    Training --> DataBucket : reads data, writes candidates
'''

DISCLAIMER = "Educational simulation: fictitious allocations, no real trades, not personalized financial advice."

# ----------------------------------------------------------------------------- solution page text

SOLUTION = {
    "title": "WealthPilot · Solution architecture",
    "subtitle": "Explainable, agentic investment simulation. UML component diagram.",
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
    "subtitle": "Region us-east-1 (US East, N. Virginia). UML deployment view of the live demo.",
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
           "", "PDF one-pager: [WealthPilot_Solution_Architecture.pdf](architecture/WealthPilot_Solution_Architecture.pdf)",
           "", "![Solution architecture, UML](architecture/solution-diagram.png)", "",
           "<details><summary>Mermaid source of this diagram (validated: parses, no label cut)</summary>", "",
           "```mermaid", SOLUTION_DIAGRAM.strip(), "```", "", "</details>", ""]
    for title, items in SOLUTION["cards"]:
        out += [f"## {title}", ""] + [f"- {_md_text(i)}" if not i[:2].rstrip(".").isdigit() else _md_text(i)
                                     for i in items] + [""]
    out += [f"*{SOLUTION['grounded']}*", ""]
    return "\n".join(out)


def aws_md() -> str:
    out = [f"# {AWS['title']}", "", f"*{AWS['subtitle']}* {DISCLAIMER}",
           "", "PDF one-pager: [WealthPilot_AWS_Architecture.pdf](architecture/WealthPilot_AWS_Architecture.pdf)",
           "", "Live demo: https://d3pmr84q14pg9z.cloudfront.net/", "", "![AWS architecture, UML](architecture/aws-diagram.png)", "",
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
    caption = ("UML component view. Dashed arrow: depends on; filled diamond: composition; solid arrow: writes. "
               "Grouping boxes: agent layer, decision engine, storage.")
    footer = f"<p>{SOLUTION['grounded']}</p><p><b>{DISCLAIMER}</b> Live demo: d3pmr84q14pg9z.cloudfront.net</p>"
    return _page(SOLUTION["title"], SOLUTION["subtitle"], "", SOLUTION_DIAGRAM, caption,
                 f'<div class="grid">{cards}</div>', footer, height="4.9in")


def aws_html() -> str:
    rows = "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td></tr>"
                   for a, b, c in AWS_SERVICES)
    notes = "".join(f"<div><h2>{t}</h2><p>{html.escape(x)}</p></div>" for t, x in AWS["notes"])
    caption = ("UML deployment view: nodes with their stereotype, artifacts deployed on them, and communication "
               "paths labelled with the protocol or the data exchanged. The frame is the AWS Region us-east-1.")
    body = (f"<table><thead><tr><th>AWS service</th><th>Role in WealthPilot</th><th>Why this choice</th></tr></thead>"
            f"<tbody>{rows}</tbody></table><div class=\"notes\">{notes}</div>")
    footer = (f"<p>{AWS['grounded']}</p><p><b>{DISCLAIMER}</b> Live demo: d3pmr84q14pg9z.cloudfront.net</p>"
              f"<p>{AWS['trademark']}</p>")
    return _page(AWS["title"], AWS["subtitle"], "", AWS_DIAGRAM, caption, body, footer, height="3.9in")


def main() -> None:
    (ROOT / "docs" / "SOLUTION_ARCHITECTURE.md").write_text(solution_md(), encoding="utf-8")
    (ROOT / "docs" / "AWS_ARCHITECTURE.md").write_text(aws_md(), encoding="utf-8")
    (HERE / "solution.html").write_text(solution_html(), encoding="utf-8")
    (HERE / "aws.html").write_text(aws_html(), encoding="utf-8")
    (HERE / "diagrams.json").write_text(json.dumps({"solution": SOLUTION_DIAGRAM, "aws": AWS_DIAGRAM}), encoding="utf-8")
    print("wrote docs/SOLUTION_ARCHITECTURE.md, docs/AWS_ARCHITECTURE.md, docs/architecture/{solution,aws}.html")


if __name__ == "__main__":
    main()
