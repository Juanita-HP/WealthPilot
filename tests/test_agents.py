import json

import pytest

from tests.conftest import requires_starter
from tests.test_profile import ROBERT
from wealthpilot.agents import ledger as lg
from wealthpilot.agents import orchestrator as orch
from wealthpilot.agents import tools as tl
from wealthpilot.agents import verifier as vf
from wealthpilot.agents.llm import ScriptedLLM

ROBERT_ANSWERS = [{"question": k, "answer": v} for k, v in ROBERT.items()]
BUILD = ("build_profile", {"answers": ROBERT_ANSWERS, "esg": "none", "excluded_sectors": [], "crypto": "no",
                           "region": "balanced", "themes": [], "amount": 150000, "simplicity": False, "values": []})


# ----------------------------------------------------------------------------- verifier units

def ledger_with(output, inputs=None):
    led = lg.Ledger("t")
    led.record("tool", "advisor", inputs or {}, output)
    return led


@pytest.mark.parametrize("text", [
    "The worst fall was 28.9% [R1].",
    "La pire baisse a été de 28,9 % [R1].",
    "It went from 105,867 $ to 75,294 $ [R1].",
    "Elle est passée de 105 867 $ à 75 294 $ [R1].",
    "You would have 150 000 $ invested [R1].",
])
def test_verifier_accepts_supported_numbers_in_both_languages(text):
    led = ledger_with({"max_drawdown": 0.28934, "peak": 105867.2, "trough": 75294.4}, inputs={"amount": 150000})
    rep = vf.verify(text, led)
    assert rep.claims and rep.passed, rep.to_dict()


def test_verifier_rejects_wrong_or_uncited_numbers():
    led = ledger_with({"max_drawdown": 0.28934})
    rep = vf.verify("The worst fall was 31.2% [R1]. Volatility was 19.5%.", led)
    assert {c.status for c in rep.unverified} == {"not_found", "no_citation"}
    assert not rep.passed


def test_verifier_ignores_years_and_small_counts():
    rep = vf.verify("In 2022, 3 of 5 levels fell.", lg.Ledger("t"))
    assert rep.claims == [] and rep.passed


def test_governance_flags_directives_but_not_negations():
    assert {g["code"] for g in vf.check_governance("You should buy TSLA now.")} == {"DIRECTIVE_TO_TRADE"}
    assert vf.check_governance("Returns are not guaranteed returns of any kind.") == []
    assert vf.check_governance("Ce placement offre des rendements garantis.")[0]["code"] == "GUARANTEE"


def test_jsonable_handles_numpy_pandas():
    import numpy as np
    import pandas as pd
    out = lg.jsonable({"a": np.float64(0.5), "b": pd.Timestamp("2022-01-03"), "c": float("nan"), "d": np.int64(3)})
    assert out == {"a": 0.5, "b": "2022-01-03", "c": None, "d": 3}
    json.dumps(out)


# ----------------------------------------------------------------------------- tool definitions

def _strict_ok(schema):
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, schema
        assert set(schema.get("required", [])) == set(schema.get("properties", {})), schema
        for p in schema.get("properties", {}).values():
            _strict_ok(p)
    if schema.get("type") == "array":
        _strict_ok(schema["items"])


def test_tool_schemas_are_strict_compatible():
    for t in tl.TOOLS:
        d = t.definition()
        assert d["strict"] is True
        _strict_ok(d["input_schema"])


def test_roles_have_distinct_tools():
    advisor = {t.name for t in tl.tools_for("advisor")}
    advocate = {t.name for t in tl.tools_for("advocate")}
    assert "build_profile" in advisor and "build_profile" not in advocate
    assert {"review_trade", "review_allocation"} <= advocate


# ----------------------------------------------------------------------------- end-to-end with a scripted model

@pytest.fixture
def session():
    pytest.importorskip("pandas")
    from wealthpilot.data import DATA_DIR
    if not (DATA_DIR / "prices_daily.csv").exists():
        pytest.skip("starter dataset not present")
    return tl.Session.from_starter()


def _fmt(x):
    return f"{100 * x:.1f}%"


@requires_starter
def test_full_flow_grounded_answer_passes(session):
    from wealthpilot import advocate, profile as pf, strategist
    rob = pf.build_profile(ROBERT)
    w = strategist.policy_allocation(rob, session.prices_cad).weights
    rv = advocate.review_trade("TSLA", 0.30, w, rob, session.prices_cad, session.universe)
    after = rv.before_after["after"]["max_drawdown"]
    llm = ScriptedLLM([
        [BUILD], [("propose_allocation", {})],
        f"Your profile caps stocks at {_fmt(rob.constraints.equity_max)} {{R?}}. "
        f"The proposed allocation keeps {_fmt(w['XBB.TO'])} in Canadian bonds {{R?}}.",
        [("review_trade", {"symbol": "TSLA", "weight": 0.3})],
        f"With 30% in TSLA the worst fall would have reached {_fmt(after)} {{R?}}. Is that acceptable?",
    ])
    ans = orch.ask(session, "Can I put 30% in Tesla?", llm, debate=False)
    assert ans.report.passed, ans.report.to_dict()
    assert ans.revisions == 0
    assert [r.tool for r in session.ledger.receipts] == ["build_profile", "propose_allocation", "review_trade"]
    assert "Devil's advocate" in ans.text and "Not financial advice" in ans.text
    assert {s.get("agent") for s in ans.trace} >= {"advisor", "advocate", "verifier"}
    assert llm.calls[-1]["tools"] == [t.name for t in tl.tools_for("advocate")]


@requires_starter
def test_unsupported_number_triggers_one_revision(session):
    llm = ScriptedLLM([
        [BUILD],
        "Robert's capacity score is 99.9 {R?}.",                       # wrong number
        "No major objection.",                                        # advocate
        "Robert's profile is moderately conservative {R?}.",          # revision without the bad figure
    ])
    ans = orch.ask(session, "What is my profile?", llm, debate=False)
    assert ans.revisions == 1 and ans.report.passed
    revision_msg = llm.calls[3]["messages"][-1]["content"]
    assert "99.9" in revision_msg and "not found" in revision_msg


@requires_starter
def test_remaining_problems_are_shown_not_hidden(session):
    llm = ScriptedLLM([
        "TSLA always returns 40% a year.", "TSLA always returns 40% a year.", "Nothing to add.",
    ])
    ans = orch.ask(session, "Tell me about TSLA", llm, debate=False)
    assert not ans.report.passed
    assert 'Not verified: "40%"' in ans.text


@requires_starter
def test_tool_errors_are_returned_to_the_model(session):
    rid, content, is_error = tl.call_tool(session, "advocate", "review_trade", {"symbol": "TSLA", "weight": 0.3})
    assert is_error and "build_profile" in content
    assert session.ledger.get(rid).error
    rid, content, is_error = tl.call_tool(session, "advocate", "build_profile", {})
    assert is_error and "not available" in content


@requires_starter
def test_debate_makes_the_advisor_answer_the_challenges(session):
    llm = ScriptedLLM([
        [BUILD],
        "Your profile is ready {R?}.",                                   # draft
        [("review_trade", {"symbol": "TSLA", "weight": 0.3})],
        "This request breaks the profile limits {R?}. Would you accept a smaller position?",  # advocate
        "Debate: the advocate's objection is accepted; the request is not compatible with the profile.",  # arbiter
    ])
    ans = orch.ask(session, "Can I put 30% in Tesla?", llm)
    assert "Debate" in ans.draft and "accepted" in ans.draft
    assert any(t.get("agent") == "arbiter" for t in ans.trace)
    assert "challenged your draft" in llm.calls[-1]["messages"][-1]["content"]


@requires_starter
def test_goal_plan_tool_and_risk_map(session):
    tl.call_tool(session, "advisor", *BUILD)
    goals = [{"name": "Cushion", "type": "emergency_fund", "horizon_years": 0, "target_amount": 15000,
              "current_amount": 15000, "monthly_contribution": 0},
             {"name": "Retirement", "type": "retirement", "horizon_years": 4, "target_amount": 300000,
              "current_amount": 135000, "monthly_contribution": 500}]
    rid, content, err = tl.call_tool(session, "advisor", "plan_goals", {"goals_list": goals})
    assert not err and session.portfolio
    out = session.ledger.get(rid).output
    assert out["goals"][0]["weights"] == {"ZST.TO": 1.0}
    rid, content, err = tl.call_tool(session, "advocate", "risk_map", {"weights": []})
    kinds = {r["kind"] for r in session.ledger.get(rid).output["risks"]}
    assert kinds == {"market", "credit", "liquidity", "currency", "concentration", "inflation"}
    rid, content, err = tl.call_tool(session, "advisor", "what_would_change", {"goals_list": goals})
    assert session.ledger.get(rid).output["conditions"]
