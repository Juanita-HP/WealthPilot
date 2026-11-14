"""Tools the agents can call. Each one wraps a tested module and returns a receipt.

The model never computes a number itself: it calls these tools, and every
result is stored in the ledger with an id it must cite.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from .. import advocate, data, lab, portfolio, strategist, ticker, time_machine
from .. import inflation as infl
from .. import profile as pf
from .ledger import Ledger, jsonable

MAX_TOOL_RESULT_CHARS = 12_000


@dataclass
class Session:
    """State shared by the agents during one conversation."""
    prices_cad: pd.DataFrame
    prices_local: pd.DataFrame
    universe: pd.DataFrame
    source: object                      # ticker data source (StarterSource or YFinanceSource)
    macro_history: pd.DataFrame | None = None
    inflation_artifact: dict | None = None
    profile: pf.InvestorProfile | None = None
    portfolio: dict[str, float] | None = None
    amount: float = 100_000.0
    ledger: Ledger = field(default_factory=lambda: Ledger(uuid.uuid4().hex[:12]))

    @classmethod
    def from_starter(cls, **kw) -> "Session":
        macro = None
        try:
            macro = pd.read_csv(data.EXTERNAL_DIR / "macro_history.csv", parse_dates=["date"])
        except FileNotFoundError:
            pass
        art = None
        try:
            art = infl.load()
        except FileNotFoundError:
            pass
        return cls(prices_cad=data.load_prices_cad(), prices_local=data.load_prices(),
                   universe=data.load_universe(), source=kw.pop("source", None) or ticker.StarterSource(),
                   macro_history=macro, inflation_artifact=art, **kw)

    @property
    def risk_free(self) -> float:
        return float(data.load_macro("V39079").iloc[-1]) / 100


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict
    func: Callable[..., object]
    agents: frozenset[str]  # which agents may call it

    def definition(self) -> dict:
        return {"name": self.name, "description": self.description, "strict": True,
                "input_schema": {**self.schema, "additionalProperties": False}}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required if required is not None else list(props)}


WEIGHTS = {"type": "array", "description": "Portfolio weights, summing to 1.",
           "items": _obj({"ticker": {"type": "string"}, "weight": {"type": "number"}}) | {"additionalProperties": False}}


def _weights(items: list[dict]) -> dict[str, float]:
    return {i["ticker"].upper(): float(i["weight"]) for i in items}


def _need_profile(s: Session):
    if s.profile is None:
        raise ValueError("No investor profile yet. Call build_profile first.")


# ----------------------------------------------------------------------------- tool functions


def t_build_profile(s: Session, answers: list[dict], esg: str, excluded_sectors: list[str], crypto: str,
                    region: str, themes: list[str], amount: float):
    s.profile = pf.build_profile({a["question"]: a["answer"] for a in answers},
                                 pf.Preferences(esg=esg, excluded_sectors=tuple(excluded_sectors), crypto=crypto,
                                                region=region, themes=tuple(themes)))
    s.amount = amount
    p = s.profile
    return {"level": p.level, "level_name": p.level_name, "capacity": p.capacity, "tolerance": p.tolerance,
            "experience": p.experience, "constraints": p.constraints.to_dict(), "expected_return_assumption": p.expected,
            "flags": [jsonable(f) for f in p.flags],
            "reasons": [jsonable(r) for r in p.reasons]}


def t_propose_allocation(s: Session):
    _need_profile(s)
    al = strategist.policy_allocation(s.profile, s.prices_cad)
    s.portfolio = al.weights
    checks = pf.check_allocation(al.weights, s.profile, s.universe, s.prices_cad)
    return {"weights": al.weights, "lines": [jsonable(ln) for ln in al.lines], "method": al.method,
            "notes": al.notes, "constraint_check": [jsonable(v) for v in checks],
            "currency_exposure": jsonable(portfolio_exposure(s, al.weights, "currency"))}


def portfolio_exposure(s: Session, w, by):
    from ..exposure import exposure
    return exposure(w, s.universe, by)


def t_replay(s: Session, weights: list[dict], amount: float):
    _need_profile(s)
    w = _weights(weights) if weights else s.portfolio
    cpi = data.load_macro_history("V41690973", point_in_time=False) if s.macro_history is not None else None
    r = time_machine.replay(w, s.prices_cad, s.profile, amount or s.amount, cpi_index=cpi)
    return r.to_dict(include_path=False)


def t_stress(s: Session, weights: list[dict], amount: float):
    w = _weights(weights) if weights else s.portfolio
    if not w:
        raise ValueError("No allocation to test.")
    return {"scenarios": [time_machine.shock(w, s.universe, amount or s.amount, k) for k in time_machine.SHOCKS],
            "inflation_erosion_10y": time_machine.inflation_erosion(amount or s.amount, 10)}


def t_compare(s: Session, portfolios: list[dict]):
    named = {p["name"]: _weights(p["weights"]) for p in portfolios}
    rf = data.risk_free_per_period(s.prices_cad.index)
    _, table = portfolio.compare(s.prices_cad, named, risk_free=rf, rebalance="quarterly", transaction_cost=0.001)
    return {"table": jsonable(table.reset_index().to_dict(orient="records")),
            "assumptions": "CAD, dividends reinvested, quarterly rebalancing, 0.1% transaction cost, BoC overnight rate as risk-free"}


def t_ticker(s: Session, symbol: str):
    o = ticker.overview(symbol, s.source, profile=s.profile, portfolio=s.portfolio, universe=s.universe,
                        prices_cad=s.prices_cad, risk_free_annual=s.risk_free)
    return o


def t_review_trade(s: Session, symbol: str, weight: float):
    _need_profile(s)
    if not s.portfolio:
        raise ValueError("No current portfolio. Call propose_allocation first or provide one.")
    return advocate.review_trade(symbol.upper(), weight, s.portfolio, s.profile, s.prices_cad, s.universe).to_dict()


def t_review_allocation(s: Session, weights: list[dict]):
    _need_profile(s)
    w = _weights(weights) if weights else s.portfolio
    return advocate.review_allocation(w, s.profile, s.prices_cad, s.universe, current=None).to_dict()


def t_lab(s: Session, symbol: str, strategy: str):
    res = lab.evaluate(s.prices_local[symbol.upper()], strategy, symbol.upper(), profile=s.profile,
                       risk_free_annual=s.risk_free)
    return {"result": res.to_dict(), "review": advocate.review_lab(res).to_dict()}


def t_inflation(s: Session, horizon_months: int):
    if s.macro_history is None or s.inflation_artifact is None:
        raise ValueError("Inflation model unavailable: run scripts/fetch_macro_history.py and scripts/train_inflation.py.")
    return infl.forecast(s.macro_history, s.inflation_artifact, horizon_months).to_dict()


def t_set_portfolio(s: Session, weights: list[dict]):
    w = _weights(weights)
    portfolio.validate_weights(w, s.prices_cad.columns)
    s.portfolio = w
    out = {"weights": w}
    if s.profile:
        out["constraint_check"] = [jsonable(v) for v in pf.check_allocation(w, s.profile, s.universe, s.prices_cad)]
    return out


QUESTION_IDS = [q.id for q in pf.QUESTIONS]

TOOLS = [
    Tool("build_profile",
         "Score the investor questionnaire (10 answers) and preferences into a risk level with constraints. "
         "Use the exact question ids and option codes. Returns capacity, tolerance, level, constraints, flags.",
         _obj({"answers": {"type": "array", "items": _obj({"question": {"type": "string", "enum": QUESTION_IDS},
                                                            "answer": {"type": "string"}}) | {"additionalProperties": False}},
               "esg": {"type": "string", "enum": ["none", "prefer", "exclude"]},
               "excluded_sectors": {"type": "array", "items": {"type": "string"}},
               "crypto": {"type": "string", "enum": ["no", "small", "open"]},
               "region": {"type": "string", "enum": list(pf.REGION_HOME_SHARE)},
               "themes": {"type": "array", "items": {"type": "string"}},
               "amount": {"type": "number", "description": "Fictional amount to invest, CAD."}}),
         t_build_profile, frozenset({"advisor"})),
    Tool("propose_allocation", "Build the policy allocation for the current profile, with a reason for every weight.",
         _obj({}), t_propose_allocation, frozenset({"advisor"})),
    Tool("set_portfolio", "Record the investor's existing (fictional) portfolio and check it against the profile.",
         _obj({"weights": WEIGHTS}), t_set_portfolio, frozenset({"advisor"})),
    Tool("replay_history",
         "Replay an allocation (empty list = current one) on 2021-2026 prices in the investor's dollars: worst fall, "
         "worst 12 months, calendar years, real value after inflation.",
         _obj({"weights": WEIGHTS, "amount": {"type": "number"}}), t_replay, frozenset({"advisor", "advocate"})),
    Tool("stress_test", "Apply labeled hypothetical shocks and inflation erosion to an allocation (empty list = current one).",
         _obj({"weights": WEIGHTS, "amount": {"type": "number"}}), t_stress, frozenset({"advisor", "advocate"})),
    Tool("compare_allocations", "Backtest several named allocations on the same dates and tabulate metrics.",
         _obj({"portfolios": {"type": "array", "items": _obj({"name": {"type": "string"}, "weights": WEIGHTS})
                              | {"additionalProperties": False}}}), t_compare, frozenset({"advisor", "advocate"})),
    Tool("ticker_overview",
         "Overview of one ticker: returns, risk, fundamentals, growth score and fit score for the current profile.",
         _obj({"symbol": {"type": "string"}}), t_ticker, frozenset({"advisor", "advocate"})),
    Tool("review_trade",
         "Devil's advocate review of putting a share of the portfolio in one ticker: constraint breaches, risk jump "
         "with honest counterpoint, recency bias, horizon mismatch.",
         _obj({"symbol": {"type": "string"}, "weight": {"type": "number", "description": "0 to 1"}}),
         t_review_trade, frozenset({"advocate", "advisor"})),
    Tool("review_allocation", "Devil's advocate review of an allocation (empty list = current one).",
         _obj({"weights": WEIGHTS}), t_review_allocation, frozenset({"advocate", "advisor"})),
    Tool("strategy_lab",
         "Test a trading rule on one ticker: optimized on 70% of history, tested on the rest, against buy-and-hold.",
         _obj({"symbol": {"type": "string"}, "strategy": {"type": "string", "enum": list(lab.STRATEGIES)}}),
         t_lab, frozenset({"advisor", "advocate"})),
    Tool("inflation_forecast",
         "Canadian CPI inflation forecast with 80% interval, using the method that won walk-forward tests.",
         _obj({"horizon_months": {"type": "integer", "enum": list(infl.HORIZONS)}}), t_inflation,
         frozenset({"advisor", "advocate"})),
]
TOOL_BY_NAME = {t.name: t for t in TOOLS}


def tools_for(agent: str) -> list[Tool]:
    return [t for t in TOOLS if agent in t.agents]


def call_tool(session: Session, agent: str, name: str, inputs: dict) -> tuple[str, str, bool]:
    """Run a tool, record a receipt, return (receipt_id, content_for_model, is_error)."""
    tool = TOOL_BY_NAME.get(name)
    if tool is None or agent not in tool.agents:
        r = session.ledger.record(name, agent, inputs, error=f"tool {name!r} not available to {agent}")
        return r.id, f"Error: tool {name!r} is not available to this agent.", True
    try:
        out = jsonable(tool.func(session, **inputs))
    except Exception as e:  # report the failure to the model instead of crashing the conversation
        r = session.ledger.record(name, agent, inputs, error=f"{type(e).__name__}: {e}")
        return r.id, f"Error [{r.id}]: {type(e).__name__}: {e}", True
    r = session.ledger.record(name, agent, inputs, out)
    text = json.dumps({"receipt": r.id, "result": out}, separators=(",", ":"))
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + f'... [truncated; full result stored in receipt {r.id}]'
    return r.id, text, False

