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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import accounts, advocate, coverage as cov, data, forecast as fc, goals as gl, inflation as infl, lab, macro_news, news
from . import onboarding as ob
from . import profile as pf
from . import markets as mk, risks, strategist, ticker as tk, time_machine as tm, whatif
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
    close, volume = data.load_prices("close"), data.load_prices("volume")
    vol = risks.average_dollar_volume(close, volume)
    try:
        cpi = data.load_macro_history("V41690973", point_in_time=False)
    except FileNotFoundError:
        cpi = None
    return {"px_cad": px_cad, "px_local": px_local, "universe": data.load_universe(), "dollar_vol": vol, "cpi": cpi,
            "close": close, "volume": volume, "fx": data.load_fx()}


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
    if os.environ.get("WEALTHPILOT_USERS_TABLE"):  # hosted: one key shared by every Lambda container
        if not _SHARED_KEY:
            _SHARED_KEY.append(accounts.token_secret())
        return _SHARED_KEY[0]
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
_SHARED_KEY: list[bytes] = []


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


def _clear_user_cache(user: str) -> None:
    with INSIGHT_CACHE.lock:
        for k in [k for k in INSIGHT_CACHE.store if isinstance(k, tuple) and k and k[0] == user]:
            INSIGHT_CACHE.store.pop(k, None)


def _match_persona(persona: str) -> tuple[str, ob.Onboarding]:
    target = persona.strip().lower()
    for name, o in ob.PERSONAS.items():
        if name.lower() == target:
            return name, o
    raise HTTPException(404, f"Unknown persona {persona!r}. Choose from: {', '.join(ob.PERSONAS)}.")


@app.post("/api/auth/demo/{persona}")
def demo_login(persona: str):
    """1-click demo persona sign-in: creates/updates the demo account, saves the persona profile, and signs in."""
    name, o = _match_persona(persona)
    u = f"demo_{name.lower()}"
    try:
        accounts.create_user(u, "wealthpilot-demo-2026")
    except accounts.AccountError:
        pass
    accounts.save_profile(u, {**o.to_dict(), "persona": name})
    _clear_user_cache(u)
    return {"token": make_token(u), "username": u, "persona": name}


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
                   "ALREADY_OWNED": "You already own it through your index funds",
                   "GOLD_ABOVE_LIMIT": "Too much gold",
                   "EQUITY_BELOW_RANGE": "Few stocks for your level",
                   "LIQUIDITY": "Could be hard to sell quickly at a fair price",
                   "LEVERAGED_FUND": "Leveraged or inverse fund"}
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
    return {"onboarding": o.to_dict(), "persona": saved.get("persona"),
            "chosen_level": min(chosen, p.level), "profile": profile_summary(p, all_flags=True),
            "financials": o.financials.to_dict(),
            "levels": [{"level": n, "name": level_name(n)} for n in range(1, p.level + 1)]}


@app.put("/api/profile")
def put_profile(d: Draft, user: str = Depends(current_user)):
    o = to_onboarding(d.onboarding)
    if not o.goals:
        raise HTTPException(400, "Choose at least one goal.")
    persona = d.onboarding.get("_persona") or None
    payload = {**o.to_dict(), **({"persona": persona} if persona in ob.PERSONAS else {})}
    accounts.save_profile(user, payload)
    _clear_user_cache(user)
    return {"saved": True}


@app.post("/api/profile/persona/{persona}")
def apply_persona(persona: str, user: str = Depends(current_user)):
    """1-click persona switcher for a signed-in user (Amira, Mateo, Robert)."""
    name, o = _match_persona(persona)
    accounts.save_profile(user, {**o.to_dict(), "persona": name})
    _clear_user_cache(user)
    return {"saved": True, "persona": name}


@app.delete("/api/profile")
def delete_profile(user: str = Depends(current_user)):
    accounts.delete_profile(user)
    _clear_user_cache(user)
    return {"deleted": True}


class Level(BaseModel):
    level: int


@app.put("/api/profile/level")
def set_level(lv: Level, user: str = Depends(current_user)):
    saved = accounts.load_profile(user)
    if not saved:
        raise HTTPException(404, "No profile yet.")
    accounts.save_profile(user, {**saved, "chosen_level": int(lv.level)})
    _clear_user_cache(user)
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


MARKETS_CACHE = TTLCache(300)


@app.get("/api/markets/overview")
def markets_overview():
    """Popular investments and today's biggest moves, each with its latest trading day's chart (5 minutes cached)."""
    return MARKETS_CACHE.get("overview", mk.overview)


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
        "vs_inflation": holdings_vs_inflation(st["weights"], m, r),
    })


# Role of each building block in the plan, and the planning assumption it maps to (FP Canada / IFP 2026).
BLOCK_ROLE = {"canadian_equity": ("Growth", "canadian_equity"), "us_equity": ("Growth", "us_equity"),
              "us_equity_esg": ("Growth", "us_equity"), "us_growth": ("Growth", "us_equity"),
              "intl_equity": ("Growth", "international_equity"), "em_equity": ("Growth", "emerging_equity"),
              "canadian_bonds": ("Stability", "fixed_income"), "us_bonds": ("Stability", "fixed_income"),
              "cash": ("Cash reserve", "short_term"), "gold": ("Diversifier", None), "crypto": ("Diversifier", None)}


def _role(ticker: str) -> tuple[str, float | None]:
    """(role, expected return per year after inflation from the planning guidelines, or None)."""
    block = next((b for b, t in strategist.BLOCKS.items() if t == ticker), None)
    if block is None:
        return "Single stock (theme)", None
    role, key = BLOCK_ROLE[block]
    if key is None:
        return role, None
    nominal = pf.assumptions.RETURNS[key]
    return role, (1 + nominal) / (1 + pf.assumptions.INFLATION) - 1


def _yield_context(start, end) -> dict | None:
    """Canada 10-year bond yield at the start and end of the window: the starting yield drives bond returns."""
    try:
        y = data.load_macro_history("BD.CDN.10YR.DQ.YLD", point_in_time=False).dropna()
    except (FileNotFoundError, KeyError):
        return None
    at = lambda d: float(y.loc[:d].iloc[-1]) if len(y.loc[:d]) else None  # noqa: E731
    latest = y.index[-1]
    return {"start": at(start), "end": at(end), "latest": float(y.iloc[-1]), "latest_date": str(latest.date()),
            "max": float(y.loc[start:end].max()), "source": "Bank of Canada, 10-year benchmark bond yield"}


def holdings_vs_inflation(weights: dict[str, float], m: dict, r) -> dict | None:
    """Each holding of the plan and the plan itself, as growth of 100, next to the cost of living (CPI)."""
    if m["cpi"] is None:
        return None
    idx = r.path.index
    cpi = tm.deflator(m["cpi"], idx)
    weekly = lambda s: s.resample("W-FRI").last().dropna()  # noqa: E731
    years = (idx[-1] - idx[0]).days / 365.25
    infl_total = float(cpi.iloc[-1] - 1)
    infl_annual = (1 + infl_total) ** (1 / years) - 1

    def row(label, ticker, weight, s):
        s = s.dropna()
        total = float(s.iloc[-1] / s.iloc[0] - 1)
        annual = (1 + total) ** (1 / years) - 1
        real = (1 + annual) / (1 + infl_annual) - 1
        role, expected_real = _role(ticker) if ticker else ("Whole plan", None)
        return {"ticker": ticker, "name": label, "weight": weight, "total_return": total, "annual_return": annual,
                "real_annual_return": real, "beats_inflation": real > 0, "role": role,
                "expected_real_return": expected_real,
                "growth": (weekly(s / s.iloc[0]) * 100).round(2).tolist()}
    u = m["universe"]
    holdings = [row(u.loc[t, "name"], t, w, m["px_cad"][t].reindex(idx).ffill())
                for t, w in sorted(weights.items(), key=lambda kv: -kv[1]) if w > 0.001 and t in m["px_cad"]]
    plan = row("Your plan (all holdings, rebalanced quarterly, after costs)", None, 1.0, r.path["value"])
    covered = [h for h in holdings if h["expected_real_return"] is not None]
    cw = sum(h["weight"] for h in covered)
    plan["expected_real_return"] = (sum(h["weight"] * h["expected_real_return"] for h in covered) / cw) if cw else None
    plan["expected_coverage"] = cw
    return {"start": str(idx[0].date()), "end": str(idx[-1].date()),
            "dates": [str(x.date()) for x in weekly(r.path["value"]).index],
            "inflation": {"total": infl_total, "annual": infl_annual, "growth": (weekly(cpi) * 100).round(2).tolist(),
                          "source": "Statistics Canada, consumer price index (all items)"},
            "plan": plan, "holdings": holdings, "yields": _yield_context(idx[0], idx[-1]),
            "assumptions": {"inflation": pf.assumptions.INFLATION, "source": pf.assumptions.SOURCE["name"]},
            "note": "In Canadian dollars, dividends reinvested. Real return = return above the rise in the cost of "
                    "living. Past results do not predict future returns."}


class TradeRequest(BaseModel):
    symbol: str
    weight: float


@app.get("/api/universe")
def universe():
    u = market()["universe"]
    return [{"ticker": t, "name": u.loc[t, "name"], "asset_class": u.loc[t, "asset_class"]} for t in sorted(u.index)]


# Assets outside the stored universe: checked once (cov.evaluate), kept for a few hours. Errors are not cached.
LIVE_CACHE = TTLCache(6 * 3600)
SEARCH_CACHE = TTLCache(600)


def _search(q: str) -> list[dict]:
    return SEARCH_CACHE.get(q.strip().lower(), lambda: cov.search_quotes(cov.fetch_search(q)))


def live_asset(symbol: str, info: dict | None = None) -> cov.Asset:
    """Coverage verdict for a symbol outside the universe (raises on network errors, which are not cached)."""
    def load():
        m = market()
        meta, frame = cov.parse_chart(cov.fetch_chart(symbol))
        found = info or next((x for x in _search(symbol) if x["symbol"] == symbol), {})
        return cov.evaluate(symbol, meta, frame, found, m["px_cad"], m["fx"])
    return LIVE_CACHE.get(("live", symbol), load)


def _stored_item(t: str, u: pd.DataFrame) -> dict:
    return {"symbol": t, "name": u.loc[t, "name"], "type": cov.TYPE_LABEL.get(u.loc[t, "asset_class"], "Other"),
            "exchange": u.loc[t, "market"], "source": "stored"}


@app.get("/api/advocate/search")
def advocate_search(q: str = "", user: str = Depends(current_user)):
    """Investments the devil's advocate can review: the stored universe, plus live matches that pass cov.evaluate.

    Matches that fail the rules are not listed; only their number is returned, so the page can say so.
    """
    u = market()["universe"]
    text = q.strip()
    up, low = text.upper(), text.lower()
    stored = [t for t in sorted(u.index) if not text or up in t or low in str(u.loc[t, "name"]).lower()]
    stored.sort(key=lambda t: (t != up, not t.startswith(up)))
    results = [_stored_item(t, u) for t in stored]
    hidden, note = 0, None
    if text:
        try:
            quotes = _search(text)
        except Exception:
            quotes, note = [], "Live search is unavailable right now: only the stored assets are listed."
        candidates = [x for x in quotes if x["symbol"] not in u.index][:8]
        hidden += sum(1 for x in candidates if x["kind"] == "currency")
        candidates = [x for x in candidates if x["kind"] != "currency"]

        def check(x):
            try:
                return live_asset(x["symbol"], x)
            except Exception:
                return None
        with ThreadPoolExecutor(max_workers=6) as ex:
            checked = list(ex.map(check, candidates))
        for x, a in zip(candidates, checked):
            if a is not None and a.covered:
                results.append({"symbol": a.symbol, "name": a.name, "type": cov.TYPE_LABEL.get(a.asset_class, "Other"),
                                "exchange": a.exchange, "source": "live"})
            else:
                hidden += 1
    return {"results": results[:12], "hidden": hidden, "note": note,
            "rules": "Listed only when there is enough data for a reviewed answer: stocks, ETFs or crypto in CAD or "
                     f"USD, at least {cov.MIN_YEARS:g} years of daily prices, traded volume, and a known sector "
                     "(stocks) or a clear match with a stock, bond or gold fund (ETFs)."}


def advocate_inputs(sym: str) -> dict:
    """Prices, universe, liquidity and flags for one asset, stored or live. 422 if it cannot be reviewed."""
    m = market()
    u = m["universe"]
    if sym in u.index:
        liq = None
        if sym in m["volume"]:
            liq = cov.liquidity(m["close"][sym], m["volume"][sym], cov.to_cad_rate(u.loc[sym, "currency"], m["fx"]))
        return {"prices": m["px_cad"], "universe": u, "liquidity": liq, "leveraged": False, "source": "stored"}
    try:
        a = live_asset(sym)
    except Exception:
        raise HTTPException(503, f"Data for {sym} could not be loaded right now. Try again in a moment.")
    if not a.covered:
        raise HTTPException(422, f"{sym} cannot be reviewed: {a.reason}")
    row = pd.DataFrame([a.universe_row()], index=pd.Index([sym], name=u.index.name))
    return {"prices": cov.merge_prices(m["px_cad"], sym, a.checks["adj_cad"]), "universe": pd.concat([u, row]),
            "liquidity": cov.liquidity(a.close, a.volume, cov.to_cad_rate(a.currency, m["fx"])),
            "leveraged": a.leveraged, "source": "live", "behaves_like": a.behaves_like}


@app.post("/api/advocate")
def devils_advocate(req: TradeRequest, user: str = Depends(current_user)):
    st = user_state(user)
    sym = req.symbol.strip().upper()
    a = advocate_inputs(sym)
    hs = headlines(sym)
    dg = news.digest(sym, hs).to_dict() if hs else None
    rv = advocate.review_trade(sym, max(0.01, min(req.weight, 0.9)), st["weights"], st["effective"], a["prices"],
                               a["universe"], news_digest=dg, macro_items=macro_items(), liquidity=a["liquidity"],
                               amount=st["plan"].total_amount, leveraged=a["leveraged"])
    tone, title = VERDICT[rv.verdict]
    row = a["universe"].loc[sym]
    basis = (f"Stored dataset ({a['prices'].index[0].date()} to {a['prices'].index[-1].date()})" if a["source"] == "stored"
             else f"Yahoo Finance daily prices, aligned to the stored dataset's calendar")
    if a.get("behaves_like"):
        b = a["behaves_like"]
        basis += f". Fund type inferred from its prices: moves like {b['label']} ({b['reference']}, correlation {b['correlation']:.2f})"
    return jsonable({"verdict": {"tone": tone, "text": title},
                     "asset": {"symbol": sym, "name": row["name"], "type": cov.TYPE_LABEL.get(row["asset_class"], "Other"),
                               "source": a["source"], "basis": basis, "liquidity": a["liquidity"]},
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


def _summarize_receipt(r: dict) -> dict:
    """Build a beginner-friendly plain-English summary of a tool receipt so any user can audit the numbers."""
    tool = r.get("tool", "")
    agent = r.get("agent", "advisor")
    agent_label = "Devil's Advocate Agent" if agent == "advocate" else "Advisor Agent"
    inp = r.get("inputs") or {}
    out = r.get("output") or {}
    if r.get("error"):
        return {
            **r,
            "plain_title": f"Tool check ({tool})",
            "agent_label": agent_label,
            "plain_summary": f"Attempted to run {tool}, which returned a notice: {r['error']}",
            "key_facts": [],
        }

    plain_title = f"Calculation ({tool})"
    plain_summary = "Verified calculation from the WealthPilot engine."
    key_facts: list[str] = []

    if tool == "investor_context":
        plain_title = "Your Investor Profile, Goals & Safety Limits"
        lvl = out.get("level_name", f"Level {out.get('level', '?')}")
        sc10 = out.get("score_10")
        amt = out.get("amount_cad", 0)
        c = out.get("constraints") or {}
        lim = c.get("limits") or {}
        eq_min = pct(c.get("equity_min"), 0)
        eq_max = pct(c.get("equity_max"), 0)
        max_single = pct(lim.get("max_single_security"), 0)
        max_sec = pct(lim.get("max_sector"), 0)
        goals = out.get("goals") or []
        plain_summary = (
            f"Loaded your profile ({lvl}" + (f", {sc10}/10 risk" if sc10 is not None else "") +
            f") and your simulated portfolio of {money(amt)} CAD."
        )
        key_facts = [
            f"Profile level: {lvl}" + (f" ({sc10}/10 risk, capacity {out.get('capacity', 0):.0f}/100, tolerance {out.get('tolerance', 0):.0f}/100)" if sc10 is not None else ""),
            f"Safety rules: {eq_min}–{eq_max} in stocks, max {max_single} in one company, max {max_sec} in one sector",
        ]
        if goals:
            key_facts.append("Goals: " + "; ".join(
                f"{g['name']} (horizon {g['horizon_years']:g} yrs, target {money(g['target_amount'])})" for g in goals
            ))
    elif tool == "ticker_overview":
        sym = inp.get("symbol") or (out.get("identity") or {}).get("ticker") or "Asset"
        name = (out.get("identity") or {}).get("name") or sym
        plain_title = f"Market & Fit Check for {name} ({sym})"
        rets = out.get("returns") or {}
        rsk = out.get("risk") or {}
        fit = out.get("fit_score") or {}
        r1y = (rets.get("1Y") or {}).get("value")
        cagr = (rets.get("CAGR_full") or {}).get("value")
        vol = (rsk.get("volatility_full") or {}).get("value")
        mdd = (rsk.get("max_drawdown") or {}).get("value")
        fscore = fit.get("score")
        flabel = fit.get("label") or "—"
        plain_summary = (
            f"Measured real historical performance and risk for {name} ({sym}) in CAD and scored how well it fits your profile."
        )
        key_facts = [
            f"1-year return: {pct(r1y, 1)} · 5-year annual return (CAGR): {pct(cagr, 1)}",
            f"Annual price swings (volatility): {pct(vol, 1)} · Worst historical drop: {pct(mdd, 1)}",
            f"Profile fit score: {fscore:.0f}/100 ({flabel})" if fscore is not None else f"Profile fit: {flabel}",
        ]
    elif tool == "review_trade":
        sym = out.get("symbol") or inp.get("symbol", "Asset")
        w = out.get("requested_weight", inp.get("weight", 0))
        verdict = out.get("verdict", "reviewed")
        chals = out.get("challenges") or []
        ba = out.get("before_after") or {}
        bef = ba.get("before") or {}
        aft = ba.get("after") or {}
        plain_title = f"Devil's Advocate Trade Test: {pct(w, 0)} in {sym}"
        plain_summary = (
            f"Simulated putting {pct(w, 0)} of your portfolio into {sym}. Verdict: '{verdict.capitalize()}' "
            f"with {len(chals)} risk/rule check(s) triggered."
        )
        if bef and aft:
            key_facts.append(
                f"Annual return (2021–2026): {pct(bef.get('cagr'), 1)} before → {pct(aft.get('cagr'), 1)} after"
            )
            key_facts.append(
                f"Worst temporary drop: {pct(bef.get('max_drawdown'), 1)} before → {pct(aft.get('max_drawdown'), 1)} after"
            )
            key_facts.append(
                f"Annual volatility: {pct(bef.get('volatility'), 1)} before → {pct(aft.get('volatility'), 1)} after"
            )
        if chals:
            key_facts.append("Flags raised: " + ", ".join(c.get("code", "") for c in chals[:4]))
    elif tool == "review_allocation":
        verdict = out.get("verdict", "reviewed")
        chals = out.get("challenges") or []
        plain_title = "Portfolio Rules & Diversification Check"
        plain_summary = (
            f"Audited the portfolio against your profile's stock, sector, and single-company limits. "
            f"Verdict: '{verdict.capitalize()}' ({len(chals)} alert(s))."
        )
        for c in chals[:3]:
            key_facts.append(f"{c.get('code', 'Alert')}: {c.get('claim', '')}")
    elif tool == "propose_allocation":
        w = out.get("weights") or {}
        plain_title = "Recommended ETF Portfolio Allocation"
        plain_summary = f"Built a diversified policy allocation across {len(w)} low-cost index funds for your risk level."
        top = ", ".join(f"{k} ({pct(v, 0)})" for k, v in sorted(w.items(), key=lambda x: -x[1])[:5])
        if top:
            key_facts.append(f"Holdings: {top}")
    elif tool == "replay_history":
        amt = out.get("amount", 0)
        fin = out.get("final_value", 0)
        cagr = out.get("cagr")
        wd = out.get("worst_drawdown") or {}
        plain_title = "Time-Machine Historical Replay (2021–2026)"
        plain_summary = (
            f"Replayed {money(amt)} CAD through real 2021–2026 market history: ending at {money(fin)} CAD ({pct(cagr, 1)}/yr)."
        )
        if wd:
            key_facts.append(
                f"Worst drop: {pct(wd.get('max_drawdown'), 1)} ({money(wd.get('dollars_lost', 0))} lost at the bottom on {wd.get('trough_date', '')})"
            )
    elif tool == "risk_map":
        rlist = out.get("risks") or []
        plain_title = "6-Dimension Portfolio Risk Map"
        plain_summary = "Measured market, credit, liquidity, currency, concentration, and inflation risks on your portfolio."
        for rk in rlist[:4]:
            key_facts.append(f"{rk.get('kind', '').capitalize()} risk ({rk.get('level', '')}): {pct(rk.get('value'), 1)}")
    elif tool == "news_digest":
        sym = out.get("ticker") or inp.get("symbol", "Asset")
        cnt = out.get("n", out.get("count", 0))
        hype = out.get("hype_share")
        pred_sh = out.get("share_predictive")
        plain_title = f"News & Hype Analysis for {sym}"
        plain_summary = (
            f"Checked {cnt} recent headlines on {sym}, separating factual reports from predictions/opinions "
            f"(opinion/prediction share: {pct(pred_sh, 0)}, low-trust hype share: {pct(hype, 0)})."
        )
        top_desc = out.get("top_descriptive") or []
        if top_desc:
            key_facts.append(f"Top factual report ({top_desc[0].get('publisher', 'Source')}): \"{top_desc[0].get('title', '')}\"")
        if out.get("controversies"):
            key_facts.append(f"ESG/regulatory headlines flagged: {len(out['controversies'])}")
    elif tool == "macro_news_impact":
        items = out.get("items") or []
        plain_title = "Official Central Bank & Economic News Impact"
        plain_summary = (
            f"Analyzed {len(items)} official releases from the Bank of Canada, Federal Reserve, and Statistics Canada "
            f"and measured how much of your portfolio is exposed."
        )
    elif tool == "inflation_forecast":
        h = out.get("horizon_months") or inp.get("horizon_months", 12)
        plain_title = f"Canadian CPI Inflation Forecast ({h} months)"
        plain_summary = (
            f"Walk-forward CPI forecast {h} months ahead: {out.get('forecast', 0):.2f}% "
            f"(80% range: {out.get('low', 0):.2f}% to {out.get('high', 0):.2f}%) vs. {out.get('current_yoy', 0):.2f}% currently."
        )
    elif tool == "what_would_change":
        conds = out.get("conditions") or []
        plain_title = "What Would Change This Recommendation"
        plain_summary = f"Computed {len(conds)} concrete tipping points (horizon, cushion, or risk level changes) that would alter the plan."
        for c in conds[:3]:
            key_facts.append(f"{c.get('condition', '')} → {c.get('effect', '')}")
    elif tool == "stress_test":
        scens = out.get("scenarios") or []
        plain_title = "Hypothetical Crisis Stress Tests"
        plain_summary = f"Tested your portfolio across {len(scens)} extreme market shock scenarios and 10-year inflation erosion."
        for sc in scens[:3]:
            key_facts.append(f"{sc.get('label', sc.get('scenario', 'Shock'))}: {pct(sc.get('portfolio_return'), 1)} ({money(sc.get('dollars', 0))})")
    elif tool == "strategy_lab":
        res = out.get("result") or {}
        sym = res.get("symbol") or inp.get("symbol", "Asset")
        strat = res.get("strategy") or inp.get("strategy", "rule")
        so = res.get("out_of_sample") or {}
        bo = res.get("buy_hold_out_of_sample") or {}
        plain_title = f"Strategy Lab Out-of-Sample Test: {strat} on {sym}"
        plain_summary = (
            f"Tuned {strat} on 70% of {sym} history and tested out-of-sample on the remaining 30% against buy-and-hold."
        )
        if so and bo:
            key_facts.append(f"Out-of-sample total return: rule {pct(so.get('total_return'), 1)} vs. buy-and-hold {pct(bo.get('total_return'), 1)}")
            key_facts.append(f"Out-of-sample Sharpe ratio: rule {so.get('sharpe', 0):.2f} vs. buy-and-hold {bo.get('sharpe', 0):.2f}")
    elif tool == "compare_allocations":
        rows = out.get("table") or []
        plain_title = "Side-by-Side Portfolio Backtest Comparison"
        plain_summary = f"Compared {len(rows)} candidate allocations on the same 2021–2026 CAD historical window."
        for row in rows[:3]:
            key_facts.append(
                f"{row.get('portfolio', row.get('index', 'Portfolio'))}: CAGR {pct(row.get('cagr'), 1)}, worst fall {pct(row.get('max_drawdown'), 1)}"
            )
    elif tool == "plan_goals":
        gls = out.get("goals") or []
        plain_title = "Goal-by-Goal Investment Plan"
        plain_summary = f"Built dedicated sub-portfolios and account recommendations across {len(gls)} financial goal(s)."
        for g in gls[:3]:
            goal_info = g.get("goal") or {}
            key_facts.append(f"{goal_info.get('name', 'Goal')}: Level {g.get('level')} ({g.get('level_name', '')}) in {g.get('account', '')}")
    elif tool == "build_profile":
        lvl = out.get("level_name", f"Level {out.get('level', '?')}")
        plain_title = "Questionnaire Risk Profile Scoring"
        plain_summary = f"Scored your answers into {lvl} (capacity {out.get('capacity', 0):.0f}/100, tolerance {out.get('tolerance', 0):.0f}/100)."
    elif tool == "set_portfolio":
        w = out.get("weights") or {}
        plain_title = "Custom Portfolio Validation"
        plain_summary = f"Recorded {len(w)} holdings and checked them against your profile constraints."
    elif tool == "invest_now_or_wait":
        inv = out.get("invested", 0)
        now_v = (out.get("now") or {}).get("average_value", 0)
        spr_v = (out.get("spread") or {}).get("average_value", 0)
        sig_v = (out.get("signal") or {}).get("average_value", 0)
        plain_title = "Entry Timing Study: Invest Now vs. Spread Over 6 Months vs. ML Signal"
        plain_summary = (
            f"Tested {money(inv)} CAD across {out.get('starts', 0)} historical start months ({out.get('period', '')}), "
            f"comparing investing immediately, spreading over {out.get('spread_months', 6)} months, or waiting for the ML timing signal."
        )
        key_facts = [
            f"Average value after {out.get('horizon_months', 12)} months: Invest now {money(now_v)} · Spread {money(spr_v)} · ML signal {money(sig_v)}",
            f"ML signal beat investing now in {pct((out.get('signal') or {}).get('beats_now_share'), 0)} of start months",
        ]
    return {
        **r,
        "plain_title": plain_title,
        "agent_label": agent_label,
        "plain_summary": plain_summary,
        "key_facts": key_facts,
    }


@app.post("/api/ask")
def ask(q: Question, user: str = Depends(current_user)):
    if not (os.environ.get("WEALTHPILOT_LLM") or os.environ.get("ANTHROPIC_API_KEY")):
        raise HTTPException(503, "Agents are not connected in this local demo. Set WEALTHPILOT_LLM=bedrock (AWS) or "
                                 "WEALTHPILOT_LLM=anthropic to ask questions in free text.")
    from .agents import Session, ask as run
    from .agents.llm import from_env
    st = user_state(user)
    u = market()["universe"]
    sess = Session.from_starter()
    sess.profile, sess.portfolio, sess.amount = st["effective"], st["weights"], st["plan"].total_amount
    fin = st["onboarding"].financials
    card = pf.level_card(sess.profile.level)
    sess.ledger.record("investor_context", "advisor", {"amount": sess.amount}, jsonable({
        "level": sess.profile.level,
        "level_name": sess.profile.level_name,
        "score_10": card["score_10"],
        "capacity": round(sess.profile.capacity, 1),
        "tolerance": round(sess.profile.tolerance, 1),
        "experience": sess.profile.experience,
        "age": fin.age,
        "emergency_months": round(fin.emergency_months, 1),
        "financials": fin.to_dict(),
        "amount_cad": sess.amount,
        "goals": [asdict(g) for g in st["onboarding"].goals],
        "constraints": sess.profile.constraints.to_dict(),
        "preferences": asdict(sess.profile.preferences),
        "current_portfolio_weights": sess.portfolio,
        "current_portfolio_holdings": [
            {"ticker": k, "name": str(u.loc[k, "name"]) if k in u.index else k, "weight": v}
            for k, v in sorted(sess.portfolio.items(), key=lambda x: -x[1])
        ],
    }))
    try:
        ans = run(sess, q.question, from_env(), debate=False)
    except Exception as e:  # missing AWS credentials, no model access, network: say so instead of a 500
        raise HTTPException(503, f"The agents could not answer ({type(e).__name__}: {str(e)[:200]}). Check the AWS "
                                 "credentials and Bedrock model access, or set WEALTHPILOT_LLM=anthropic with an API key.")
    raw_receipts = [x.to_dict() for x in sess.ledger.receipts]
    receipts = [_summarize_receipt(x) for x in raw_receipts]
    aws_trace_id = None
    trace_table = os.environ.get("TRACE_TABLE") or os.environ.get("WEALTHPILOT_TRACE_TABLE")
    if trace_table:
        try:
            import boto3
            from .aws.storage import TraceStore
            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
            table = boto3.resource("dynamodb", region_name=region).Table(trace_table)
            aws_trace_id = TraceStore(table).save_turn(user, q.question, ans.to_dict(), raw_receipts)
        except Exception:
            aws_trace_id = None
    return jsonable({
        "text": ans.text,
        "draft": ans.draft,
        "critique": ans.critique,
        "receipts": receipts,
        "report": ans.report.to_dict(),
        "revisions": ans.revisions,
        "trace": ans.trace,
        "aws_trace_id": aws_trace_id,
        "aws_trace_table": trace_table if aws_trace_id else None,
    })


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


def _aws_credentials() -> bool:
    try:
        import boto3
        return boto3.Session().get_credentials() is not None
    except Exception:
        return False


def main() -> None:
    import uvicorn
    # Use Claude on Amazon Bedrock by default when AWS credentials are configured on this machine; otherwise the
    # agents stay off and the interface says how to turn them on (the rest of the app works without them).
    if not os.environ.get("WEALTHPILOT_LLM") and _aws_credentials():
        os.environ["WEALTHPILOT_LLM"] = "bedrock"
        os.environ.setdefault("AWS_REGION", "us-east-1")
        os.environ.setdefault("TRACE_TABLE", "wealthpilot-traces")
    uvicorn.run("wealthpilot.api:app", host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))


if __name__ == "__main__":
    main()
