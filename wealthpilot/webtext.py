"""Read the text behind a news item, politely and only where the site allows it.

Two steps, as in any web scraping:

1. Download the page (``urllib``). Before that, the site's ``robots.txt`` is
   read and must allow BOTH our own user agent and the AI agents (``ClaudeBot``,
   ``anthropic-ai``), because the text is analysed by an AI model. Sites that
   exclude AI agents (Yahoo Finance does) are respected: the item keeps its
   headline and is marked "text not available". No CAPTCHA or paywall is
   bypassed, requests are spaced by the site's crawl delay, and pages are cached.
2. Extract the article text with BeautifulSoup: drop scripts, menus, headers
   and footers, keep the paragraphs of the main content, remove boilerplate.

Each result carries a status so the interface can say why a text is missing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER_AGENT = "WealthPilot/0.1 (PolyFinances datathon prototype; non-commercial; AI-assisted analysis)"
AGENT_TOKEN = "WealthPilot"
AI_TOKENS = ("ClaudeBot", "anthropic-ai")
PAGES_DIR = Path(os.environ.get("WEALTHPILOT_NEWS_DIR", Path(__file__).resolve().parent.parent / "data" / "news")) / "pages"
DEFAULT_DELAY = 1.0      # seconds between two requests to the same host
MIN_TEXT = 300           # characters; below this the page is not an article (or is paywalled)
MAX_BYTES = 3_000_000

STATUS_TEXT = {
    "ok": "text read",
    "robots_disallow": "the site does not allow automated analysis by AI agents (robots.txt)",
    "paywall": "subscribers only",
    "too_short": "no usable article text on the page",
    "http_error": "page unavailable",
    "network_error": "site unreachable",
    "not_html": "not an HTML document",
}

# Hosts that moved; following the redirect would leave the allowed network.
REWRITE = [(re.compile(r"^https?://www\.statcan\.gc\.ca/(daily-quotidien/.*)$"),
            r"https://www150.statcan.gc.ca/n1/\1")]

BOILERPLATE = re.compile(
    r"(official website of the United States|\.gov website|Share sensitive information|secure \.gov|"
    r"media inquiries|Lock Locked padlock|cookies?|Sign up for|Subscribe to|Related (articles|content)|"
    r"Follow us on|All rights reserved)", re.I)
RELATED = re.compile(r"(callout|related|teaser|promo|share|breadcrumb|newsletter|card)", re.I)
PAYWALL = re.compile(r"(subscribe to (continue|read)|subscribers only|sign in to (continue|read)|"
                     r"already a subscriber|abonnez-vous|réservé aux abonnés)", re.I)


@dataclass
class Page:
    url: str
    status: str
    title: str
    text: str
    fetched_at: str
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def status_label(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    def to_dict(self):
        return asdict(self)


def normalize(url: str) -> str:
    for rx, repl in REWRITE:
        if rx.match(url):
            return rx.sub(repl, url)
    return url


# ----------------------------------------------------------------------------- extraction


def extract(html: str, url: str = "") -> tuple[str, str]:
    """(title, text) of the main content of an HTML page."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.find("h1"):
        title = soup.find("h1").get_text(" ", strip=True)
    elif soup.title:
        title = soup.title.get_text(" ", strip=True)
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg"]):
        tag.decompose()
    # Related-content boxes, teasers and share bars sit inside the main area on many sites.
    for tag in soup.find_all(class_=RELATED):
        tag.decompose()
    root = (soup.find(id="article") or soup.find("article") or soup.find("main")
            or soup.find(attrs={"role": "main"}) or soup.body or soup)
    paras = []
    for el in root.find_all(["p", "li", "h2", "h3"]):
        if el.name == "li" and el.find_parent(["ul", "ol"]) is not None and len(el.get_text(strip=True)) < 60:
            continue  # navigation-like lists
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        t = re.sub(r"\s+([,.;:%)])", r"\1", t).replace("( ", "(")
        if len(t) < 25 or BOILERPLATE.search(t):
            continue
        if paras and t == paras[-1]:
            continue
        paras.append(t)
    return title, "\n".join(paras)


# ----------------------------------------------------------------------------- fetching


class Fetcher:
    """Downloads pages that robots.txt allows, with a per-host delay and a disk cache.

    ``opener(url, headers) -> (status_code, content_type, body_bytes)`` is injectable for tests.
    """

    def __init__(self, cache_dir: Path | None = PAGES_DIR, max_age_days: float = 7.0, opener=None,
                 sleep=time.sleep):
        self.cache_dir = cache_dir
        self.max_age = timedelta(days=max_age_days)
        self.opener = opener or _urlopen
        self.sleep = sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}

    # robots.txt -------------------------------------------------------------
    def robots(self, url: str) -> urllib.robotparser.RobotFileParser:
        parts = urllib.parse.urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        if host not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                code, _, body = self.opener(host + "/robots.txt", {"User-Agent": USER_AGENT})
            except Exception:
                code, body = 0, b""
            if code in (401, 403) or code == 0:
                rp.disallow_all = True          # cannot read the rules: do not crawl
            elif code >= 400:
                rp.allow_all = True             # no robots.txt: crawling allowed (standard)
            else:
                rp.parse(body.decode("utf-8", "ignore").splitlines())
            self._robots[host] = rp
        return self._robots[host]

    def allowed(self, url: str) -> tuple[bool, str]:
        rp = self.robots(url)
        if rp.disallow_all:
            return False, "robots.txt unreadable or disallows everything"
        blocked = [a for a in (AGENT_TOKEN, *AI_TOKENS) if not rp.can_fetch(a, url)]
        if blocked:
            return False, "robots.txt disallows " + ", ".join(blocked)
        return True, ""

    def _wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        rp = self._robots.get(f"{urllib.parse.urlsplit(url).scheme}://{host}")
        delay = DEFAULT_DELAY
        if rp is not None:
            try:
                delay = max(delay, float(rp.crawl_delay(AGENT_TOKEN) or 0))
            except (TypeError, ValueError):
                pass
        elapsed = time.monotonic() - self._last.get(host, -1e9)
        if elapsed < delay:
            self.sleep(delay - elapsed)
        self._last[host] = time.monotonic()

    # cache --------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".json")

    def _cached(self, url: str) -> Page | None:
        path = self._cache_path(url)
        if path is None or not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="cp1252", errors="replace")
        d = json.loads(raw)
        if datetime.fromisoformat(d["fetched_at"]) < datetime.now(timezone.utc) - self.max_age:
            return None
        return Page(**d)

    def _store(self, page: Page) -> Page:
        path = self._cache_path(page.url)
        if path is not None and page.status in ("ok", "robots_disallow", "paywall", "too_short"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(page.to_dict(), ensure_ascii=False), encoding="utf-8")
        return page

    # main entry -----------------------------------------------------------------
    def get(self, url: str) -> Page:
        url = normalize(url)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cached = self._cached(url)
        if cached is not None:
            return cached
        ok, why = self.allowed(url)
        if not ok:
            return self._store(Page(url, "robots_disallow", "", "", now, why))
        self._wait(url)
        try:
            code, ctype, body = self.opener(url, {"User-Agent": USER_AGENT, "Accept": "text/html"})
        except Exception as e:  # network refusal, timeout, DNS
            return Page(url, "network_error", "", "", now, type(e).__name__)
        if code >= 400:
            return Page(url, "http_error", "", "", now, f"HTTP {code}")
        if "html" not in (ctype or "html"):
            return Page(url, "not_html", "", "", now, ctype)
        html = body[:MAX_BYTES].decode("utf-8", "ignore")
        title, text = extract(html, url)
        if PAYWALL.search(html) and len(text) < 3 * MIN_TEXT:
            return self._store(Page(url, "paywall", title, "", now, "paywall wording and little text"))
        if len(text) < MIN_TEXT:
            return self._store(Page(url, "too_short", title, text, now, f"{len(text)} characters"))
        return self._store(Page(url, "ok", title, text, now))


def _urlopen(url: str, headers: dict) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", b""
