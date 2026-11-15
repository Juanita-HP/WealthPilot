"""HTTP API for the React interface (FastAPI).

Run:  uvicorn wealthpilot.api:app --port 8000      (or: python -m wealthpilot.api)

The React app (web/) calls these endpoints; when ``web/dist`` exists (``npm run build``), the API also serves it,
so one process runs the whole demo. Simulation only: fictional accounts and amounts, no real transactions, not
financial advice.

Every text returned here is plain English, ready to display. Numbers stay numbers; the interface formats them.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import accounts, advocate, data, forecast as fc, goals as gl, inflation as infl, lab, macro_news, news
from . import onboarding as ob
from . import profile as pf
from . import risks, strategist, ticker as tk, time_machine as tm, whatif
from .agents.ledger import jsonable

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = Path(os.environ.get("WEALTHPILOT_WEB_DIST", ROOT / "web" / "dist"))
TOKEN_DAYS = 7

app = FastAPI(title="WealthPilot API", version="1.0",
              description="Educational investment simulation. Not financial advice.")


# ----------------------------------------------------------------------------- data (loaded once)


@lru_cache(maxsize=1)
def market() -> dict:
    px_cad = data.load_prices_cad()
    px_local = data.load_prices()
    vol = risks.average_dollar_volume(data.load_prices("close"), data.load_prices("volume"))
    try:
        cpi = data.load_macro_history("V41690973", point_in_time=False)
    except FileNotFoundError:
        cpi = None
    return {"px_cad": px_cad, "px_local": px_local, "universe": data.load_universe(), "dollar_vol": vol, "cpi": cpi}


class TTLCache:
    """Small time-based cache for slow, network-bound results (news, live quotes)."""

    def __init__(self, seconds: float):
        self.seconds, self.store, self.lock = seconds, {}, threading.Lock()

    def get(self, key, compute):
        now = time.time()
        with self.lock:
            hit = self.store.get(key)
            if hit and now - hit[0] < self.seconds:
                return hit[1]
        value = compute()
        with self.lock:
            self.store[key] = (now, value)
        return value


NEWS_CACHE = TTLCache(3600)
INFLATION_CACHE = TTLCache(6 * 3600)


def inflation_card(h: int = 12) -> dict | None:
    """12-month Canadian inflation forecast: the method that tested best, and what the ML model (ridge) sees."""
    def compute():
        try:
            history = pd.read_csv(data.EXTERNAL_DIR / "macro_history.csv")
            artifact = infl.load()
            f = infl.forecast(history, artifact, h)
            ridge = infl.ridge_view(history, artifact, h)
        except (FileNotFoundError, KeyError, ValueError):
            return None
        used = "ridge" if f.method == "ridge" else f.method
        return {
            "horizon_months": h, "origin_month": f.origin_month, "available_from": f.available_from,
            "target_month": f.target_month, "current": f.current_yoy, "forecast": f.forecast, "low": f.low,
            "high": f.high, "method": used, "method_label": f.method_label, "mae": f.evaluation["mae"],
            "interval_coverage": f.evaluation["interval_coverage"], "note": f.note, "ml": ridge,
            "long_run_assumption": pf.assumptions.INFLATION, "target": infl.TARGET,
        }
    return INFLATION_CACHE.get(h, compute)
INSIGHT_CACHE = TTLCache(900)


def macro_items() -> list[dict]:
    def load():
        try:
            return macro_news.recent()
        except Exception:  # official news are optional context
            return []
    return NEWS_CACHE.get("macro", load)


def headlines(symbol: str) -> list[dict] | None:
    def load():
        try:
            return news.recent_headlines(symbol)
        except Exception:
            return None
    return NEWS_CACHE.get(("headlines", symbol), load)


# ----------------------------------------------------------------------------- authentication


def _secret() -> bytes:
    env = os.environ.get("WEALTHPILOT_SECRET")
    if env:
        return env.encode()
    path = Path(os.environ.get("WEALTHPILOT_USERS_DB", accounts.DB_PATH)).parent / ".token_secret"
    try:
        if path.exists():
            return path.read_bytes()
        path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        path.write_bytes(key)
        return key
    except OSError:  # read-only filesystem: tokens last as long as the process
        return _PROCESS_KEY


_PROCESS_KEY = secrets.token_bytes(32)


def make_token(username: str) -> str:
    payload = f"{username}|{int(time.time()) + TOKEN_DAYS * 86400}".encode()
    sig = hmac.new(_secret(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def read_token(token: str) -> str | None:
    try:
        p64, s64 = token.split(".", 1)
        payload, sig = base64.urlsafe_b64decode(p64), base64.urlsafe_b64decode(s64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, hmac.new(_secret(), payload, hashlib.sha256).digest()):
        return None
    user, exp = payload.decode().rsplit("|", 1)
    return user if int(exp) > time.time() else None


def current_user(authorization: str = Header(default="")) -> str:
    user = read_token(authorization.removeprefix("Bearer ").strip()) if authorization else None
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


class Credentials(BaseModel):
    username: str
    password: str


@app.post("/api/auth/signup")
def signup(c: Credentials):
    try:
        accounts.create_user(c.username, c.password)
    except accounts.AccountError as e:
        raise HTTPException(400, str(e))
    u = c.username.lower()
    return {"token": make_token(u), "username": u}


@app.post("/api/auth/login")
def login(c: Credentials):
    if not accounts.authenticate(c.username, c.password):
        raise HTTPException(401, "Incorrect username or password.")
    u = c.username.lower()
    return {"token": make_token(u), "username": u}


@app.get("/api/me")
def me(user: str = Depends(current_user)):
    return {"username": user, "has_profile": bool(accounts.load_profile(user))}


# ----------------------------------------------------------------------------- shared wording

GOAL_LABEL = {"emergency_fund": "Emergency fund", "home_purchase": "First home", "project": "Project (trip, car, studies)",
              "retirement": "Retirement", "income": "Regular income", "legacy": "Wealth to pass on"}
ACCOUNT_LABEL = {"emergency_fund": "TFSA or high-interest savings account", "home_purchase": "FHSA",
                 "project": "TFSA", "retirement": "RRSP, then TFSA", "income": "TFSA, then non-registered",
                 "legacy": "Non-registered or TFSA (see an estate planner)"}
LEVEL_FOR = {1: "short horizons, little comfort with swings, or money needed soon",
             2: "people near retirement or with medium horizons who put stability first",
             3: "medium to long horizons, balancing growth and stability",
             4: "long horizons and comfort with large temporary declines",
             5: "very long horizons, with high capacity AND high tolerance for risk"}
FLAG_TEXT = {
    "CAPACITY_TOLERANCE_GAP": "Your capacity and your tolerance for risk do not match: your level follows the lower one.",
    "EMERGENCY_FUND_SHORT": "Your emergency fund is below target: filling it comes before investing.",
    "SAVINGS_OVERCOMMITTED": "Your goals need more monthly savings than you can set aside.",
    "HIGH_DEBT": "Your debts are high compared with your income: paying them down is a guaranteed return.",
    "EXPECTATION_GAP": "The return you hope for is above prudent assumptions for your level.",
    "ESG_DATA_LIMIT": "ESG preferences are applied through exclusions and a screened fund; we have no ESG ratings.",
    "CRYPTO_NO_EXPERIENCE": "Crypto turned off: your profile shows no investment experience.",
    "CRYPTO_NOT_ALLOWED": "Your level allows no crypto: a preference never overrides a limit.",
    "LEVEL_LOWERED": "You chose a more cautious level than the one recommended.",
    "HORIZON_CAP": "Your horizon limits the level of risk.",
    "NO_EMERGENCY_FUND": "You have no emergency fund.",
    "GOAL_NOT_REACHABLE": "A goal is not reachable as it stands.",
}
RISK_LABEL = {"market": "Market", "credit": "Credit", "liquidity": "Liquidity", "currency": "Currency",
              "concentration": "Concentration", "inflation": "Inflation"}
FACTOR_LABEL = {"revenue_growth": "Revenue growth", "earnings_growth": "Earnings growth",
                "margin_trend": "Margin trend", "fcf_margin": "Free cash flow margin", "debt_to_equity": "Debt",
                "analyst_eps_growth": "Analyst forecasts (opinion)", "volatility": "Price swings",
                "max_drawdown": "Worst fall vs accepted loss", "recovery_vs_horizon": "Recovery time vs horizon",
                "preferences": "Your preferences", "portfolio_impact": "Effect on your portfolio"}
CHALLENGE_TITLE = {"SINGLE_SECURITY": "Too large for a single stock", "EQUITY_ABOVE_RANGE": "Too much in stocks for your level",
                   "SECTOR": "Too concentrated in one sector", "RISK_CONCENTRATION": "One holding carries most of the risk",
                   "CRYPTO_ABOVE_LIMIT": "Too much crypto for your level", "EXCLUDED_SECTOR": "Against your values",
                   "RISK_JUMP": "Risk rises sharply", "HORIZON_MISMATCH": "Too slow to recover for your horizon",
                   "RECENCY_BIAS": "Recency bias", "HIDDEN_CONCENTRATION": "Less diversified than it looks",
                   "HOME_BIAS": "Home bias", "HYPE": "Lots of media noise",
                   "NEWS_EXPOSURE": "Dependence on a topic in the news",
                   "RECENT_NEWS": "Recent news: read with a grain of salt",
                   "ESG_CONTROVERSY": "ESG or controversy signal in recent news",
                   "GOLD_ABOVE_LIMIT": "Too much gold",
                   "EQUITY_BELOW_RANGE": "Few stocks for your level"}
VERDICT = {"reconsider": ("red", "Reconsider"), "proceed with care": ("yellow", "Proceed with care"),
           "no major objection": ("green", "No major objection")}
STRATEGY_LABEL = {"ma_crossover": "Moving-average crossover", "rsi": "RSI (buy the dips)", "bollinger": "Bollinger bands",
                  "macd": "MACD (momentum)", "breakout": "Breakout to new highs"}
ESG = {"none": "No preference", "prefer": "I prefer responsible investments", "exclude": "I require responsible investments"}
CRYPTO = {"no": "No", "small": "A little", "open": "Yes, if my profile allows it"}
REGION = {"canada": "Mostly Canada", "balanced": "Balanced", "us": "Mostly the U.S.", "global": "Global (the whole world)"}
RANGES = {"A": (0.04, -0.02), "B": (0.08, -0.08), "C": (0.14, -0.18), "D": (0.22, -0.32)}


def pct(x: float | None, digits: int = 0) -> str:
    return "—" if x is None else f"{x * 100:.{digits}f}%"


def money(x: float) -> str:
    return f"${x:,.0f}"


def level_name(level: int) -> str:
    return pf.level_card(level)["name"]


def goal_level_text(g) -> str:
    return "Cash" if g.level_name == "Cash reserve" else level_name(g.level)


def risk_text(r) -> str:
    v = r.value
    return {
        "market": f"This mix has moved about {pct(v)} a year; holdings can fall together.",
        "credit": f"{pct(v)} in bond funds, mostly government and high-quality issuers.",
        "liquidity": f"{pct(v)} in thinly traded assets or crypto.",
        "currency": f"{pct(v)} in U.S. dollars: its value in CAD moves with the exchange rate.",
        "concentration": (f"The largest single holding carries {pct(v)} of the risk." if v > 0 else
                          "No single company dominates: risk is spread across broad funds."),
        "inflation": f"Assumed real return of about {pct(v, 1)} a year after inflation (assumption).",
    }.get(r.kind, r.reason)


def forecast_for(symbol: str) -> dict | None:
    """Tested return forecast (crypto, gold) from models/asset_forecast.json, if trained."""
    art = fc.load_artifact()
    if not art or symbol not in art.get("assets", {}):
        return None
    a = art["assets"][symbol]
    return None if "error" in a else {**a, "trained_on": art["trained_on"], "rating_scale": art["rating_scale"]}


# Funds have no statements to measure: their gauge places the planning assumption of their market between the
# lowest and the highest assumptions of the FP Canada / IFP guidelines.
LOW_R, HIGH_R = pf.assumptions.RETURNS["short_term"], pf.assumptions.RETURNS["emerging_equity"]


def assumption_score(annual_return: float) -> float:
    return round(100 * min(1.0, max(0.0, (annual_return - LOW_R) / (HIGH_R - LOW_R))), 1)


def fit_sentence(fit: dict, risk: dict) -> str:
    if fit["label"] == "Not suitable":
        return fit["notes"][0] if fit["notes"] else "This investment conflicts with your preferences or limits."
    scored = [f for f in fit["factors"] if f["score"] is not None]
    worst = min(scored, key=lambda f: f["score"]) if scored else None
    if worst is None or worst["score"] >= 0.6:
        return "Its past behaviour stays within the limits of your profile."
    mdd = risk["max_drawdown"]["value"]
    return {
        "volatility": "Its price swings far more than your profile accepts for a single holding.",
        "max_drawdown": f"Its worst fall ({pct(mdd)}) is well beyond the loss you accept in a bad year.",
        "recovery_vs_horizon": "It took a long time to recover from its worst fall, compared with your horizon.",
        "preferences": "It goes against your preferences.",
        "portfolio_impact": "Adding it would unbalance your current portfolio.",
    }.get(worst["name"], "One of your profile's criteria is not met.")


def potential_sentence(pot: dict) -> str:
    scored = [f for f in pot["factors"] if f["score"] is not None]
    if not scored:
        return ""
    best, worst = max(scored, key=lambda f: f["score"]), min(scored, key=lambda f: f["score"])
    out = []
    if best["score"] >= 0.6:
        out.append(f"Strength: {FACTOR_LABEL.get(best['name'], best['name']).lower()}.")
    if worst["score"] < 0.5:
        out.append(f"Weakness: {FACTOR_LABEL.get(worst['name'], worst['name']).lower()}.")
    return " ".join(out) or "No factor stands out."


# ----------------------------------------------------------------------------- onboarding


@app.get("/api/meta")
def meta():
    """Everything the onboarding form needs: options, labels, personas."""
    q = pf.QUESTION_BY_ID
    return {
        "employment": [{"value": k, "label": v[1]} for k, v in ob.EMPLOYMENT.items()],
        "provinces": ob.PROVINCES,
        "goal_types": [{"value": k, "label": v} for k, v in GOAL_LABEL.items()],
        "questions": {qid: {"text": q[qid].text, "options": [{"value": o.code, "label": o.label} for o in q[qid].options]}
                      for qid in ("drop_reaction", "range_choice", "goal", "experience", "return_expectation")},
        "ranges": RANGES,
        "themes": [{"value": k, "label": v[0], "tickers": v[1]} for k, v in strategist.THEMES.items()],
        "esg": [{"value": k, "label": v} for k, v in ESG.items()],
        "crypto": [{"value": k, "label": v} for k, v in CRYPTO.items()],
        "region": [{"value": k, "label": v} for k, v in REGION.items()],
        "personas": {name: o.to_dict() for name, o in ob.PERSONAS.items()},
        "blank": blank_draft(),
    }


def blank_draft() -> dict:
    fin = ob.Financials(age=30, province="QC", employment="salaried", annual_income=70_000.0, monthly_expenses=3_000.0,
                        monthly_savings=500.0, cash_savings=10_000.0, investments=20_000.0, other_assets=0.0,
                        debts=0.0, dependents=0)
    return {"financials": asdict(fin), "goals": [asdict(g) for g in ob.suggested_goals(fin)],
            "tolerance": {"drop_reaction": "hold", "range_choice": "B", "goal": "balanced", "experience": "beginner",
                          "return_expectation": "5to7"},
            "preferences": asdict(pf.Preferences())}


def to_onboarding(d: dict) -> ob.Onboarding:
    try:
        return ob.Onboarding.from_dict(d)
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"Incomplete or invalid profile: {e}")


def profile_summary(p: pf.InvestorProfile, all_flags: bool = False) -> dict:
    card = pf.level_card(p.level)
    return {"level": p.level, "name": card["name"], "score_10": card["score_10"], "suits": LEVEL_FOR[p.level],
            "capacity": p.capacity, "tolerance": p.tolerance, "experience": p.experience,
            "flags": [{"code": f.code, "severity": f.severity, "text": FLAG_TEXT.get(f.code, f.message), "detail": f.message}
                      for f in p.flags if all_flags or f.severity == "warning"],
            "capacity_reasons": [{"label": r.label, "points": r.contribution} for r in p.reasons
                                 if r.dimension == "capacity"]}


class Draft(BaseModel):
    onboarding: dict


@app.post("/api/onboarding/preview")
def preview(d: Draft, user: str = Depends(current_user)):
    o = to_onboarding(d.onboarding)
    fin = o.financials
    out = {"financials": fin.to_dict(), "suggested_goals": [asdict(g) for g in ob.suggested_goals(fin)]}
    if o.goals:
        p = ob.build_profile(o)
        plan = gl.plan(p, o.goals, market()["px_cad"])
        out["profile"] = profile_summary(p)
        out["goals"] = [{"name": g.goal.name, "level": goal_level_text(g)} for g in plan.goals]
    return out


@app.get("/api/profile")
def get_profile(user: str = Depends(current_user)):
    saved = accounts.load_profile(user)
    if not saved:
        raise HTTPException(404, "No profile yet.")
    o = to_onboarding(saved)
    p = ob.build_profile(o)
    chosen = int(saved.get("chosen_level", p.level))
    return {"onboarding": o.to_dict(), "chosen_level": min(chosen, p.level), "profile": profile_summary(p, all_flags=True),
            "financials": o.financials.to_dict(),
            "levels": [{"level": n, "name": level_name(n)} for n in range(1, p.level + 1)]}


@app.put("/api/profile")
def put_profile(d: Draft, user: str = Depends(current_user)):
    o = to_onboarding(d.onboarding)
    if not o.goals:
        raise HTTPException(400, "Choose at least one goal.")
    accounts.save_profile(user, o.to_dict())
    return {"saved": True}


@app.delete("/api/profile")
def delete_profile(user: str = Depends(current_user)):
    accounts.delete_profile(user)
    return {"deleted": True}


class Level(BaseModel):
    level: int


@app.put("/api/profile/level")
def set_level(lv: Level, user: str = Depends(current_user)):
    saved = accounts.load_profile(user)
    if not saved:
        raise HTTPException(404, "No profile yet.")
    accounts.save_profile(user, {**saved, "chosen_level": int(lv.level)})
    return {"chosen_level": int(lv.level)}


def user_state(user: str) -> dict:
    """Profile, plan and the portfolio a new request must respect, for one signed-in user."""
    saved = accounts.load_profile(user)
    if not saved:
        raise HTTPException(409, "Create your profile first.")
    o = to_onboarding(saved)
    base = ob.build_profile(o)
    profile = base
    chosen = int(saved.get("chosen_level", base.level))
    if chosen < base.level:
        profile, _ = pf.choose_level(base, chosen)
    plan = gl.plan(profile, o.goals, market()["px_cad"])
    return {"onboarding": o, "base": base, "profile": profile, "plan": plan,
            "effective": gl.effective_profile(profile, plan), "weights": plan.total_weights}


# ----------------------------------------------------------------------------- plan


@app.get("/api/plan")
def plan(user: str = Depends(current_user)):
    st, m = user_state(user), market()
    u, profile, p = m["universe"], st["profile"], st["plan"]
    checks = gl.check_plan(profile, p, u, m["px_cad"])
    goals = []
    for g in p.goals:
        ga = g.goal_analysis
        if ga.get("kind") == "cushion":
            status = (("green", "Fund complete.") if ga["reachable"] else
                      ("yellow", f"{money(ga['gap'])} short, about {ga['months_to_fill']:.0f} months at the current pace.")
                      if ga["months_to_fill"] else ("yellow", f"{money(ga['gap'])} short. Plan a monthly amount."))
        elif ga["reachable"]:
            status = ("green", "On track under our assumptions.")
        else:
            need = ga.get("monthly_contribution_needed")
            status = ("yellow", "Not reachable as it stands" + (f": you would need about {money(need)} a month." if need else "."))
        goals.append({
            "name": g.goal.name, "type": g.goal.type, "level": g.level, "level_text": goal_level_text(g),
            "horizon": "immediate" if g.goal.horizon_years == 0 else f"{g.goal.horizon_years:g} years",
            "target": g.goal.target_amount, "current": g.goal.current_amount,
            "holdings": [{"ticker": t, "name": u.loc[t, "name"] if t in u.index else t, "weight": w}
                         for t, w in sorted(g.weights.items(), key=lambda x: -x[1])],
            "status": {"tone": status[0], "text": status[1]},
            "warnings": [v.message for v in checks[g.goal.name] if v.severity == "warning"],
            "account": ACCOUNT_LABEL.get(g.goal.type, g.account),
            "why_level": g.why_level,
            "reasons": g.reasons,
            "assumption": None if ga.get("kind") == "cushion" else
            f"Required return {pct(ga['required_return'], 1)} a year; assumption {pct(ga['assumed_return'], 1)} a year "
            f"({pf.assumptions.SOURCE['name']}).",
            "what_if": [{"condition": c.condition, "effect": c.effect} for c in whatif.goal_conditions(profile, g.goal)],
        })
    rm = risks.risk_map(st["weights"], u, m["px_cad"], m["dollar_vol"], expected_nominal=profile.expected["net"])
    card = pf.level_card(profile.level)
    fin = st["onboarding"].financials
    from . import timing
    entry = timing.entry_summary(st["weights"], p.total_amount)
    if entry:
        entry["experience"] = profile.experience
    return {"inflation": inflation_card(12), "entry": jsonable(entry),
            "level": profile.level, "name": card["name"], "score_10": card["score_10"], "total": p.total_amount,
            "available": fin.cash_savings + fin.investments,
            "goals": goals, "notes": p.notes,
            "risks": [{"kind": r.kind, "label": RISK_LABEL[r.kind], "level": r.level, "text": risk_text(r),
                       "metric": r.metric, "value": r.value, "reason": r.reason} for r in rm],
            "combined": [{"ticker": t, "name": u.loc[t, "name"] if t in u.index else t, "weight": w}
                         for t, w in sorted(st["weights"].items(), key=lambda x: -x[1])]}


@app.get("/api/news/portfolio")
def portfolio_news(user: str = Depends(current_user)):
    st, m = user_state(user), market()
    items = macro_items()
    if not items:
        return {"items": [], "notes": ["Official releases are unavailable right now (Bank of Canada, Federal Reserve, "
                                       "Statistics Canada)."], "sources": [], "rule": ""}
    out = macro_news.impact(st["weights"], m["universe"], items, m["px_cad"], amount=st["plan"].total_amount, top=5)
    u = m["universe"]
    for it in out["items"]:
        if it["analog"]:
            for r in it["analog"]["rows"]:
                r["name"] = u.loc[r["ticker"], "name"] if r["ticker"] in u.index else r["ticker"]
    return jsonable(out)


# ----------------------------------------------------------------------------- stocks


def _overview(symbol: str, eff, weights) -> tuple[dict, bool, str | None]:
    m = market()
    source = tk.auto_source()
    live = isinstance(source, tk.YFinanceSource)
    note = None
    try:
        ov = tk.overview(symbol, source, profile=eff, portfolio=weights, universe=m["universe"], prices_cad=m["px_cad"])
    except Exception as e:
        if not live or symbol not in m["universe"].index:
            raise HTTPException(404, f"No data for {symbol}.")
        note = f"Live data unavailable ({type(e).__name__}); offline data used."
        source, live = tk.StarterSource(), False
        ov = tk.overview(symbol, source, profile=eff, portfolio=weights, universe=m["universe"], prices_cad=m["px_cad"])
    return ov, live, note


@app.get("/api/stocks/{symbol}/insights")
def insights(symbol: str, user: str = Depends(current_user)):
    symbol = symbol.strip().upper()
    st = user_state(user)

    model = forecast_for(symbol)

    def compute():
        ov, live, note = _overview(symbol, st["effective"], st["weights"])
        fit, pot, lra = ov["fit_score"], ov["potential_score"], ov["long_run_assumption"]
        if pot["score"] is not None:
            pot_text = potential_sentence(pot)
        elif lra:
            pot_text = (f"Diversified fund: its potential is its market's. Long-run assumption "
                        f"{pct(lra['annual_return'], 1)} a year ({lra['source']}), not a forecast. The needle places it "
                        f"between the lowest assumption ({pct(LOW_R, 1)}, short-term deposits) and the highest "
                        f"({pct(HIGH_R, 1)}, emerging-market stocks).")
        elif pot["label"] == "Not applicable" and model:
            m = model["models"]["gradient_boosting"]
            pot_text = (f"No financial statements and no recognized planning assumption, so a model was tested instead: "
                        f"its R² against the historical average is {pct(m['r2_oos'], 1)} ({m['rating']['label'].lower()}). "
                        + ("It passes the test, so the needle uses its forecast." if model["usable"] else
                           "It does not do reliably better than the average, so the gauge stays unscored."))
        elif pot["label"] == "Not applicable":
            pot_text = "Not assessable: no financial statements and no recognized assumption for this asset."
        else:
            pot_text = "Not enough data to measure the company's growth." + ("" if live else " Install yfinance for statements.")
        vol = ov["risk"]["volatility_full"]["value"]
        return {
            "symbol": symbol, "name": ov["identity"]["name"], "live": live, "note": note,
            "fit": {**fit, "sentence": fit_sentence(fit, ov["risk"]),
                    "zones": [{"from": 0, "to": 40, "tone": "red"}, {"from": 40, "to": 70, "tone": "yellow"},
                              {"from": 70, "to": 100, "tone": "green"}]},
            "potential": {**pot, "sentence": pot_text, "long_run_assumption": lra,
                          "assumption_score": assumption_score(lra["annual_return"]) if lra else
                          (assumption_score(model["forecast"]["annualized"]) if model and model["usable"] else None),
                          "model": model,
                          "zones": [{"from": 0, "to": 45, "tone": "red"}, {"from": 45, "to": 70, "tone": "yellow"},
                                    {"from": 70, "to": 100, "tone": "green"}]},
            "factor_labels": FACTOR_LABEL,
            "stats": {"return_1y": ov["returns"]["1Y"]["value"], "max_drawdown": ov["risk"]["max_drawdown"]["value"],
                      "volatility": vol,
                      "swings": "large" if vol and vol > 0.35 else "medium" if vol and vol > 0.18 else "small"},
            "returns": ov["returns"], "risk": ov["risk"], "fundamentals": ov["fundamentals"],
            "analyst_upside": ov["fundamentals"]["analyst_target_upside"]["value"],
            "data": ov["data"], "identity": ov["identity"],
        }
    return jsonable(INSIGHT_CACHE.get((user, symbol), compute))


@app.get("/api/stocks/{symbol}/news")
def stock_news(symbol: str, user: str = Depends(current_user)):
    symbol = symbol.strip().upper()
    hs = headlines(symbol)
    if hs is None:
        return {"available": False, "note": "News unavailable right now (Yahoo Finance connection)."}
    dg = news.digest(symbol, hs).to_dict()
    texts = NEWS_CACHE.get(("texts", symbol), lambda: news.read_texts([h for h in hs if news.is_relevant(h)]))
    return {"available": True, "digest": dg, "texts_note": texts["note"],
            "quotes": [q for r in texts["rows"] if r["status"] == "ok" for q in r.get("quotes", [])][:4]}


YAHOO_HOSTS = {"q1": "https://query1.finance.yahoo.com", "q2": "https://query2.finance.yahoo.com"}
YAHOO_PATHS = ("v8/finance/chart/", "v1/finance/search", "v7/finance/quote", "ws/fundamentals-timeseries/")
YAHOO_CACHE = TTLCache(30)


@app.get("/api/yahoo/{host}/{path:path}")
def yahoo(host: str, path: str, request: Request):
    """Server-side relay for the market-data calls of the stock page (browsers cannot call Yahoo directly: CORS)."""
    if host not in YAHOO_HOSTS or not path.startswith(YAHOO_PATHS):
        raise HTTPException(404, "Not a relayed endpoint.")
    url = f"{YAHOO_HOSTS[host]}/{path}"
    if request.url.query:
        url += "?" + request.url.query

    def fetch():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() or b"{}"
        except Exception as e:
            return 502, json.dumps({"error": type(e).__name__}).encode()
    status, body = YAHOO_CACHE.get(url, fetch)
    return Response(body, status_code=status, media_type="application/json")


# ----------------------------------------------------------------------------- time machine, advocate, lab


@app.get("/api/time-machine")
def time_machine(user: str = Depends(current_user)):
    st, m = user_state(user), market()
    amount = float(max(st["plan"].total_amount, 1000))
    r = tm.replay(st["weights"], m["px_cad"], st["effective"], amount, cpi_index=m["cpi"])
    path = r.path.resample("W-FRI").last().dropna(how="all")
    d = r.worst_drawdown
    shocks = [tm.shock(st["weights"], m["universe"], amount, k) for k in tm.SHOCKS]
    return jsonable({
        "amount": amount, "start": r.start, "end": r.end,
        "dates": [str(x.date()) for x in path.index], "value": path["value"].round(2).tolist(),
        "value_real": path["value_real"].round(2).tolist() if "value_real" in path else None,
        "worst": d, "worst_12_months": r.worst_12_months, "final_value": r.final_value,
        "final_value_real": r.final_value_real, "cagr": r.cagr,
        "summary": f"At the worst moment ({d['trough_date']}), your {money(amount)} would have been worth "
                   f"{money(d['trough_value'])}, {money(d['dollars_lost'])} less than at the previous peak.",
        "shocks": [{"label": s["label"], "return": s["portfolio_return"], "dollars": s["dollars"], "basis": s["basis"]}
                   for s in shocks],
    })


class TradeRequest(BaseModel):
    symbol: str
    weight: float


@app.get("/api/universe")
def universe():
    u = market()["universe"]
    return [{"ticker": t, "name": u.loc[t, "name"], "asset_class": u.loc[t, "asset_class"]} for t in sorted(u.index)]


@app.post("/api/advocate")
def devils_advocate(req: TradeRequest, user: str = Depends(current_user)):
    st, m = user_state(user), market()
    sym = req.symbol.upper()
    if sym not in m["universe"].index:
        raise HTTPException(404, f"{sym} is not in the simulation universe.")
    hs = headlines(sym)
    dg = news.digest(sym, hs).to_dict() if hs else None
    rv = advocate.review_trade(sym, max(0.01, min(req.weight, 0.9)), st["weights"], st["effective"], m["px_cad"],
                               m["universe"], news_digest=dg, macro_items=macro_items())
    tone, title = VERDICT[rv.verdict]
    return jsonable({"verdict": {"tone": tone, "text": title},
                     "challenges": [{"code": c.code, "title": CHALLENGE_TITLE.get(c.code, c.bias), "severity": c.severity,
                                     "claim": c.claim, "counterpoint": c.counterpoint, "question": c.question}
                                    for c in rv.challenges],
                     "before_after": rv.before_after})


class LabRequest(BaseModel):
    symbol: str
    strategy: str


@app.get("/api/lab/strategies")
def strategies():
    return [{"value": k, "label": v, "description": lab.STRATEGIES[k].description} for k, v in STRATEGY_LABEL.items()]


@app.post("/api/lab")
def strategy_lab(req: LabRequest, user: str = Depends(current_user)):
    st, m = user_state(user), market()
    sym = req.symbol.upper()
    if sym not in m["px_local"].columns or req.strategy not in STRATEGY_LABEL:
        raise HTTPException(404, "Unknown symbol or rule.")
    res = lab.evaluate(m["px_local"][sym], req.strategy, sym, profile=st["profile"], risk_free_annual=0.025)
    so, bo = res.out_of_sample, res.buy_hold_out_of_sample
    keys = ["total_return", "cagr", "volatility", "sharpe", "max_drawdown", "trades", "costs_paid"]
    return jsonable({
        "split_date": res.split_date, "rule": so["total_return"], "hold": bo["total_return"],
        "better": so["total_return"] > bo["total_return"],
        "table": [{"metric": k, "rule_in": res.in_sample.get(k), "hold_in": res.buy_hold_in_sample.get(k),
                   "rule_out": so.get(k), "hold_out": bo.get(k)} for k in keys],
        "findings": [f["message"] for f in res.findings], "params": res.params,
        "combinations": res.combinations_tested, "description": res.description,
    })


class Question(BaseModel):
    question: str


@app.post("/api/ask")
def ask(q: Question, user: str = Depends(current_user)):
    if not (os.environ.get("WEALTHPILOT_LLM") or os.environ.get("ANTHROPIC_API_KEY")):
        raise HTTPException(503, "Agents are not connected in this local demo. Set WEALTHPILOT_LLM=bedrock (AWS) or "
                                 "WEALTHPILOT_LLM=anthropic to ask questions in free text.")
    from .agents import Session, ask as run
    from .agents.llm import from_env
    st = user_state(user)
    sess = Session.from_starter()
    sess.profile, sess.portfolio, sess.amount = st["effective"], st["weights"], st["plan"].total_amount
    ans = run(sess, q.question, from_env())
    return jsonable({"text": ans.text, "receipts": [x.to_dict() for x in sess.ledger.receipts]})


# ----------------------------------------------------------------------------- errors and the built interface


@app.exception_handler(FileNotFoundError)
def missing_data(request: Request, exc: FileNotFoundError):
    return JSONResponse({"detail": f"Starter data missing: {exc}. Copy the organizers' CSV files into data/starter/."},
                        status_code=500)


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    """Serve the built React app; unknown paths fall back to index.html (client-side routes)."""
    if path.startswith("api/"):
        raise HTTPException(404, "Unknown endpoint.")
    if not WEB_DIST.exists():
        return JSONResponse({"detail": "Interface not built. Run: cd web && npm install && npm run build "
                                       "(or npm run dev for development)."}, status_code=404)
    target = (WEB_DIST / path).resolve()
    if path and target.is_file() and WEB_DIST.resolve() in target.parents:
        return FileResponse(target)
    return FileResponse(WEB_DIST / "index.html")


def main() -> None:
    import uvicorn
    uvicorn.run("wealthpilot.api:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    main()
