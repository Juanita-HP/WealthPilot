"""Official news: polite fetching, text extraction, analysis, portfolio exposure. Offline (fake sites)."""

import copy

import pandas as pd
import pytest

from tests.conftest import requires_starter
from wealthpilot import macro_news as mn
from wealthpilot import news, webtext

YAHOO_ROBOTS = b"""User-agent: ClaudeBot
User-agent: anthropic-ai
User-agent: GPTBot
Disallow: /

User-agent: *
Disallow: /m/
"""
OPEN_ROBOTS = b"User-agent: *\nDisallow: /wp-admin/\nCrawl-delay: 2\n"

BOC_TEXT = (
    "The Bank of Canada today increased its target for the overnight rate by 25 basis points to 2.5%, with the Bank "
    "Rate at 2.75% and the deposit rate at 2.45%. Global financial conditions have tightened since July. Advanced "
    "economy sovereign bond yields are higher. Given persistently high oil prices, CPI inflation has been around 3% "
    "since April and is expected to rise to about 3½% by the end of the year. The Canadian economy is expected to "
    "grow 1% in 2026. The next scheduled date for announcing the overnight rate target is December 9, 2026.")
BOC_HTML = f"""<html><head><title>BoC</title><script>var x=1;</script></head><body>
<nav><ul><li>Home</li><li>Markets</li></ul></nav><header>Bank of Canada</header>
<main><h1>Bank of Canada raises the policy rate by 25 basis points to 2½%</h1>
{''.join(f'<p>{s}.</p>' for s in BOC_TEXT.rstrip('.').split('. '))}
<p>For media inquiries, please contact us.</p></main><footer>All rights reserved</footer></body></html>"""
FED_TEXT = ("The Federal Open Market Committee approved the following statement. The Committee decided to maintain the "
            "target range for the federal funds rate at 3-3/4 to 4 percent, in support of the Federal Reserve's dual "
            "mandate. Inflation remains elevated. Economic activity is expanding at a strong pace.")
CPI_TEXT = ("The Consumer Price Index (CPI) rose 3.1% year over year in September, following a 3.0% increase in "
            "August. Gasoline prices rose 12.0% year over year. Excluding gasoline, prices rose 2.2%. Prices for "
            "food rose 3.4%.")
CPI_UP_TEXT = CPI_TEXT.replace("following a 3.0% increase", "following a 2.6% increase")
LFS_TEXT = ("Employment was little changed in October. The unemployment rate rose 0.2 percentage points to 6.7%. "
            "The employment rate fell 0.1 percentage points. Total hours worked were unchanged.")


class FakeWeb:
    """Serves robots.txt and pages from dictionaries; records requests."""

    def __init__(self, robots: dict, pages: dict):
        self.robots, self.pages, self.calls = robots, pages, []

    def __call__(self, url, headers):
        self.calls.append(url)
        host = "/".join(url.split("/")[:3])
        if url.endswith("/robots.txt"):
            r = self.robots.get(host)
            if isinstance(r, int):
                return r, "text/plain", b""
            return (200, "text/plain", r) if r is not None else (404, "text/html", b"")
        if url in self.pages:
            return 200, "text/html; charset=utf-8", self.pages[url].encode()
        return 404, "text/html", b""


def fetcher(web, tmp_path=None):
    return webtext.Fetcher(cache_dir=tmp_path, opener=web, sleep=lambda s: None)


# ----------------------------------------------------------------------------- fetching and extraction


def test_sites_that_exclude_ai_agents_are_not_read():
    web = FakeWeb({"https://finance.yahoo.com": YAHOO_ROBOTS}, {"https://finance.yahoo.com/news/a.html": BOC_HTML})
    page = fetcher(web).get("https://finance.yahoo.com/news/a.html")
    assert page.status == "robots_disallow" and "ClaudeBot" in page.reason
    assert "https://finance.yahoo.com/news/a.html" not in web.calls, "the page itself must never be requested"


@pytest.mark.parametrize("robots, expected", [(403, "robots_disallow"), (None, "ok"), (OPEN_ROBOTS, "ok")])
def test_robots_rules(robots, expected):
    url = "https://www.bankofcanada.ca/2026/10/fad/"
    web = FakeWeb({"https://www.bankofcanada.ca": robots}, {url: BOC_HTML})
    assert fetcher(web).get(url).status == expected


def test_extraction_keeps_article_and_drops_boilerplate():
    title, text = webtext.extract(BOC_HTML)
    assert title.startswith("Bank of Canada raises")
    assert "increased its target for the overnight rate" in text
    for junk in ("var x", "Home", "media inquiries", "All rights reserved"):
        assert junk not in text


def test_paywall_and_short_pages_are_flagged(tmp_path):
    url = "https://news.example.com/a"
    pw = "<main><p>Subscribe to continue reading this article about the economy today.</p></main>"
    web = FakeWeb({"https://news.example.com": OPEN_ROBOTS}, {url: pw})
    assert fetcher(web, tmp_path).get(url).status == "paywall"


def test_cache_avoids_second_download(tmp_path):
    url = "https://www.bankofcanada.ca/2026/10/fad/"
    web = FakeWeb({"https://www.bankofcanada.ca": OPEN_ROBOTS}, {url: BOC_HTML})
    f = fetcher(web, tmp_path)
    assert f.get(url).ok
    n = len(web.calls)
    assert webtext.Fetcher(cache_dir=tmp_path, opener=web).get(url).ok
    assert len(web.calls) == n


def test_statcan_links_are_rewritten_to_the_allowed_host():
    assert webtext.normalize("https://www.statcan.gc.ca/daily-quotidien/261113/dq261113a-eng.htm") == \
        "https://www150.statcan.gc.ca/n1/daily-quotidien/261113/dq261113a-eng.htm"


def test_ticker_headlines_report_why_text_is_missing():
    web = FakeWeb({"https://finance.yahoo.com": YAHOO_ROBOTS}, {})
    hs = [{"id": "1", "ticker": "NVDA", "title": "Nvidia news", "link": "https://finance.yahoo.com/x.html"}]
    out = news.read_texts(hs, fetcher(web))
    assert out["read"] == 0 and out["blocked"] == 1
    assert "finance.yahoo.com" in out["note"] and "preuve" in out["note"]


# ----------------------------------------------------------------------------- feeds


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><item><title>Federal Reserve issues FOMC statement</title>
<link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm]]></link>
<pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item></channel></rss>"""
RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item rdf:about="x"><title>Bank of Canada raises the policy rate</title><link>https://www.bankofcanada.ca/2026/10/fad/</link>
<dc:date>2026-10-28T13:45:00+00:00</dc:date></item></rdf:RDF>"""
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Consumer Price Index, <span>September 2026</span></div></title>
<link href="https://www.statcan.gc.ca/daily-quotidien/261019/dq261019a-eng.htm"/><updated>2026-10-19T08:30:00-04:00</updated></entry>
<entry><title type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">Sawmills, August 2026</div></title>
<link href="https://www.statcan.gc.ca/daily-quotidien/261019/dq261019b-eng.htm"/><updated>2026-10-19T08:30:00-04:00</updated></entry>
</feed>"""


def test_parse_three_feed_formats_and_keep_major_releases():
    fed = mn.parse_feed(RSS, mn.FEEDS[1])
    boc = mn.parse_feed(RDF, mn.FEEDS[0])
    sc = mn.parse_feed(ATOM, mn.FEEDS[2])
    assert fed[0].published_at == "2026-10-28T18:00:00+00:00" and fed[0].link.endswith("monetary20261028a.htm")
    assert boc[0].title.startswith("Bank of Canada") and boc[0].published_at.startswith("2026-10-28")
    assert [i.title for i in sc] == ["Consumer Price Index, September 2026"], "minor releases are left out"
    assert sc[0].published_at == "2026-10-19T12:30:00+00:00"


# ----------------------------------------------------------------------------- text analysis


def test_boc_decision_is_read_with_its_sentence():
    a = mn.analyze_text(BOC_TEXT)
    d = a.decision
    assert (d["kind"], d["direction"], d["value"]) == ("policy_rate", "up", 2.5)
    assert d["sentence"] in BOC_TEXT
    assert a.main_factors[0] == "rates" and a.importance == 5
    assert all(q["text"] in BOC_TEXT for q in a.key_quotes), "quotes are exact sentences of the text"
    assert not any("next scheduled" in q["text"] for q in a.key_quotes)
    forecast = [q for q in a.key_quotes if "expected to rise" in q["text"]]
    assert not forecast or forecast[0]["kind"] == "forecast"


def test_fed_hold_with_fractions():
    d = mn.analyze_text(FED_TEXT).decision
    assert (d["kind"], d["direction"], d["value"]) == ("policy_rate", "unchanged", 4.0)


@pytest.mark.parametrize("text, direction", [(CPI_TEXT, "unchanged"), (CPI_UP_TEXT, "up")])
def test_cpi_direction_is_acceleration_not_level(text, direction):
    d = mn.analyze_text(text).decision
    assert d["kind"] == "cpi" and d["value"] == 3.1 and d["direction"] == direction


def test_unemployment_value_across_decimals():
    d = mn.analyze_text(LFS_TEXT).decision
    assert (d["kind"], d["direction"], d["value"]) == ("unemployment", "up", 6.7)


def test_text_without_economic_content_is_not_news_for_the_portfolio():
    a = mn.analyze_text("The Bank unveiled a new vertical $20 bank note featuring a portrait. "
                        "The note will enter circulation next year. It includes new security features.")
    assert a.decision is None and a.main_factors == [] and a.importance == 1


def test_french_fact_sentences():
    item = {"publisher": "Bank of Canada", "region": "CA", "title": "", "analysis": mn.analyze_text(BOC_TEXT).to_dict()}
    assert mn.fact_fr(item) == "La Banque du Canada a relevé son taux directeur à 2,5 %."
    item = {"publisher": "Statistics Canada", "region": "CA", "title": "", "analysis": mn.analyze_text(CPI_TEXT).to_dict()}
    assert "3,1 %" in mn.fact_fr(item) and "stable" in mn.fact_fr(item)


# ----------------------------------------------------------------------------- portfolio exposure


@pytest.fixture
def universe():
    return pd.DataFrame({
        "name": ["TSX 60", "S&P 500", "Canada bonds", "US bonds", "Ultra short", "Gold", "Enbridge", "Royal Bank"],
        "asset_class": ["etf_equity", "etf_equity", "etf_bond", "etf_bond", "etf_bond", "etf_commodity", "equity", "equity"],
        "currency": ["CAD", "USD", "CAD", "USD", "CAD", "USD", "CAD", "CAD"],
        "sector": ["Broad market (Canada)", "Broad market (U.S.)", "Bonds (Canada aggregate)", "Bonds (U.S. aggregate)",
                   "Bonds (Canada ultra short-term)", "Gold", "Energy", "Financials"],
    }, index=pd.Index(["XIU.TO", "SPY", "XBB.TO", "AGG", "ZST.TO", "GLD", "ENB.TO", "RY.TO"], name="ticker"))


BALANCED = {"XIU.TO": 0.2, "SPY": 0.2, "XBB.TO": 0.35, "AGG": 0.1, "ZST.TO": 0.1, "GLD": 0.05}


def test_canadian_rate_news_exposure(universe):
    ex = mn.exposure(BALANCED, universe, "rates", "CA")
    by = {x["ticker"]: x["channel"] for x in ex["lines"]}
    assert by["XBB.TO"] == "direct" and by["AGG"] == "indirect" and by["ZST.TO"] == "indirect"
    assert "SPY" not in by
    assert ex["share_direct"] == pytest.approx(0.35)
    assert ex["share_direct"] + ex["share_indirect"] + ex["share_unexposed"] == pytest.approx(1.0)


def test_currency_exposure_is_everything_in_us_dollars(universe):
    ex = mn.exposure(BALANCED, universe, "currency", "US")
    assert ex["share_direct"] == pytest.approx(0.35)       # SPY, AGG, GLD


def _item(text, publisher="Bank of Canada", region="CA", at="2026-10-28T14:00:00+00:00"):
    return {"id": at, "source": "x", "publisher": publisher, "region": region, "title": "t", "link": "https://x",
            "published_at": at, "text_status": "ok", "text_status_fr": "texte lu", "text_chars": len(text),
            "analysis": mn.analyze_text(text).to_dict(), "retrieved_at": at}


def test_impact_message_dedupe_and_purity(universe):
    items = [_item(BOC_TEXT), _item(BOC_TEXT.replace("increased", "maintained").replace(" by 25 basis points", ""),
                                    at="2026-09-02T14:00:00+00:00"),
             _item(FED_TEXT, "Federal Reserve", "US")]
    w = dict(BALANCED)
    out = mn.impact(w, universe, items)
    assert w == BALANCED, "news never change the allocation"
    boc = [r for r in out["items"] if r["publisher"] == "Bank of Canada"]
    assert len(boc) == 1 and boc[0]["decision"]["direction"] == "up", "only the latest decision of a kind is kept"
    assert "35 %" in boc[0]["message"] and "diversification" in boc[0]["note"]
    assert out["n_text_read"] == 3


def test_concentrated_portfolio_is_flagged(universe):
    out = mn.impact({"XBB.TO": 0.8, "XIU.TO": 0.2}, universe, [_item(BOC_TEXT)])
    assert out["items"][0]["concentrated"] and "moitié" in out["items"][0]["note"]


def test_rate_hike_suggests_rate_stress_test(universe):
    out = mn.impact(BALANCED, universe, [_item(BOC_TEXT)], amount=10_000)
    st = out["items"][0]["stress"]
    assert st["scenario"] == "rates_up_1pt"
    assert st["dollars"] < 0 and st["portfolio_return"] > -0.07   # ZST barely moves, gold and equities a little


@requires_starter
def test_analogs_from_real_rate_history():
    from wealthpilot import data
    px = data.load_prices_cad()
    a = mn.analogs("policy_rate", "up", "CA", ["XBB.TO", "SPY"], px)
    assert a is not None and a["n_events"] >= 5
    assert {r["verdict"] for r in a["rows"]} <= {"clear", "unclear", "too_few"}
    assert "pas une prévision" in a["caveat"]


@requires_starter
def test_advocate_shows_rising_dependence_on_a_news_factor():
    from tests.test_profile import MATEO
    from wealthpilot import advocate as adv, data, profile as pf, strategist as st
    px, u = data.load_prices_cad(), data.load_universe()
    mateo = pf.build_profile(MATEO)
    current = st.policy_allocation(mateo, px).weights
    rv = adv.review_trade("TLT", 0.40, current, mateo, px, u, macro_items=[_item(FED_TEXT, "Federal Reserve", "US")])
    ch = next(c for c in rv.challenges if c.code == "NEWS_EXPOSURE")
    assert ch.evidence["after"] > ch.evidence["before"] + 0.1 and "Fed" in ch.claim


def test_agent_tool_is_registered():
    from wealthpilot.agents import tools as tl
    t = tl.TOOL_BY_NAME["macro_news_impact"]
    assert {"advisor", "advocate"} <= t.agents
    assert copy.deepcopy(t)  # plain data, no live connection at import time


def test_llm_analyzer_drops_quotes_not_in_the_text():
    from types import SimpleNamespace

    class FakeLLM:
        def create(self, system, messages, tools, effort=None):
            assert "record_analysis" == tools[0]["name"] and "EXACTLY" in system
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={
                "decision_kind": "policy_rate", "direction": "up", "value": 2.5, "main_factors": ["rates", "inflation"],
                "quotes": [{"text": "The Bank of Canada today increased its target for the overnight rate by 25 basis "
                                    "points to 2.5%, with the Bank Rate at 2.75% and the deposit rate at 2.45%.",
                            "kind": "fact"},
                           {"text": "The Bank promised to cut rates next year.", "kind": "forecast"}]})])

    a = mn.LLMTextAnalyzer(FakeLLM()).analyze(BOC_TEXT)
    assert a.analyzer == "claude-macro-v1" and a.decision["direction"] == "up"
    assert [q["text"] for q in a.key_quotes] == [a.decision["sentence"]], "invented quote removed"
