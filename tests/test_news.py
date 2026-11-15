from types import SimpleNamespace

import pytest

from tests.conftest import requires_starter
from tests.test_profile import ROBERT
from wealthpilot import news


def h(title, ticker="TSLA", publisher="Reuters", at="2026-11-10T12:00:00+00:00"):
    t, tier = news.trust(publisher)
    return {"id": title[:20], "ticker": ticker, "title": title, "publisher": publisher, "published_at": at,
            "link": "", "related": [ticker], "retrieved_at": "2026-11-14T00:00:00+00:00", "trust": t, "tier": tier}


def test_trust_tiers():
    assert news.trust("Business Wire")[1] == "official"
    assert news.trust("Reuters")[0] > news.trust("Motley Fool")[0]
    assert news.trust("Unknown Blog")[1] == news.DEFAULT_TIER


@pytest.mark.parametrize("title, expected", [
    ("Tesla Reports Third Quarter Results", "descriptive"),
    ("Is Tesla Stock a Buy Now?", "predictive"),
    ("Tesla Could Soar 50%, Analyst Says", "predictive"),
    ("Tesla Opens Cybercab Pre-Orders", "descriptive"),
])
def test_rule_classifier_types(title, expected):
    assert news.RuleClassifier().classify(h(title)).type == expected


def test_relevance_uses_company_names():
    assert news.is_relevant(h("Tesla Opens Cybercab Pre-Orders"))
    assert not news.is_relevant(h("GH Research Reports Third Quarter Results", ticker="JNJ"))
    assert news.is_relevant(h("Bitcoin slips below $80,000", ticker="BTC-USD"))


def test_digest_point_in_time_and_hype():
    rows = [h("Tesla Could Soar 50%", publisher="Motley Fool", at="2026-11-01T00:00:00+00:00"),
            h("Why Tesla Stock Will Double", publisher="Stocktwits", at="2026-11-02T00:00:00+00:00"),
            h("Is Tesla a Buy Before Earnings?", publisher="Zacks", at="2026-11-03T00:00:00+00:00"),
            h("Tesla Reports Deliveries", publisher="Reuters", at="2026-11-04T00:00:00+00:00"),
            h("Tesla Recalls 10,000 Vehicles", publisher="Associated Press", at="2026-11-05T00:00:00+00:00"),
            h("Tesla Price Target Raised", publisher="Benzinga", at="2026-11-20T00:00:00+00:00")]
    d = news.digest("TSLA", rows, as_of="2026-11-10T00:00:00+00:00")
    assert d.n == 5                                   # the Nov 20 headline did not exist yet
    assert d.hype_share == pytest.approx(3 / 5)
    assert d.top_descriptive[0]["publisher"] in {"Reuters", "Associated Press"}


def test_fetch_headlines_with_fake_search():
    fake = lambda q, n: [{"uuid": "u1", "title": "Tesla opens orders", "publisher": "TechCrunch",  # noqa: E731
                          "providerPublishTime": 1794686684, "link": "x", "relatedTickers": ["TSLA"]},
                         {"title": None, "providerPublishTime": 1}]
    rows = news.fetch_headlines("TSLA", 5, search=fake)
    assert len(rows) == 1 and rows[0].tier == "media" and rows[0].published_at.startswith("2026-11")


def test_llm_classifier_parses_tool_call():
    class FakeLLM:
        def create(self, system, messages, tools, effort=None):
            assert tools[0]["name"] == "record_label" and "Headline:" in messages[0]["content"]
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="record_label", id="t", input={
                "type": "predictive", "category": "analyst_rating", "sentiment": 3.0, "importance": 2,
                "relevant": True, "reason": "asks whether to buy"})], stop_reason="tool_use")
    lab = news.LLMClassifier(FakeLLM(), "v2").classify(h("Is Tesla a Buy?"))
    assert lab.type == "predictive" and lab.sentiment == 1.0 and lab.classifier == "claude-prompt-v2"


def test_evaluate_and_example_exclusion():
    golden = news.load_jsonl(news.NEWS_DIR / "golden_v0.jsonl")
    full = news.evaluate(news.RuleClassifier(), golden)
    assert full["n"] == 64 and 0 <= full["type_accuracy"] <= 1
    prompt = (news.PROMPTS_DIR / "v2.md").read_text()
    assert news.evaluate(news.RuleClassifier(), golden, exclude_text=prompt)["n"] < 64


@requires_starter
def test_hype_challenge_in_advocate():
    from wealthpilot import advocate, data, profile as pf, strategist
    px, u = data.load_prices_cad(), data.load_universe()
    rob = pf.build_profile(ROBERT)
    dg = {"n": 10, "hype_share": 0.6, "share_predictive": 0.7, "share_low_trust": 0.8, "window": "2026-11-01 to 2026-11-14",
          "top_predictive": [{"title": "TSLA to the moon"}], "top_descriptive": [{"title": "Tesla reports deliveries"}],
          "classifier": "rules-v1"}
    rv = advocate.review_trade("TSLA", 0.05, strategist.policy_allocation(rob, px).weights, rob, px, u, news_digest=dg)
    hype = [c for c in rv.challenges if c.code == "HYPE"]
    assert hype and "Tesla reports deliveries" in hype[0].counterpoint


def test_suffixed_symbols_are_searched_by_name():
    asked = []

    def search(q, n):
        asked.append(q)
        return [{"title": "Royal Bank posts record profit", "publisher": "Reuters", "providerPublishTime": 1_763_000_000,
                 "uuid": "u1", "link": "https://x"}]
    hs = news.fetch_headlines("RY.TO", 5, search)
    assert asked == ["Royal Bank"] and hs[0].ticker == "RY.TO"
    asked.clear()
    news.fetch_headlines("BTC-USD", 5, search)
    assert asked == ["Bitcoin"]


def test_empty_search_retries_with_the_name():
    asked = []

    def search(q, n):
        asked.append(q)
        return [] if q == "AAPL" else [{"title": "Apple launches a phone", "publisher": "Reuters",
                                        "providerPublishTime": 1_763_000_000, "uuid": "u2", "link": ""}]
    hs = news.fetch_headlines("AAPL", 5, search)
    assert asked == ["AAPL", "Apple"] and hs and hs[0].ticker == "AAPL"


def test_digest_lists_esg_and_legal_controversies():
    rows = [h("Enbridge pipeline spill draws regulator fine", ticker="ENB.TO"),
            h("Enbridge faces lawsuit over oil sands emissions", ticker="ENB.TO", publisher="Bloomberg"),
            h("Enbridge raises its dividend", ticker="ENB.TO")]
    d = news.digest("ENB.TO", rows)
    titles = [c["title"] for c in d.controversies]
    assert len(titles) == 2 and "Enbridge raises its dividend" not in titles
