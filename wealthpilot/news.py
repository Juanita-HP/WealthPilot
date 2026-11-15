"""News as data: headlines with a source trust score, classified as descriptive or predictive.

Pipeline
--------
1. Collect: headlines per ticker from Yahoo Finance's search endpoint (title,
   publisher, publication time, related tickers). Article pages are read only where the
   site's robots.txt allows AI agents (``read_texts``, ``webtext``). Yahoo
   Finance does not, so for its links the headline is context, not evidence.
2. Trust: each publisher gets a documented trust score (regulator and company
   releases high, wire services and major newspapers next, aggregators and
   promotional sites low).
3. Classify each headline:
   * type: DESCRIPTIVE (something that happened) or PREDICTIVE (forecast,
     opinion, price target, "could", "will")
   * category, sentiment (-1..1), importance (1..5)
   Two classifiers share one interface: a rule-based baseline that runs
   offline, and a Claude classifier whose prompt is versioned in
   wealthpilot/news_prompts/ and scored against a golden dataset.
4. Digest per ticker: counts, trust-weighted sentiment, and a HYPE share
   (predictive headlines from low-trust sources) used by the devil's advocate.

News are used to EXPLAIN and CHALLENGE, never to predict prices.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

NEWS_DIR = Path(os.environ.get("WEALTHPILOT_NEWS_DIR", Path(__file__).resolve().parent.parent / "data" / "news"))
PROMPTS_DIR = Path(__file__).resolve().parent / "news_prompts"

# ----------------------------------------------------------------------------- source trust

TRUST_TIERS = {
    "official": (1.0, "Regulator, central bank or company press release"),
    "wire": (0.85, "Wire service or major financial newspaper with editorial standards"),
    "media": (0.65, "Established financial or tech media"),
    "aggregator": (0.45, "Aggregator, quant summary or opinion platform"),
    "promotional": (0.3, "Stock-picking newsletter or social platform"),
}
PUBLISHER_TIER = {
    # official
    "Business Wire": "official", "GlobeNewswire": "official", "PR Newswire": "official", "CNW Group": "official",
    "Newsfile": "official", "Bank of Canada": "official", "SEC": "official",
    # wire / major papers
    "Reuters": "wire", "Bloomberg": "wire", "Associated Press": "wire", "AP Finance": "wire",
    "The Wall Street Journal": "wire", "Financial Times": "wire", "The Globe and Mail": "wire", "Barrons.com": "wire",
    "MarketWatch": "wire", "CNBC": "wire", "Dow Jones": "wire",
    # media
    "TechCrunch": "media", "Fortune": "media", "Investopedia": "media", "Yahoo Finance": "media",
    "Yahoo Finance Video": "media", "Business Insider": "media", "Morningstar": "media", "The Information": "media",
    "Axios": "media", "Quartz": "media", "Barchart": "media", "Investor's Business Daily": "media",
    # aggregators / opinion
    "Simply Wall St.": "aggregator", "Zacks": "aggregator", "Benzinga": "aggregator", "Insider Monkey": "aggregator",
    "24/7 Wall St.": "aggregator", "GuruFocus.com": "aggregator", "Seeking Alpha": "aggregator",
    "Moneywise": "aggregator", "TipRanks": "aggregator", "MarketBeat": "aggregator", "Investing.com": "aggregator",
    # promotional / social
    "Motley Fool": "promotional", "Stocktwits": "promotional", "InvestorPlace": "promotional",
    # seen in the 2026-11-14 collection
    "MT Newswires": "wire", "CBS News": "wire", "TheStreet": "media", "etf.com": "media", "decrypt": "media",
    "TIKR": "aggregator", "Trefis": "aggregator",
    "99bitcoins": "promotional", "BeInCrypto": "promotional", "CryptoProwl": "promotional",
}
DEFAULT_TIER = "aggregator"


def trust(publisher: str | None) -> tuple[float, str]:
    tier = PUBLISHER_TIER.get((publisher or "").strip(), DEFAULT_TIER)
    return TRUST_TIERS[tier][0], tier


# ----------------------------------------------------------------------------- collection


@dataclass
class Headline:
    id: str
    ticker: str
    title: str
    publisher: str
    published_at: str      # ISO UTC
    link: str
    related: list[str]
    retrieved_at: str
    trust: float = 0.0
    tier: str = ""

    def to_dict(self):
        return asdict(self)


SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search?q={q}&newsCount={n}&quotesCount=0"


def yahoo_search(query: str, count: int) -> list[dict]:
    """Yahoo Finance's public search endpoint (the one yfinance.Search uses), without extra dependencies."""
    import urllib.parse
    import urllib.request
    url = SEARCH_URL.format(q=urllib.parse.quote(query), n=count)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("news", [])


def fetch_headlines(ticker: str, count: int = 20, search=None) -> list[Headline]:
    """Recent headlines for one ticker. ``search`` is injectable for tests."""
    search = search or yahoo_search
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for item in search(ticker, count) or []:
        ts = item.get("providerPublishTime")
        if not item.get("title") or ts is None:
            continue
        t, tier = trust(item.get("publisher"))
        out.append(Headline(
            id=item.get("uuid") or f"{ticker}-{ts}", ticker=ticker, title=item["title"],
            publisher=item.get("publisher") or "", link=item.get("link") or "",
            published_at=datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds"),
            related=list(item.get("relatedTickers") or []), retrieved_at=now, trust=t, tier=tier))
    return out


def save_jsonl(rows: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r.to_dict() if hasattr(r, "to_dict") else r, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ----------------------------------------------------------------------------- classification

TYPES = ("descriptive", "predictive")
CATEGORIES = ("earnings", "product", "legal_regulatory", "deal", "management", "macro", "analyst_rating",
              "market_move", "esg_controversy", "other")


# Words that show a headline is really about the asset (search results include loosely related stories).
NAME_KEYWORDS = {
    "AAPL": ["Apple", "iPhone"], "MSFT": ["Microsoft"], "NVDA": ["Nvidia", "Jensen Huang"],
    "GOOGL": ["Alphabet", "Google"], "AMZN": ["Amazon", "AWS"], "TSLA": ["Tesla", "Cybercab", "Cybertruck"],
    "JPM": ["JPMorgan", "Dimon"], "JNJ": ["Johnson & Johnson", "J&J"], "PG": ["Procter", "P&G", "Pampers", "Tide"],
    "XOM": ["Exxon", "ExxonMobil", "Energy Stocks"], "RY.TO": ["Royal Bank", "RBC"], "TD.TO": ["TD Bank", "Toronto-Dominion"],
    "MFC.TO": ["Manulife"], "ENB.TO": ["Enbridge"], "CNQ.TO": ["Canadian Natural"], "CNR.TO": ["Canadian National", "CN Rail"],
    "FTS.TO": ["Fortis"], "ATD.TO": ["Couche-Tard", "Circle K"], "SHOP.TO": ["Shopify"], "CSU.TO": ["Constellation Software"],
    "XIU.TO": ["TSX"], "SPY": ["S&P 500", "401(k)", "Fed", "PPI", "CPI", "Inflation"], "QQQ": ["Nasdaq", "QQQ", "Tech ETF", "AI trade", "AI Roundup"],
    "ESGV": ["ESG"], "XBB.TO": ["Canadian bond"], "ZST.TO": ["short-term bond"], "AGG": ["Aggregate Bond"],
    "TLT": ["Treasury", "Treasuries", "Interest Bill", "Debt"], "GLD": ["Gold", "Debt"],
    "BTC-USD": ["Bitcoin", "BTC"], "ETH-USD": ["Ether", "Ethereum", "ETH"],
}


def is_relevant(h: dict) -> bool:
    title = h["title"]
    words = NAME_KEYWORDS.get(h.get("ticker", ""), []) + [h.get("ticker", "").split(".")[0].split("-")[0]]
    return any(re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", title, re.I) for w in words if w)


@dataclass
class Label:
    type: str
    category: str
    sentiment: float
    importance: int
    reason: str
    classifier: str
    relevant: bool = True

    def to_dict(self):
        return asdict(self)


PREDICTIVE_CUES = re.compile(
    r"\b(could|may|might|will|would|expect(s|ed)?|forecast|outlook|predict(s|ion)?|price target|target|"
    r"poised|set to|likely|should|upside|downside|top pick|buy now|to buy|to sell|why .* (is|could|will)|"
    r"here'?s why|best|worst|bull(ish)?|bear(ish)?|could soar|could crash|undervalued|overvalued|forget|"
    r"takes?|verdict|thinks?|bets?|calls? for|flags?|warns?|about to|ways to)\b", re.I)
DESCRIPTIVE_CUES = re.compile(
    r"\b(reports?|reported|posts?|posted|announc(es|ed)|declares?|declared|files?|filed|opens?|opened|"
    r"breaks ground|launch(es|ed)|cuts?|raises?|raised|approv(es|ed)|completes?|completed|fell|rose|jumps?|"
    r"slumps?|plunges?|surges?|beats?|misses?|names?|appoints?|resigns?|exit|pulls?|recalls?|sues?|fined)\b", re.I)
CATEGORY_CUES = [
    ("earnings", r"\b(earnings|quarter|q[1-4]|revenue|profit|eps|results|guidance|dividend)\b"),
    ("analyst_rating", r"\b(upgrade|downgrade|price target|rating|analyst|overweight|underweight|top pick)\b"),
    ("legal_regulatory", r"\b(sec|lawsuit|sues?|probe|investigation|regulator|antitrust|fine[ds]?|approval|attorney general|court)\b"),
    ("deal", r"\b(merger|acquisition|acquire|deal|buyout|takeover|stake)\b"),
    ("management", r"\b(ceo|cfo|chief|board|appoints?|resigns?|exit|founder|reinstate[ds]?|ousted|ouster|fired|"
                   r"steps? down|departure|successor|leadership)\b"),
    ("macro", r"\b(fed|rates?|inflation|cpi|tariff|recession|bank of canada|jobs report|economy)\b"),
    ("esg_controversy", r"\b(emissions|climate|spill|pollution|labor|union|strike|safety|recall|scandal|controvers)\w*"),
    ("product", r"\b(launch|pre-orders?|product|model|chip|cybercab|robotaxi|ai|factory|plant|software)\b"),
    ("market_move", r"\b(shares|stock|soars?|plunges?|jumps?|slumps?|rally|sell-off|record high)\b"),
]
POS = re.compile(r"\b(beat|beats|surge|soar|jump|record|approv|raise|growth|gain|strong|wins?|upgrade|expands?)\w*", re.I)
NEG = re.compile(r"\b(miss|plunge|slump|fall|fell|cut|lawsuit|probe|recall|weak|loss|downgrade|scrutiny|pull|crash|halt|fine)\w*", re.I)


class RuleClassifier:
    """Offline baseline (version rules-v3): keyword cues, documented and deterministic."""
    name = "rules-v3"

    def classify(self, h: dict) -> Label:
        title = h["title"]
        pred, desc = len(PREDICTIVE_CUES.findall(title)), len(DESCRIPTIVE_CUES.findall(title))
        typ = "predictive" if pred > desc or title.strip().endswith("?") else "descriptive"
        cat = next((c for c, rx in CATEGORY_CUES if re.search(rx, title, re.I)), "other")
        s = len(POS.findall(title)) - len(NEG.findall(title))
        sentiment = max(-1.0, min(1.0, 0.5 * s))
        importance = {"earnings": 4, "legal_regulatory": 4, "deal": 4, "management": 3, "macro": 3,
                      "esg_controversy": 3, "product": 3, "analyst_rating": 2, "market_move": 2}.get(cat, 1)
        if h.get("tier") == "official":
            importance = min(5, importance + 1)
        reason = f"{pred} predictive cue(s), {desc} descriptive cue(s); category keyword: {cat}"
        return Label(typ, cat, sentiment, importance, reason, self.name, is_relevant(h))


class LLMClassifier:
    """Claude classifier with a versioned prompt (wealthpilot/news_prompts/<version>.md)."""

    TOOL = {
        "name": "record_label", "strict": True,
        "description": "Record the classification of one headline.",
        "input_schema": {"type": "object", "additionalProperties": False,
                         "required": ["type", "category", "sentiment", "importance", "relevant", "reason"],
                         "properties": {
                             "type": {"type": "string", "enum": list(TYPES)},
                             "category": {"type": "string", "enum": list(CATEGORIES)},
                             "sentiment": {"type": "number"},
                             "importance": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                             "relevant": {"type": "boolean"},
                             "reason": {"type": "string"}}},
    }

    def __init__(self, llm, version: str = "v2"):
        self.llm = llm
        self.version = version
        self.name = f"claude-prompt-{version}"
        self.system = (PROMPTS_DIR / f"{version}.md").read_text()

    def classify(self, h: dict) -> Label:
        msg = (f"Headline: {h['title']}\nPublisher: {h.get('publisher', '')} (source tier: {h.get('tier', '')})\n"
               f"Ticker: {h.get('ticker', '')}\nCall record_label once.")
        resp = self.llm.create(self.system, [{"role": "user", "content": msg}], [self.TOOL], effort="low")
        call = next((b for b in resp.content if b.type == "tool_use"), None)
        if call is None:
            raise ValueError("classifier returned no label")
        x = dict(call.input)
        return Label(x["type"], x["category"], max(-1.0, min(1.0, float(x["sentiment"]))), int(x["importance"]),
                     x["reason"], self.name, bool(x["relevant"]))


# ----------------------------------------------------------------------------- evaluation against the golden set


def evaluate(classifier, golden: list[dict], exclude_text: str = "") -> dict:
    """Agreement with human labels. Golden rows: headline fields + 'label' dict.

    Headlines quoted in ``exclude_text`` (a prompt's worked examples) are left out to avoid leakage.
    """
    golden = [g for g in golden if g["title"][:40] not in exclude_text]
    rows = []
    for g in golden:
        pred = classifier.classify(g)
        gold = g["label"]
        rows.append({"id": g["id"], "type_ok": pred.type == gold["type"], "category_ok": pred.category == gold["category"],
                     "sentiment_sign_ok": (pred.sentiment > 0.15) - (pred.sentiment < -0.15)
                     == (gold["sentiment"] > 0.15) - (gold["sentiment"] < -0.15),
                     "importance_error": abs(pred.importance - gold["importance"]),
                     "relevance_ok": pred.relevant == gold.get("relevant", True),
                     "predicted_type": pred.type, "gold_type": gold["type"]})
    n = len(rows)
    pred_pred = [r for r in rows if r["predicted_type"] == "predictive"]
    gold_pred = [r for r in rows if r["gold_type"] == "predictive"]
    tp = sum(r["predicted_type"] == r["gold_type"] == "predictive" for r in rows)
    return {
        "classifier": classifier.name, "n": n,
        "type_accuracy": sum(r["type_ok"] for r in rows) / n,
        "predictive_precision": tp / len(pred_pred) if pred_pred else None,
        "predictive_recall": tp / len(gold_pred) if gold_pred else None,
        "category_accuracy": sum(r["category_ok"] for r in rows) / n,
        "sentiment_sign_accuracy": sum(r["sentiment_sign_ok"] for r in rows) / n,
        "importance_mae": sum(r["importance_error"] for r in rows) / n,
        "relevance_accuracy": sum(r["relevance_ok"] for r in rows) / n,
        "errors": [r for r in rows if not r["type_ok"]],
    }


# ----------------------------------------------------------------------------- digest per ticker

LOW_TRUST = 0.6


@dataclass
class Digest:
    ticker: str
    n: int
    window: str
    share_predictive: float
    share_low_trust: float
    hype_share: float
    sentiment_trust_weighted: float
    by_category: dict
    top_descriptive: list[dict]
    top_predictive: list[dict]
    classifier: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def digest(ticker: str, headlines: list[dict], classifier=None, as_of: str | None = None) -> Digest:
    """Aggregate classified headlines published up to ``as_of`` (point in time), keeping relevant ones."""
    classifier = classifier or RuleClassifier()
    items = [h for h in headlines if as_of is None or h["published_at"] <= as_of]
    rows, dropped = [], 0
    for h in items:
        lab = classifier.classify(h)
        if not lab.relevant:
            dropped += 1
            continue
        rows.append({**h, "label": lab.to_dict()})
    n = len(rows)
    if n == 0:
        return Digest(ticker, 0, "", 0.0, 0.0, 0.0, 0.0, {}, [], [], classifier.name,
                      [f"No relevant headlines ({dropped} loosely related left out)."])
    pred = [r for r in rows if r["label"]["type"] == "predictive"]
    low = [r for r in rows if r["trust"] < LOW_TRUST]
    hype = [r for r in pred if r["trust"] < LOW_TRUST]
    wsum = sum(r["trust"] for r in rows)
    sent = sum(r["trust"] * r["label"]["sentiment"] for r in rows) / wsum if wsum else 0.0
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["label"]["category"]] = cats.get(r["label"]["category"], 0) + 1
    key = lambda r: (-r["trust"], -r["label"]["importance"], r["published_at"])  # noqa: E731
    slim = lambda r: {"title": r["title"], "publisher": r["publisher"], "published_at": r["published_at"],  # noqa: E731
                      "trust": r["trust"], "type": r["label"]["type"], "category": r["label"]["category"],
                      "importance": r["label"]["importance"], "sentiment": r["label"]["sentiment"], "link": r["link"]}
    dates = sorted(r["published_at"] for r in rows)
    notes = ["Headlines only (no article bodies). Recent news from Yahoo Finance's search endpoint; "
             "the window is short and not a full history.",
             f"{dropped} loosely related headline(s) left out as not about {ticker}."]
    if n < 5:
        notes.append(f"Only {n} headlines: too few for conclusions.")
    return Digest(ticker, n, f"{dates[0][:10]} to {dates[-1][:10]}", len(pred) / n, len(low) / n, len(hype) / n,
                  sent, cats, [slim(r) for r in sorted([r for r in rows if r not in pred], key=key)[:5]],
                  [slim(r) for r in sorted(pred, key=key)[:5]], classifier.name, notes)


def recent_headlines(ticker: str, max_age_hours: float = 12.0, count: int = 20, search=None) -> list[dict]:
    """Headlines for a ticker from the local cache if fresh enough, otherwise fetched and cached."""
    from datetime import timedelta
    path = NEWS_DIR / "cache" / f"{ticker}.jsonl"
    if path.exists():
        rows = load_jsonl(path)
        if rows and datetime.fromisoformat(rows[0]["retrieved_at"]) > datetime.now(timezone.utc) - timedelta(hours=max_age_hours):
            return rows
    rows = [h.to_dict() for h in fetch_headlines(ticker, count, search)]
    save_jsonl(rows, path)
    return rows


# ----------------------------------------------------------------------------- article texts


def read_texts(headlines: list[dict], fetcher=None, max_fetch: int = 5) -> dict:
    """Try to read the article behind each headline (robots.txt respected, see ``webtext``).

    Returns per-headline status and, for texts that could be read, the share of sentences that are forecasts
    and the sentences that mention the asset. Only texts that were actually read can be used as evidence.
    """
    from . import macro_news, webtext
    fetcher = fetcher or webtext.Fetcher()
    rows, fetched = [], 0
    for h in headlines:
        link = h.get("link") or ""
        if not link:
            rows.append({"id": h["id"], "status": "too_short", "status_label": webtext.STATUS_TEXT["too_short"]})
            continue
        ok, why = fetcher.allowed(webtext.normalize(link))
        if not ok:
            rows.append({"id": h["id"], "status": "robots_disallow", "status_label": webtext.STATUS_TEXT["robots_disallow"],
                         "reason": why})
            continue
        if fetched >= max_fetch:
            rows.append({"id": h["id"], "status": "not_attempted", "status_label": "not read (per-search limit)"})
            continue
        page = fetcher.get(link)
        fetched += 1
        row = {"id": h["id"], "status": page.status, "status_label": page.status_label, "reason": page.reason}
        if page.ok:
            sents = macro_news.sentences(page.text)
            words = NAME_KEYWORDS.get(h.get("ticker", ""), []) + [h.get("ticker", "").split(".")[0]]
            about = [s for s in sents if any(re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", s, re.I)
                                             for w in words if w)]
            row.update({"chars": len(page.text), "sentences": len(sents),
                        "forward_share": sum(bool(macro_news.FORWARD.search(s)) for s in sents) / max(len(sents), 1),
                        "quotes": about[:2]})
        rows.append(row)
    n = len(rows)
    read = sum(r["status"] == "ok" for r in rows)
    blocked = sum(r["status"] == "robots_disallow" for r in rows)
    hosts = sorted({re.sub(r"^https?://([^/]+).*$", r"\1", h.get("link") or "") for h in headlines
                    if h.get("link")})
    note = (f"Article text read for {read} of {n} headlines."
            + (f" {blocked} cannot be read: the site ({', '.join(hosts)}) does not allow automated analysis by AI "
               "agents. These headlines are context only, never evidence." if blocked else ""))
    return {"rows": rows, "n": n, "read": read, "blocked": blocked, "note": note}
