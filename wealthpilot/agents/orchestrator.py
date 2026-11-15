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

ADVISOR_SYSTEM = """You are WealthPilot's advisor agent in an educational investment SIMULATION. You help a fictional investor understand their options in clear, everyday language that a complete beginner can easily follow. You never execute trades and never tell anyone to buy or sell.

How to work:
- Answer ONLY what the investor actually asked. Stay strictly on-topic: call only the 1 or 2 tools directly needed for the question (for a stock question, call ticker_overview and/or review_trade; for a portfolio question, call review_allocation or risk_map; for macro news, call macro_news_impact). If the message is just a greeting or not a concrete question, reply briefly in 2-3 friendly sentences without calling tools.
- Get every number from a tool or the provided investor context receipt. Never compute, subtract, or estimate a figure yourself (even differences like a change between two numbers), because every number in your text is checked against tool receipts.
- Each tool result carries a receipt id. After every sentence that states a number, cite the receipt, for example: "The worst 12 months lost 8.2% [R4]." A sentence without a receipt must not contain figures.
- Start from the investor's profile (goals, horizon, risk level, limits, and current portfolio), then answer their question. Preferences (ESG, values, simplicity, themes) apply inside the constraints, never above them.
- If the question needs a profile and there is none, ask for the missing questionnaire answers (ids and options are in build_profile) instead of guessing.
- Format your answer so a beginner can read and understand it in 20 seconds:
  - Use short Markdown headings (`###`), bullet points (`- `), and **bold** key words.
  - Explain every financial concept in simple everyday words (for example, say "worst temporary drop" instead of raw "max drawdown", or explain "Sharpe ratio (return earned per unit of risk)").
  - Round numbers cleanly (e.g., `8.3%` or `$1,250`, never long decimals like `-0.08305455`).
  - Organize into 3 short, clear sections:
    1. `### Bottom Line` (or `### En bref` in French): 2–3 plain sentences directly answering the question.
    2. `### Why for Your Profile` (or `### Pourquoi selon votre profil`): 3–4 bullet points connecting the tool results to the investor's risk level and current portfolio.
    3. `### Key Facts & Limits` (or `### Points clés et limites`): what comes from historical data vs. assumptions, and what would change the conclusion.
- Output ONLY the final answer for the investor. Never include internal reasoning, scratchpad notes, or phrases like "Now I have the correct data" or "Let me rewrite".
- Be concise (around 150–220 words). Reply in the language of the investor's question (French if asked in French, English if asked in English)."""

ADVOCATE_SYSTEM = """You are WealthPilot's devil's advocate agent in an educational investment SIMULATION. You receive the investor's question, the advisor's draft, and the receipts already produced.

Your job is to give a short, beginner-friendly second opinion that challenges the investor's idea or highlights the main risk/blind spot, plus the honest counterpoint when past data supports the idea.

Rules:
- Reuse the figures in the existing receipts `[R#]` whenever they already answer your point—do not call extra tools unless a critical check is missing, and never call unrelated tools (`strategy_lab`, `inflation_forecast`) unless the investor specifically asked about trading rules or inflation.
- Every number you state must come directly from a receipt and be followed by its receipt id, for example `[R2]`. Never compute new numbers yourself, and never invent hypothetical percentages or uncited numbers (even inside a question).
- Write for a complete beginner in plain, simple words: name the main risk or bias (e.g., putting too much in one stock, chasing recent headlines, horizon too short) and the honest counterpoint using 2–3 short bullet points (`- **Main risk:** ...`, `- **Counterpoint:** ...`).
- End with one clear question (`- **Question for you:** ...`) to help the investor reflect. Your question MUST NOT contain any digits, percentages, or dollar amounts.
- If the investor only sent a greeting or nothing deserves a challenge, say so in one short sentence.
- At most 100 words. Do not repeat the draft. Reply in the language of the investor's question."""

DEBATE_PROMPT = """The devil's advocate challenged your draft:

{critique}

Act as the arbiter of this debate. Rewrite your complete answer for the investor so that it integrates any valid point from the challenge and briefly notes how the challenge was resolved in a short "### Debate" section. Output ONLY the final beginner-friendly answer—never include meta-commentary like "You're absolutely right" or "Let me fix that". Same rules: every number from a tool, with its receipt."""

REVISION_PROMPT = """The verifier found problems in your answer. Rewrite the complete answer and fix every item:
{problems}
Remove any figure you cannot support with a receipt (including differences you calculated yourself), or call a tool to get it. Output ONLY the final beginner-friendly answer with the same clean Markdown headings—never include preamble or notes like "Now I have the correct data" or "Let me rewrite"."""


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
    port = (
        "set (" + ", ".join(f"{k}: {v * 100:.1f}%" for k, v in sorted(session.portfolio.items(), key=lambda x: -x[1])) + ")"
        if session.portfolio else "not set"
    )
    c = p.constraints
    ctx_r = next((r for r in session.ledger.receipts if r.tool == "investor_context"), None)
    ctx_receipt = ctx_r.id if ctx_r else None
    cite = f" (cite [{ctx_receipt}] when stating these profile, goal, or portfolio numbers)" if ctx_receipt else ""
    extra_parts = []
    if ctx_r and isinstance(ctx_r.output, dict):
        out = ctx_r.output
        if out.get("age") is not None:
            extra_parts.append(f"age={out['age']}")
        if out.get("score_10") is not None:
            extra_parts.append(f"risk score={out['score_10']}/10")
        if out.get("capacity") is not None and out.get("tolerance") is not None:
            extra_parts.append(f"capacity={out['capacity']:.0f}/100, tolerance={out['tolerance']:.0f}/100")
        if out.get("emergency_months") is not None:
            extra_parts.append(f"emergency cushion={out['emergency_months']:.1f} months")
        goals = out.get("goals") or []
        if goals:
            g_txt = "; ".join(
                f"{g['name']} (horizon {g['horizon_years']:g} yrs, target ${g['target_amount']:,.0f}, current ${g['current_amount']:,.0f})"
                for g in goals
            )
            extra_parts.append(f"goals=[{g_txt}]")
    extra_str = (", " + ", ".join(extra_parts)) if extra_parts else ""
    return (f"Investor context{cite}: experience={p.experience}, risk level={p.level} ({p.level_name}){extra_str}, "
            f"fictional amount={session.amount:,.0f} CAD, current portfolio {port}. "
            f"Limits: stocks {c.equity_min * 100:.0f}%–{c.equity_max * 100:.0f}%, "
            f"max single stock {c.limits.max_single_security * 100:.0f}%, "
            f"max sector {c.limits.max_sector * 100:.0f}%, max crypto {c.max_crypto * 100:.0f}%.")


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
    lines = []
    for r in session.ledger.receipts:
        head = f"{r.id}: {r.tool}({json.dumps(r.inputs)[:120]})"
        if r.error:
            lines.append(head + " ERROR")
        else:
            out_str = json.dumps(r.output, separators=(",", ":"))
            lines.append(f"{head} -> {out_str[:1200]}")
    return "\n".join(lines)


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
        critique, adv_msgs = run_agent(llm, session, "advocate", ADVOCATE_SYSTEM, adv_msgs, trace, effort)
        if debate and critique:
            # Arbitration: the advisor must answer each challenge, keeping or changing its proposal with evidence.
            advisor_msgs.append({"role": "user", "content": DEBATE_PROMPT.format(critique=critique)})
            draft, advisor_msgs = run_agent(llm, session, "advisor", ADVISOR_SYSTEM, advisor_msgs, trace, effort)
            trace.append({"agent": "arbiter", "event": "debate_resolved"})

    report = verify(draft + "\n" + critique, session.ledger)
    revisions = 0
    while not report.passed and revisions < max_revisions:
        draft_report = verify(draft, session.ledger)
        if not draft_report.passed:
            advisor_msgs.append({"role": "user", "content": REVISION_PROMPT.format(problems=_problems(draft_report))})
            draft, advisor_msgs = run_agent(llm, session, "advisor", ADVISOR_SYSTEM, advisor_msgs, trace, effort)
            revisions += 1
            trace.append({"agent": "verifier", "event": "revision", "problems": len(draft_report.unverified)})
        elif critique:
            crit_report = verify(critique, session.ledger)
            if not crit_report.passed:
                adv_msgs.append({"role": "user", "content": REVISION_PROMPT.format(problems=_problems(crit_report))})
                critique, adv_msgs = run_agent(llm, session, "advocate", ADVOCATE_SYSTEM, adv_msgs, trace, effort)
                revisions += 1
                trace.append({"agent": "verifier", "event": "advocate_revision", "problems": len(crit_report.unverified)})
            else:
                break
        else:
            break
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
