import numpy as np
import pandas as pd
import pytest

from tests.conftest import requires_starter
from tests.test_profile import AMIRA, MATEO, ROBERT
from wealthpilot import advocate as adv
from wealthpilot import lab
from wealthpilot import profile as pf
from wealthpilot.exposure import pct


def codes(review):
    return {c.code for c in review.challenges}


def test_pct_formatting():
    assert pct(0.075) == "7.5%" and pct(0.10) == "10%"


def test_recency_evidence_rank_correlation():
    idx = pd.bdate_range("2020-01-01", "2023-12-31")
    years = idx.year - 2020
    # asset i grows by i% per year in 2020-2021 and by -i% after: rankings flip
    cols = {f"A{i}": 100 * np.exp(np.where(years < 2, i, -i) * 0.01 * (idx.dayofyear / 365 + years)) for i in range(12)}
    px = pd.DataFrame(cols, index=idx)
    rec = adv.recency_evidence(px)
    assert rec["assets"] == 12 and rec["pairs"]


def test_review_lab_turns_findings_into_challenges():
    idx = pd.bdate_range("2020-01-01", periods=900)
    close = pd.Series(100 * np.cumprod(1 + np.random.default_rng(5).normal(0.0003, 0.015, 900)), index=idx)
    res = lab.evaluate(close, "rsi", "TEST", params={"window": 14, "lower": 0, "upper": 70})
    rv = adv.review_lab(res)
    assert "NO_POSITION_OOS" in codes(rv)
    assert all(c.question for c in rv.challenges)


@requires_starter
def test_robert_tsla_request_is_challenged_with_honest_counterpoint():
    from wealthpilot import data, strategist as st
    px, u = data.load_prices_cad(), data.load_universe()
    rob = pf.build_profile(ROBERT)
    rv = adv.review_trade("TSLA", 0.30, st.policy_allocation(rob, px).weights, rob, px, u)
    assert rv.verdict == "reconsider"
    assert {"SINGLE_SECURITY", "RISK_JUMP", "HORIZON_MISMATCH"} <= codes(rv)
    jump = next(c for c in rv.challenges if c.code == "RISK_JUMP")
    after, before = rv.before_after["after"], rv.before_after["before"]
    if after["cagr"] > before["cagr"]:
        assert "RAISED" in jump.counterpoint, "the advocate must not hide that the request paid off"
    assert "limit 7.5%" in next(c for c in rv.challenges if c.code == "SINGLE_SECURITY").claim


@requires_starter
def test_small_quality_position_is_not_blocked():
    from wealthpilot import data, strategist as st
    px, u = data.load_prices_cad(), data.load_universe()
    mateo = pf.build_profile(MATEO)
    rv = adv.review_trade("RY.TO", 0.05, st.policy_allocation(mateo, px).weights, mateo, px, u)
    assert rv.verdict != "reconsider"


@requires_starter
def test_system_critiques_its_own_allocation():
    from wealthpilot import data, strategist as st
    px, u = data.load_prices_cad(), data.load_universe()
    ami = pf.build_profile(AMIRA, pf.Preferences(crypto="open", themes=("Information Technology",)))
    rv = adv.review_allocation(st.policy_allocation(ami, px).weights, ami, px, u)
    assert "HIDDEN_CONCENTRATION" in codes(rv)          # QQQ and SPY
    assert not any(c.severity == "warning" for c in rv.challenges)  # but within the profile


@requires_starter
def test_recent_news_warning_scales_with_the_profile():
    from wealthpilot import data
    px = data.load_prices_cad()
    digest = {"n": 6, "classifier": "rules-v3", "top_descriptive": [
        {"title": "Board ousts the CEO", "publisher": "Reuters", "published_at": "2026-11-13T12:00:00+00:00",
         "trust": 0.85, "category": "management", "importance": 3},
        {"title": "Blog post about the stock", "publisher": "Some blog", "published_at": "2026-11-13T12:00:00+00:00",
         "trust": 0.3, "category": "management", "importance": 3}]}
    cautious = adv.recent_news_challenge("NVDA", pf.build_profile(ROBERT), px, digest)
    bold = adv.recent_news_challenge("NVDA", pf.with_level(pf.build_profile(AMIRA), 4, "t") if pf.build_profile(AMIRA).level >= 4
                                     else pf.build_profile(AMIRA), px, digest)
    assert cautious.severity == "warning" and "prudent" in cautious.claim
    assert "Board ousts the CEO" in cautious.claim and "Blog post" not in cautious.claim, "low-trust sources are left out"
    assert "headlines" in cautious.counterpoint and "which way" in cautious.counterpoint
    assert bold.claim != cautious.claim


def test_no_recent_news_warning_without_signal():
    idx = pd.bdate_range("2024-01-01", periods=400)
    calm = pd.DataFrame({"AAA": 100 * np.cumprod(1 + np.full(400, 0.0005) + np.random.default_rng(1).normal(0, 0.01, 400))}, index=idx)
    assert adv.recent_news_challenge("AAA", pf.build_profile(ROBERT), calm, {"n": 0}) is None
