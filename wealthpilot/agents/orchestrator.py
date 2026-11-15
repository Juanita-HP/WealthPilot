"""Agent workflow: advisor -> devil's advocate -> verifier (-> one revision).

Roles, and why each exists:

* Advisor (LLM + tools): understands the question, calls the calculation tools,
  drafts the answer with a receipt id after every number.
* Devil's advocate (LLM + review tools): challenges the request AND the draft
  with evidence, including the counterpoint when the data favors the request.
* Debate: the advisor, as arbiter, rewrites its answer responding to each
  challenge (accepted or rejected with evidence) - the "debate agent" idea from
  the BNC kick-off.
* Verifier (code, not a model): checks every number against the receipts and
  applies governance rules. If it fails, the advisor gets one revision with the
  list of problems; anything still unverified is shown to the user as such.

Everything is recorded in the session ledger, which is the execution trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .llm import LLM
from .tools import Session, call_tool, tools_for
from .verifier import Report, verify

MAX_TOOL_ROUNDS = 8
DISCLAIMER = ("Simulation for education only (PolyFinances datathon). Not financial advice and not a recommendation "
              "to buy or sell. Past results do not predict future returns.")

ADVISOR_SYSTEM = """You are WealthPilot's advisor agent, part of an educational investment SIMULATION. You help a fictional investor understand options. You never execute trades and never tell anyone to buy or sell.

How to work:
- Get every number from a tool. Never compute, estimate or recall a figure yourself.
- Each tool result carries a receipt id. After every sentence that states a number, cite the receipt, for example: "The worst 12 months lost 8.2% [R4]." A sentence without a receipt must not contain figures.
- Start from the investor, not the product: goals, horizon of each goal, capacity and tolerance, constraints, then preferences. Preferences (ESG, values, simplicity, themes) apply inside the constraints, never above them.
- If the question needs a profile and there is none, ask for the missing questionnaire answers (ids and options are in build_profile) instead of guessing. When the investor names goals, use plan_goals: each goal has its own horizon and sub-portfolio.
- When a request conflicts with the profile, say so plainly, explain it with tool results, and ask whether the profile or the request should change. Do not simply agree.
- Structure the answer like this, with short sections:
  1. Answer (two or three sentences)
  2. Data used (what, which period, which currency, which source)
  3. Finding and analysis
  4. Proposal
  5. Why this choice, and its limits (what is a fact, what is an assumption)
  6. What would change this answer (use what_would_change)
- News: when the investor asks about current events or why the portfolio moved, use macro_news_impact (official texts, read in full, with quotes and the exposed share of the portfolio). Quote the official sentence, say what share of the portfolio is exposed and what is not, and separate the fact (what was announced) from the source's own forecasts. News explain; they never justify changing the allocation (that would be market timing). Headlines from news_digest are context only.
- Adapt depth to the investor's experience: none or beginner, plain words and fewer numbers; intermediate, standard; advanced, include volatility, drawdown dates and Sharpe ratios.
- Be concise. Reply in the language of the investor's question."""

ADVOCATE_SYSTEM = """You are WealthPilot's devil's advocate agent in an educational investment SIMULATION. You receive the investor's question, the advisor's draft and the list of receipts already produced.

Your job is to challenge both the investor's request and the advisor's draft, using your review tools (review_trade, review_allocation, replay_history, stress_test, strategy_lab, ticker_overview, compare_allocations, inflation_forecast, macro_news_impact).

Rules:
- Every number you state comes from a tool result and is followed by its receipt id, for example [R7]. Earlier receipts may be cited too.
- Name the bias or risk in plain words (concentration, recency bias, horizon mismatch, overfitting, home bias, reacting to news).
- Give the honest counterpoint when the data supports the request. Never hide that something would have paid off.
- End with one question for the investor.
- If nothing deserves a challenge, say so in one sentence.
- At most about 150 words. Do not repeat the draft. Reply in the language of the investor's question."""

DEBATE_PROMPT = """The devil's advocate challenged your draft:

{critique}

Act as the arbiter of this debate. Rewrite your complete answer so that it responds to each challenge: accept it and change the proposal, or reject it with evidence. Add a short section "Debate" listing each challenge and how it was resolved. Same rules: every number from a tool, with its receipt."""

REVISION_PROMPT = """The verifier found problems in your answer. Rewrite the complete answer and fix every item:
{problems}
Remove any figure you cannot support with a receipt, or call a tool to get it. Keep the same structure."""


@dataclass
class AgentAnswer:
    text: str
    draft: str
    critique: str
    report: Report
    revisions: int
    trace: list[dict] = field(default_factory=list)

    def to_dict(self):
        return {"text": self.text, "draft": self.draft, "critique": self.critique, "report": self.report.to_dict(),
                "revisions": self.revisions, "trace": self.trace}


def _context(session: Session) -> str:
    p = session.profile
    if p is None:
        return "Investor context: no profile yet."
    port = "set" if session.portfolio else "not set"
    return (f"Investor context: experience={p.experience}, risk level={p.level} ({p.level_name}), "
            f"fictional amount={session.amount:,.0f} CAD, current portfolio {port}.")


def run_agent(llm: LLM, session: Session, agent: str, system: str, messages: list, trace: list,
              effort: str | None = None) -> tuple[str, list]:
    """Tool-use loop for one agent. Returns its final text and the updated message list."""
    defs = [t.definition() for t in tools_for(agent)]
    for _ in range(MAX_TOOL_ROUNDS):
        resp = llm.create(system, messages, defs, effort=effort)
        if resp.stop_reason == "refusal":
            trace.append({"agent": agent, "event": "refusal"})
            return "The model declined this request.", messages
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "max_tokens":
                trace.append({"agent": agent, "event": "max_tokens"})
            return text, messages
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for c in calls:
            rid, content, is_error = call_tool(session, agent, c.name, dict(c.input))
            trace.append({"agent": agent, "tool": c.name, "receipt": rid, "error": is_error})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})  # all results of one turn in a single message
    trace.append({"agent": agent, "event": "tool_round_limit"})
    return "I could not finish within the tool-call limit.", messages


def _problems(report: Report) -> str:
    lines = []
    for c in report.unverified:
        why = "no receipt cited in that sentence" if c.status == "no_citation" else f"not found in {', '.join(c.receipts)}"
        lines.append(f'- "{c.text}" in: "{c.sentence[:160]}" ({why})')
    for g in report.governance:
        lines.append(f'- governance {g["code"]}: "{g["excerpt"].strip()}"')
    return "\n".join(lines)


def _receipt_index(session: Session) -> str:
    return "\n".join(f"{r.id}: {r.tool}({json.dumps(r.inputs)[:120]})" + (" ERROR" if r.error else "")
                     for r in session.ledger.receipts)


def ask(session: Session, question: str, llm: LLM, advocate: bool = True, max_revisions: int = 1,
        effort: str | None = None, debate: bool = True) -> AgentAnswer:
    trace: list[dict] = []
    advisor_msgs = [{"role": "user", "content": f"{_context(session)}\n\nQuestion: {question}"}]
    draft, advisor_msgs = run_agent(llm, session, "advisor", ADVISOR_SYSTEM, advisor_msgs, trace, effort)

    critique = ""
    if advocate:
        adv_msgs = [{"role": "user", "content":
                     f"{_context(session)}\n\nInvestor question: {question}\n\nAdvisor draft:\n{draft}\n\n"
                     f"Receipts so far:\n{_receipt_index(session)}"}]
        critique, _ = run_agent(llm, session, "advocate", ADVOCATE_SYSTEM, adv_msgs, trace, effort)
        if debate and critique:
            # Arbitration: the advisor must answer each challenge, keeping or changing its proposal with evidence.
            advisor_msgs.append({"role": "user", "content": DEBATE_PROMPT.format(critique=critique)})
            draft, advisor_msgs = run_agent(llm, session, "advisor", ADVISOR_SYSTEM, advisor_msgs, trace, effort)
            trace.append({"agent": "arbiter", "event": "debate_resolved"})

    report = verify(draft + "\n" + critique, session.ledger)
    revisions = 0
    while not report.passed and revisions < max_revisions:
        draft_report = verify(draft, session.ledger)
        if draft_report.passed:
            break  # the remaining problems are in the critique; they are shown, not silently edited
        advisor_msgs.append({"role": "user", "content": REVISION_PROMPT.format(problems=_problems(draft_report))})
        draft, advisor_msgs = run_agent(llm, session, "advisor", ADVISOR_SYSTEM, advisor_msgs, trace, effort)
        revisions += 1
        trace.append({"agent": "verifier", "event": "revision", "problems": len(draft_report.unverified)})
        report = verify(draft + "\n" + critique, session.ledger)

    text = draft
    if critique:
        text += "\n\n---\n**Devil's advocate**\n\n" + critique
    text += f"\n\n---\n**Verification**: {sum(c.status == 'verified' for c in report.claims)} of {len(report.claims)} " \
            f"figures checked against receipts."
    if report.unverified:
        text += " Not verified: " + "; ".join(f'"{c.text}"' for c in report.unverified) + "."
    if report.governance:
        text += " Governance flags: " + ", ".join(g["code"] for g in report.governance) + "."
    text += f"\n\n_{DISCLAIMER}_"
    trace.append({"agent": "verifier", "coverage": report.coverage, "passed": report.passed})
    return AgentAnswer(text, draft, critique, report, revisions, trace)
