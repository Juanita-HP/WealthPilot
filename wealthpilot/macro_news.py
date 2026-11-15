"""Global news, read in full, translated into exposure of the investor's own portfolio.

Our recommendations are diversified portfolios, so the news that matters is the
news that moves whole asset classes: interest rate decisions, inflation, jobs,
growth, trade, energy, the exchange rate. For each recent item:

1. Collect it from official feeds (Bank of Canada, Federal Reserve, Statistics
   Canada's The Daily). These sources publish the full text and allow it to be
   read (see ``webtext``: robots.txt is checked, including for AI agents).
2. Read the text (BeautifulSoup) and analyse it sentence by sentence:
   - the decision or figure it announces (rate raised to 2.5%, CPI up 2.4%),
   - the risk factors it talks about (rates, inflation, currency, energy,
     growth, trade), each with the exact sentences as evidence,
   - which sentences are facts and which are the source's own forecasts.
3. Map each factor to the investor's holdings: directly exposed, indirectly
   exposed, not exposed. The unexposed share is what diversification buys.
4. Show what happened before after similar events, measured in our price data
   (20 business days after past rate hikes, cuts, inflation surprises), with the
   number of cases and whether the difference is distinguishable from noise.
5. Suggest the matching hypothetical stress test.

News never change the recommended allocation: reacting to news is market
timing, which works against a cautious investor. They explain why the portfolio
moves and what to watch.
"""

from __future__ import annotations

import json
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import data, webtext

MACRO_DIR = Path(os.environ.get("WEALTHPILOT_NEWS_DIR", Path(__file__).resolve().parent.parent / "data" / "news")) / "macro"
ANALYZER_VERSION = "macro-rules-v1"

# ----------------------------------------------------------------------------- sources

FEEDS = [
    {"id": "boc", "publisher": "Bank of Canada", "region": "CA",
     "url": "https://www.bankofcanada.ca/content_type/press-releases/feed/", "keep": None},
    {"id": "fed", "publisher": "Federal Reserve", "region": "US",
     "url": "https://www.federalreserve.gov/feeds/press_monetary.xml", "keep": None},
    {"id": "statcan", "publisher": "Statistics Canada", "region": "CA",
     "url": "https://www150.statcan.gc.ca/n1/rss/dai-quo/0-eng.atom",
     # The Daily publishes ~10 releases a day; only the major market-moving indicators are kept.
     "keep": re.compile(r"^(Consumer Price Index,|Labour Force Survey,|Gross domestic product|"
                        r"Canadian international merchandise trade,|Retail trade,)", re.I)},
]


@dataclass
class FeedItem:
    source: str
    publisher: str
    region: str
    title: str
    link: str
    published_at: str
    summary: str = ""


def _text(el) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _child(el, name: str):
    return next((c for c in el if c.tag.split("}")[-1] == name), None)


def _parse_date(s: str) -> str:
    s = (s or "").strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = datetime.strptime(s, fmt)
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
        except ValueError:
            pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return ""


def parse_feed(xml: str | bytes, feed: dict) -> list[FeedItem]:
    """RSS 2.0, RSS 1.0 (RDF) and Atom."""
    root = ET.fromstring(xml)
    out = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = _text(_child(el, "title"))
        link_el = _child(el, "link")
        link = (link_el.get("href") if link_el is not None and link_el.get("href") else _text(link_el))
        date = next((_text(_child(el, n)) for n in ("pubDate", "date", "updated", "published") if _child(el, n) is not None), "")
        summary = _text(_child(el, "description") or _child(el, "summary"))
        if not title or not link:
            continue
        if feed.get("keep") is not None and not feed["keep"].search(title):
            continue
        out.append(FeedItem(feed["id"], feed["publisher"], feed["region"], title, link.strip(), _parse_date(date), summary))
    return out


# ----------------------------------------------------------------------------- text analysis

FACTORS = {
    "rates": ("Interest rates", r"\b(policy rate|overnight rate|federal funds|interest rates?|bond yields?|yields|"
                                r"monetary policy|policy stance|basis points?|rate (cuts?|hikes?|increases?|decreases?)|"
                                r"financial conditions)\b"),
    "inflation": ("Inflation", r"\b(inflation|consumer price index|CPI|price stability|cost pressures|"
                               r"prices? (rose|increased|fell|declined|were up|were down))\b"),
    "currency": ("Currency (CAD / USD)", r"\b(Canadian dollar|U\.?S\.?[- ]dollar|exchange rates?|currenc(y|ies)|loonie)\b"),
    "energy": ("Energy and oil", r"\b(oil|gasoline|energy prices?|crude|petroleum|natural gas|refin\w*|fuel)\b"),
    "growth": ("Growth and jobs", r"\b(GDP|gross domestic product|economic activity|economy|recession|"
                                       r"unemployment|employment|jobs?|labou?r market|consumer spending|"
                                       r"excess supply|business investment|retail sales)\b"),
    "trade": ("Trade and geopolitics", r"\b(tariffs?|trade (relations|war|policy|tensions|environment)|exports?|"
                                         r"imports?|sanctions|geopolitic\w*|conflict)\b"),
}
FACTOR_RX = {k: re.compile(v[1], re.I) for k, v in FACTORS.items()}
FACTOR_LABEL = {k: v[0] for k, v in FACTORS.items()}

FORWARD = re.compile(r"\b(expect\w*|project\w*|forecast\w*|outlook|will|anticipat\w*|likely|could|may|"
                     r"is set to|going forward|risks? to)\b", re.I)

SCHEDULE = re.compile(r"\b(next scheduled|scheduled date|will announce|will be released|plans to meet|media inquiries)\b", re.I)

FRACTIONS = {"½": ".5", "¼": ".25", "¾": ".75"}


def _num(s: str) -> float | None:
    s = s.strip()
    for k, v in FRACTIONS.items():
        s = s.replace(k, v)
    m = re.match(r"^(\d+)-(\d)/(\d)$", s)          # 3-3/4
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    try:
        return float(s)
    except ValueError:
        return None


UP = {"increased", "raised", "raise", "increase", "rose", "grew", "edged up", "rise", "up", "higher", "accelerated"}
DOWN = {"lowered", "reduced", "cut", "lower", "reduce", "fell", "declined", "decreased", "edged down", "down",
        "contracted", "decelerated", "slowed"}

DECISIONS = [
    ("policy_rate", re.compile(
        r"(increased|raised|lowered|reduced|cut|maintained|held|kept)\s+(?:its\s+)?target for the overnight rate"
        r"(?:\s+(?:by|at)\s+\d+\s+basis points?)?\s+(?:to|at)\s+([\d.½¼¾]+)\s?%", re.I)),
    ("policy_rate", re.compile(
        r"decided to (raise|lower|maintain|reduce|increase) the target range for the federal funds rate"
        r"(?:\s+by\s+[\d/ ]+\s+percentage points?)?\s+(?:to|at)\s+[\d\-/ ]+?\s+to\s+([\d\-/]+)\s+percent", re.I)),
    ("cpi", re.compile(r"Consumer Price Index \(CPI\)\s+(rose|increased|fell|declined|was unchanged)\s*([\d.]+)?%?"
                       r"\s*year over year", re.I)),
    ("unemployment", re.compile(r"unemployment rate\s+(rose|fell|increased|decreased|edged up|edged down|"
                                r"was little changed|held steady|was unchanged)(?:.{0,60}?\bto\s+([\d.]+)%)?", re.I)),
    ("gdp", re.compile(r"(?:Real gross domestic product \(GDP\)|Real GDP)\s+(rose|grew|fell|declined|contracted|"
                       r"edged up|edged down|was essentially unchanged|was unchanged)\s*([\d.]+)?%?", re.I)),
]
DECISION_LABEL = {"policy_rate": "Policy rate", "cpi": "Inflation (CPI)", "unemployment": "Unemployment rate",
                  "gdp": "Real GDP"}
DECISION_FACTOR = {"policy_rate": "rates", "cpi": "inflation", "unemployment": "growth", "gdp": "growth"}


def sentences(text: str) -> list[str]:
    out = []
    for para in text.split("\n"):
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z(\"“])", para):
            s = s.strip()
            if len(s) >= 30:
                out.append(s)
    return out


def _direction(verb: str) -> str:
    v = verb.lower()
    if v in UP:
        return "up"
    if v in DOWN:
        return "down"
    return "unchanged"


@dataclass
class TextAnalysis:
    analyzer: str
    n_sentences: int
    decision: dict | None
    factors: dict            # factor -> {"label", "sentences", "share", "quotes"}
    main_factors: list[str]
    forward_share: float     # share of sentences that are the source's own forecasts
    key_quotes: list[dict]   # {"text", "kind": "fact"|"forecast"}
    importance: int

    def to_dict(self):
        return asdict(self)


def analyze_text(text: str, title: str = "") -> TextAnalysis:
    """Deterministic analysis of an official text. Every claim comes with the sentence it is based on."""
    sents = sentences(text)
    n = max(len(sents), 1)
    decision = None
    for kind, rx in DECISIONS:
        for s in sents:
            m = rx.search(s)
            if m:
                decision = {"kind": kind, "label": DECISION_LABEL[kind], "direction": _direction(m.group(1)),
                            "value": _num(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None,
                            "sentence": s, "factor": DECISION_FACTOR[kind]}
                break
        if decision:
            break
    if decision and decision["kind"] == "cpi" and decision["value"] is not None:
        m = re.search(r"following an? ([\d.]+)% (increase|rise|gain|decline|decrease)", decision["sentence"], re.I)
        prev = float(m.group(1)) * (-1 if m and m.group(2).lower() in ("decline", "decrease") else 1) if m else None
        decision["previous"] = prev
        # The figure is an annual rate; what matters is whether it sped up or slowed down.
        decision["direction"] = ("unchanged" if prev is None or abs(decision["value"] - prev) < 0.2
                                 else "up" if decision["value"] > prev else "down")
    factors = {}
    for f, rx in FACTOR_RX.items():
        hits = [s for s in sents if rx.search(s)]
        if hits:
            # Prefer sentences with a figure; announcements of the next meeting date are not evidence.
            # Quotes must be real sentences (not headings or link titles such as "Monetary Policy Report—October").
            useful = [s for s in hits if not SCHEDULE.search(s) and s.rstrip().endswith((".", "!", "?"))
                      and len(s.split()) >= 8] or hits
            with_number = [s for s in useful if re.search(r"\d", s)]
            quotes = (with_number + [s for s in useful if s not in with_number])[:2]
            factors[f] = {"label": FACTOR_LABEL[f], "sentences": len(hits), "share": len(hits) / n,
                          "quotes": [{"text": q, "kind": "forecast" if FORWARD.search(q) else "fact"} for q in quotes]}
    # Without a decision, a factor must come back in at least 3 sentences to be a topic of the text.
    need = 2 if decision else 3
    main = sorted([f for f, v in factors.items() if v["sentences"] >= need and v["share"] >= 0.12],
                  key=lambda f: -factors[f]["sentences"])
    if decision and decision["factor"] not in main:
        main.insert(0, decision["factor"])
    elif decision:
        main.remove(decision["factor"])
        main.insert(0, decision["factor"])
    forward = sum(bool(FORWARD.search(s)) for s in sents) / n
    key = []
    if decision:
        key.append({"text": decision["sentence"], "kind": "fact"})
    for f in main:
        for q in factors.get(f, {}).get("quotes", []):
            if q["text"] not in [k["text"] for k in key]:
                key.append(q)
                break
    importance = 5 if decision and decision["kind"] == "policy_rate" else 4 if decision else 3 if main else 1
    return TextAnalysis(ANALYZER_VERSION, len(sents), decision, factors, main[:3], forward, key[:4], importance)


class LLMTextAnalyzer:
    """Claude reads the same text with a versioned prompt (news_prompts/macro_<version>.md).

    Output has the same shape as the rule analyzer, and every quote must be an exact sentence of the text:
    quotes that are not found verbatim are dropped (no invented evidence).
    """

    TOOL = {
        "name": "record_analysis", "strict": True,
        "description": "Record the analysis of one official economic text.",
        "input_schema": {
            "type": "object", "additionalProperties": False,
            "required": ["decision_kind", "direction", "value", "main_factors", "quotes"],
            "properties": {
                "decision_kind": {"type": "string", "enum": ["policy_rate", "cpi", "unemployment", "gdp", "none"]},
                "direction": {"type": "string", "enum": ["up", "down", "unchanged", "none"]},
                "value": {"type": ["number", "null"]},
                "main_factors": {"type": "array", "items": {"type": "string", "enum": list(FACTORS)}},
                "quotes": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["text", "kind"],
                    "properties": {"text": {"type": "string"}, "kind": {"type": "string", "enum": ["fact", "forecast"]}}}},
            }},
    }

    def __init__(self, llm, version: str = "v1"):
        from .news import PROMPTS_DIR
        self.llm = llm
        self.name = f"claude-macro-{version}"
        self.system = (PROMPTS_DIR / f"macro_{version}.md").read_text()

    def analyze(self, text: str, title: str = "") -> TextAnalysis:
        base = analyze_text(text, title)
        resp = self.llm.create(self.system, [{"role": "user", "content": f"Title: {title}\n\nText:\n{text[:12000]}"}],
                               [self.TOOL], effort="low")
        call = next((b for b in resp.content if b.type == "tool_use"), None)
        if call is None:
            return base
        x = dict(call.input)
        quotes = [q for q in x["quotes"] if q["text"].strip() and q["text"].strip() in text][:4]
        decision = None
        if x["decision_kind"] != "none":
            sent = next((q["text"] for q in quotes if q["kind"] == "fact"), "")
            decision = {"kind": x["decision_kind"], "label": DECISION_LABEL[x["decision_kind"]],
                        "direction": x["direction"] if x["direction"] != "none" else "unchanged",
                        "value": x["value"], "sentence": sent, "factor": DECISION_FACTOR[x["decision_kind"]]}
        return TextAnalysis(self.name, base.n_sentences, decision, base.factors, x["main_factors"][:3],
                            base.forward_share, quotes or base.key_quotes,
                            5 if decision and decision["kind"] == "policy_rate" else 4 if decision else
                            3 if x["main_factors"] else 1)


# ----------------------------------------------------------------------------- collection


@dataclass
class MacroItem:
    id: str
    source: str
    publisher: str
    region: str
    title: str
    link: str
    published_at: str
    text_status: str
    text_status_label: str
    text_chars: int
    analysis: dict
    retrieved_at: str

    def to_dict(self):
        return asdict(self)


def collect(fetcher: webtext.Fetcher | None = None, days: int = 60, per_feed: int = 6,
            feeds: list[dict] | None = None, feed_reader=None, analyzer=None) -> list[MacroItem]:
    """Recent items from each official feed, with the full text read and analysed."""
    fetcher = fetcher or webtext.Fetcher()
    feed_reader = feed_reader or (lambda url: fetcher.opener(url, {"User-Agent": webtext.USER_AGENT})[2])
    analyze = analyzer.analyze if analyzer is not None else analyze_text
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for feed in feeds or FEEDS:
        try:
            items = parse_feed(feed_reader(feed["url"]), feed)
        except Exception:  # one feed down must not hide the others
            continue
        items = sorted([i for i in items if i.published_at >= since], key=lambda i: i.published_at, reverse=True)
        for it in items[:per_feed]:
            page = fetcher.get(it.link)
            text = page.text if page.ok else it.summary
            a = analyze(text, it.title) if text else analyze_text("", it.title)
            out.append(MacroItem(webtext.normalize(it.link), it.source, it.publisher, it.region, it.title,
                                 webtext.normalize(it.link), it.published_at, page.status, page.status_label,
                                 len(page.text), a.to_dict(), now))
    return out


def recent(max_age_hours: float = 12.0, **kw) -> list[dict]:
    """Collected items from the local cache if fresh enough, otherwise collected again."""
    path = MACRO_DIR / "items.jsonl"
    if path.exists():
        rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
        version = kw["analyzer"].name if kw.get("analyzer") is not None else ANALYZER_VERSION
        fresh = bool(rows) and datetime.fromisoformat(rows[0]["retrieved_at"]) > datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        # Analyse again when the rules or the stored fields changed.
        if fresh and rows[0]["analysis"].get("analyzer") == version and "text_status_label" in rows[0]:
            return rows
    rows = [i.to_dict() for i in collect(**kw)]
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return rows


# ----------------------------------------------------------------------------- exposure of a portfolio

EQUITY = ("equity", "etf_equity")


def _channel(factor: str, region: str, row: pd.Series, ticker: str) -> tuple[str, str] | None:
    """(direct|indirect, reason in French) for one holding, or None if not exposed. Documented rules."""
    ac, cur, sector = row["asset_class"], row["currency"], str(row["sector"])
    ultra = "ultra short" in sector.lower()
    local = (region == "CA" and cur == "CAD") or (region == "US" and cur == "USD")
    if factor == "rates":
        if ac == "etf_bond" and ultra:
            return "indirect", "Very short maturities: its yield follows the policy rate and its price barely moves."
        if ac == "etf_bond":
            return ("direct" if local else "indirect",
                    "A bond's price falls when rates rise, and rises when they fall."
                    + ("" if local else " Canadian and U.S. rates often move together."))
        if ac in EQUITY and sector in ("Financials", "Utilities") and local:
            return "indirect", "Rate-sensitive sector (bank margins, utility debt)."
        if ticker == "QQQ" and region == "US":
            return "indirect", "Growth stocks are sensitive to discount rates."
        return None
    if factor == "inflation":
        if ac == "etf_bond" and not ultra:
            return "direct", "Fixed coupons: inflation reduces their real value."
        if ac == "etf_bond":
            return "indirect", "Yield close to short-term rates: follows inflation with a lag."
        if ac == "etf_commodity" or sector == "Energy":
            return "indirect", "Has often held up better against inflation in the past, with no guarantee."
        return None
    if factor == "currency":
        if cur == "USD":
            return "direct", "Held in U.S. dollars: its value in CAD moves with the exchange rate."
        return None
    if factor == "energy":
        if sector == "Energy":
            return "direct", "Energy-sector company."
        if ticker == "XIU.TO":
            return "indirect", "Energy is one of the largest sectors of the Canadian index."
        return None
    if factor == "growth":
        if ac in EQUITY and local:
            return "direct", "Company profits follow the country's economic activity."
        if ac == "etf_bond" and local and not ultra:
            return "indirect", "Bonds often rise when growth slows (opposite effect)."
        if ac in EQUITY:
            return "indirect", "The Canadian and U.S. economies are linked."
        return None
    if factor == "trade":
        if ac in EQUITY and cur == "CAD":
            return "direct", "Canadian companies, exposed to trade with the United States."
        if ac in EQUITY:
            return "indirect", "Tariffs also affect U.S. companies (costs, sales)."
        return None
    return None


def exposure(weights: dict[str, float], universe: pd.DataFrame, factor: str, region: str) -> dict:
    lines = []
    for t, w in weights.items():
        if w <= 0 or t not in universe.index:
            continue
        ch = _channel(factor, region, universe.loc[t], t)
        if ch:
            lines.append({"ticker": t, "name": universe.loc[t, "name"], "weight": float(w), "channel": ch[0],
                          "reason": ch[1]})
    total = sum(w for w in weights.values() if w > 0) or 1.0
    d = sum(x["weight"] for x in lines if x["channel"] == "direct") / total
    i = sum(x["weight"] for x in lines if x["channel"] == "indirect") / total
    return {"factor": factor, "label": FACTOR_LABEL[factor], "region": region, "lines": lines,
            "share_direct": d, "share_indirect": i, "share_unexposed": max(0.0, 1 - d - i)}


# ----------------------------------------------------------------------------- what happened after similar events

HORIZON = 20  # business days, about one month


def event_dates(kind: str, direction: str, region: str) -> list[pd.Timestamp]:
    """Dates of past events of the same kind and direction (from the official series we store)."""
    if kind == "policy_rate":
        sid = "V39079" if region == "CA" else "DFEDTARU"
        s = data.load_macro_history(sid, point_in_time=False).dropna()
        d = s.diff()
        if direction == "up":
            return list(d[d > 0].index)
        if direction == "down":
            return list(d[d < 0].index)
        return []
    if kind == "cpi" and region == "CA":
        # Point in time: the date the figure became public (load_macro_history lags it), so no look-ahead.
        s = data.load_macro_history("STATIC_TOTALCPICHANGE", point_in_time=True).dropna()
        d = s.diff()
        if direction == "up":
            return list(d[d >= 0.2].index)
        if direction == "down":
            return list(d[d <= -0.2].index)
    return []


def analogs(kind: str, direction: str, region: str, tickers: list[str], prices_cad: pd.DataFrame,
            horizon: int = HORIZON) -> dict | None:
    """Average return of each holding over ``horizon`` days after past similar events vs all periods.

    A difference is called clear only if it is at least two standard errors from the usual average;
    with few events or overlapping market regimes, it says so.
    """
    dates = [d for d in event_dates(kind, direction, region)
             if prices_cad.index[0] <= d and d + pd.tseries.offsets.BDay(horizon) <= prices_cad.index[-1]]
    if not dates:
        return None
    rows = []
    idx = prices_cad.index
    for t in tickers:
        if t not in prices_cad.columns:
            continue
        px = prices_cad[t].dropna()
        if px.empty:
            continue
        fwd = px.shift(-horizon) / px - 1
        base = fwd.dropna()
        ev = []
        for d in dates:
            pos = idx.searchsorted(d) - 1   # last close BEFORE the announcement
            if pos < 0:
                continue
            day = idx[pos]
            if day in fwd.index and not math.isnan(fwd.loc[day]):
                ev.append(float(fwd.loc[day]))
        if not ev:
            continue
        n = len(ev)
        mean, usual, sd = sum(ev) / n, float(base.mean()), float(base.std())
        se = sd / math.sqrt(n) if n else float("nan")
        z = (mean - usual) / se if se and not math.isnan(se) else 0.0
        verdict = "too_few" if n < 5 else ("clear" if abs(z) >= 2 else "unclear")
        rows.append({"ticker": t, "n": n, "mean_after": mean, "usual": usual,
                     "hit_rate": sum(e > 0 for e in ev) / n, "z": z, "verdict": verdict,
                     "worst_after": min(ev), "best_after": max(ev)})
    if not rows:
        return None
    return {"kind": kind, "direction": direction, "region": region, "horizon_days": horizon,
            "n_events": len(dates), "first": str(dates[0].date()), "last": str(dates[-1].date()),
            "rows": rows,
            "caveat": ("Historical association, not a forecast. Few cases, and each period had other causes "
                       "(for example, the 2022 hikes coincided with a broad market decline).")}


# ----------------------------------------------------------------------------- impact on one portfolio

STRESS_FOR = {("rates", "up"): "rates_up_1pt", ("inflation", "up"): "stocks_and_bonds_down"}
PUBLISHER_NAME = {"Bank of Canada": "The Bank of Canada", "Federal Reserve": "The U.S. Federal Reserve",
                  "Statistics Canada": "Statistics Canada"}


def _fmt(x: float) -> str:
    return f"{x:g}"


def fact(item: dict) -> str:
    """One plain sentence stating what the official text announces (no interpretation)."""
    d = item["analysis"].get("decision")
    who = PUBLISHER_NAME.get(item["publisher"], item["publisher"])
    if not d:
        return f"{who}: {item['title']}"
    v = d.get("value")
    if d["kind"] == "policy_rate":
        verb = {"up": "raised", "down": "lowered", "unchanged": "held"}[d["direction"]]
        if item["region"] == "US":
            return f"{who} {verb} its policy rate" + (f" (upper bound {_fmt(v)}%)." if v is not None else ".")
        return f"{who} {verb} its policy rate" + (f" {'at' if verb == 'held' else 'to'} {_fmt(v)}%." if v is not None else ".")
    if d["kind"] == "cpi":
        trend = {"up": "speeding up", "down": "slowing down", "unchanged": "roughly stable"}[d["direction"]]
        prev = d.get("previous")
        return (f"Canadian inflation was {_fmt(v)}% over one year"
                + (f" (vs {_fmt(prev)}% the month before)" if prev is not None else "") + f", {trend}.")
    if d["kind"] == "unemployment":
        trend = {"up": "rose", "down": "fell", "unchanged": "was stable"}[d["direction"]]
        joiner = " at" if d["direction"] == "unchanged" else " to"
        return f"Canada's unemployment rate {trend}" + (f"{joiner} {_fmt(v)}%." if v is not None else ".")
    if d["kind"] == "gdp":
        trend = {"up": "grew", "down": "shrank", "unchanged": "was roughly unchanged"}[d["direction"]]
        return f"Canada's real GDP {trend}" + (f" by {_fmt(v)}%." if v is not None and d["direction"] != "unchanged" else ".")
    return f"{who}: {item['title']}"


def _dedupe(items: list[dict]) -> list[dict]:
    """Keep the latest item per publisher and kind (two FOMC statements: only the latest is news)."""
    seen, out = set(), []
    for it in sorted(items, key=lambda r: r["published_at"], reverse=True):
        d = it["analysis"].get("decision")
        key = (it["publisher"], d["kind"] if d else it["title"].split(",")[0])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out
CONCENTRATED = 0.5   # half the portfolio directly exposed to one current news factor


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def impact(weights: dict[str, float], universe: pd.DataFrame, items: list[dict],
           prices_cad: pd.DataFrame | None = None, amount: float | None = None, top: int = 5) -> dict:
    """Recent official news, each mapped to the portfolio. Pure function of its inputs."""
    from . import time_machine
    rows = []
    for it in _dedupe(items):
        a = it["analysis"]
        if a["importance"] < 3 or not a["main_factors"]:
            continue
        factor = a["main_factors"][0]
        ex = exposure(weights, universe, factor, it["region"])
        dec = a.get("decision")
        direction = dec["direction"] if dec else None
        analog = None
        if dec and prices_cad is not None:
            held = [t for t, w in weights.items() if w > 0]
            analog = analogs(dec["kind"], direction, it["region"], held, prices_cad)
        analog_note = None
        if analog is None and dec and dec["kind"] == "policy_rate" and direction == "unchanged":
            analog_note = ("No comparable cases measured: decisions to hold rates are not dated in our rate "
                           "series.")
        elif analog is None and direction == "unchanged":
            analog_note = "No marked change, so nothing comparable to measure."
        elif analog is None:
            analog_note = "No measurable comparable cases in our data for this kind of news."
        stress = None
        scen = STRESS_FOR.get((factor, direction)) or STRESS_FOR.get((factor, None))
        if scen and amount:
            stress = time_machine.shock(weights, universe, amount, scen)
        d, i, u = ex["share_direct"], ex["share_indirect"], ex["share_unexposed"]
        names = ", ".join(sorted({x["name"] for x in ex["lines"] if x["channel"] == "direct"}))
        msg = (f"This news directly affects {_pct(d)} of your portfolio"
               + (f" ({names})" if names else "") + f", and {_pct(i)} indirectly.")
        if d >= CONCENTRATED:
            note = "More than half of your money reacts directly to this factor: your portfolio depends heavily on it."
        elif u >= 0.4:
            note = f"{_pct(u)} is not exposed to it: that is what diversification is for."
        else:
            note = "The effect is spread over several holdings, with none dominating."
        rows.append({
            "id": it["id"], "title": it["title"], "publisher": it["publisher"], "region": it["region"],
            "published_at": it["published_at"], "link": it["link"], "fact": fact(it),
            "text_status": it["text_status"], "text_status_label": it["text_status_label"],
            "importance": a["importance"], "decision": dec, "factor": factor, "factor_label": FACTOR_LABEL[factor],
            "other_factors": [FACTOR_LABEL[f] for f in a["main_factors"][1:]],
            "quotes": a["key_quotes"], "forward_share": a["forward_share"], "analyzer": a["analyzer"],
            "exposure": ex, "concentrated": d >= CONCENTRATED, "message": msg, "note": note,
            "analog": analog, "analog_note": analog_note, "stress": stress})
    rows = sorted(rows, key=lambda r: (r["importance"], r["published_at"]), reverse=True)[:top]
    read = sum(it["text_status"] == "ok" for it in items)
    return {"items": rows, "n_collected": len(items), "n_text_read": read,
            "sources": sorted({it["publisher"] for it in items}),
            "rule": "News explain what moves your money; they never change the recommended allocation.",
            "notes": [f"Full text read for {read} of {len(items)} official releases collected."]}
