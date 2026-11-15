// Search page (template): autocomplete from Yahoo, keyboard navigation, ticker verification, invalid-search shake.
// Any kind of investment (stocks, ETFs, funds, crypto, currencies), plus popular investments and today's biggest
// moves with their daily charts.
import { useEffect, useRef, useState } from "react";
import { YAHOO, api, fmt, num, requestJSON, resolveTicker, signedPct, verifyTicker, go } from "../lib.js";

const KINDS = { EQUITY: "Stock", ETF: "ETF", MUTUALFUND: "Fund", CRYPTOCURRENCY: "Crypto", CURRENCY: "Currency" };
const WORDS = ["a company.", "an ETF.", "a crypto.", "a currency.", "a fund."];

// Types one word, erases it, types the next. With reduced motion, the words simply change.
function useTypewriter(words) {
  const [text, setText] = useState(words[0]);
  useEffect(() => {
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let i = 0, n = words[0].length, deleting = false, timer;
    const tick = () => {
      if (reduce) { i = (i + 1) % words.length; setText(words[i]); timer = setTimeout(tick, 2600); return; }
      const word = words[i];
      if (!deleting && n === word.length) { deleting = true; timer = setTimeout(tick, 1900); return; }
      if (deleting && n === 0) { deleting = false; i = (i + 1) % words.length; timer = setTimeout(tick, 250); return; }
      n += deleting ? -1 : 1;
      setText(words[i].slice(0, n));
      timer = setTimeout(tick, deleting ? 45 : 85);
    };
    timer = setTimeout(tick, 1900);
    return () => clearTimeout(timer);
  }, [words]);
  return text;
}

// Latest trading day, 5-minute prices; dashed line at the previous day's last price.
export function Sparkline({ points, previous, up }) {
  if (!points?.length) return <div className="spark empty" />;
  const values = num(previous) ? [...points, previous] : points;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const w = 160, h = 48, x = i => (points.length === 1 ? w / 2 : (i / (points.length - 1)) * w), y = v => h - 3 - ((v - lo) / span) * (h - 6);
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      {num(previous) && <line x1="0" x2={w} y1={y(previous)} y2={y(previous)} className="spark-base" />}
      <polyline points={points.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} className={up ? "spark-up" : "spark-down"} />
    </svg>
  );
}

// Currency pairs: CAD=X is U.S. dollars in Canadian dollars; EURCAD=X is euros in Canadian dollars.
const label = sym => {
  if (!sym.endsWith("=X")) return sym;
  const p = sym.slice(0, -2);
  return p.length === 3 ? "USD/" + p : p.slice(0, 3) + "/" + p.slice(3);
};

function MarketCard({ c }) {
  const up = (c.change ?? 0) >= 0;
  return (
    <button type="button" className="market-card" onClick={() => go("stocks", c.symbol)}>
      <div className="market-top">
        <div><strong>{label(c.symbol)}</strong><small>{c.name}</small></div>
        <span className="type-badge">{c.type}</span>
      </div>
      <Sparkline points={c.points} previous={c.previous} up={up} />
      <div className="market-bottom">
        <span>{fmt(c.price)}{c.currency ? " " + c.currency : ""}</span>
        <b className={up ? "up" : "down"}>{num(c.change) ? signedPct(c.change, 2) : "—"}</b>
      </div>
      {num(c.relative_volume) && c.relative_volume >= 1.5 && <small className="muted">Volume {c.relative_volume.toFixed(1)}× its recent days</small>}
    </button>
  );
}

function MarketSection({ title, sub, cards }) {
  if (!cards?.length) return null;
  return (
    <section className="market-section">
      <div className="market-head"><h2>{title}</h2>{sub && <p>{sub}</p>}</div>
      <div className="market-grid">{cards.map(c => <MarketCard key={c.symbol} c={c} />)}</div>
    </section>
  );
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [selected, setSelected] = useState(-1);
  const [status, setStatus] = useState({ text: "", error: false });
  const [invalid, setInvalid] = useState(0);
  const [profile, setProfile] = useState(null);
  const tokens = useRef({ search: 0, submit: 0 });
  const abort = useRef(null);
  const form = useRef(null);

  const [overview, setOverview] = useState(null);
  const word = useTypewriter(WORDS);

  useEffect(() => { api("/profile").then(setProfile).catch(() => {}); }, []);
  useEffect(() => { api("/markets/overview").then(setOverview).catch(() => setOverview({ failed: true })); }, []);

  useEffect(() => {
    tokens.current.search++;
    tokens.current.submit++;
    setSuggestions([]);
    setSelected(-1);
    const q = query.trim();
    if (!q) { setStatus({ text: "", error: false }); return; }
    const timer = setTimeout(async () => {
      const token = ++tokens.current.search;
      if (abort.current) abort.current.abort();
      abort.current = new AbortController();
      try {
        const url = YAHOO + "/v1/finance/search?" + new URLSearchParams({ q, quotesCount: "30", newsCount: "0" });
        const data = await requestJSON(url, abort.current.signal);
        if (token !== tokens.current.search) return;
        const seen = new Set();
        const list = (data.quotes || [])
          .filter(x => {
            if (!x.symbol || !KINDS[x.quoteType]) return false;
            const symbol = x.symbol.toUpperCase();
            if (seen.has(symbol)) return false;
            seen.add(symbol);
            return true;
          })
          .map(x => ({ symbol: x.symbol.toUpperCase(), name: x.longname || x.shortname || x.symbol, exchange: x.exchDisp || x.exchange || "",
                       type: KINDS[x.quoteType] }))
          .sort((a, b) => {
            const Q = q.toUpperCase();
            const score = item => (item.symbol === Q ? 100 : 0) + (item.symbol === Q + ".TO" ? 120 : 0) + (item.symbol.startsWith(Q) ? 30 : 0);
            return score(b) - score(a);
          })
          .slice(0, 8);
        setSuggestions(list);
        setStatus({ text: list.length ? "" : "No matching investments found.", error: false });
      } catch (err) {
        if (token !== tokens.current.search || err.name === "AbortError") return;
        setStatus({ text: "Search suggestions unavailable. Enter a ticker directly.", error: false });
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [query]);

  const open = (symbol) => go("stocks", symbol);

  const onKeyDown = e => {
    if (e.key === "Escape") { setSuggestions([]); setSelected(-1); return; }
    if (!suggestions.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setSelected((selected + 1) % suggestions.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSelected((selected - 1 + suggestions.length) % suggestions.length); }
  };

  const onSubmit = async e => {
    e.preventDefault();
    const q = query.trim().toUpperCase();
    if (!q) return;
    const id = ++tokens.current.submit;
    const pick = selected >= 0 ? suggestions[selected] : suggestions.find(x => x.symbol === q);
    setSuggestions([]);
    setSelected(-1);
    setStatus({ text: "Checking...", error: false });
    try {
      const result = pick ? await verifyTicker(pick.symbol) : await resolveTicker(q);
      if (id !== tokens.current.submit) return;
      setStatus({ text: "", error: false });
      open(result.symbol);
    } catch {
      if (id !== tokens.current.submit) return;
      setInvalid(n => n + 1);
      setStatus({ text: "Not found. Check the symbol (for example AAPL, XIU.TO, BTC-USD, CAD=X).", error: true });
    }
  };

  // Restart the shake animation on every failed search.
  useEffect(() => {
    if (!invalid || !form.current) return;
    form.current.classList.remove("invalid");
    void form.current.offsetWidth;
    form.current.classList.add("invalid");
  }, [invalid]);

  const p = profile?.profile;
  return (
    <section id="home">
      <h1 aria-label="Research a company, an ETF, a crypto asset, a currency or a fund.">
        <span aria-hidden="true">Research <span className="typed">{word}</span><span className="caret" /></span>
      </h1>
      <div className="searchbox">
        <form className="searchform" ref={form} onSubmit={onSubmit}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="10.8" cy="10.8" r="7.2" />
            <path d="m16.2 16.2 5 5" />
          </svg>
          <input placeholder="Search a company, ETF, crypto or currency" autoComplete="off" spellCheck="false" value={query}
                 onChange={e => { form.current?.classList.remove("invalid"); setStatus({ text: "", error: false }); setQuery(e.target.value); }}
                 onKeyDown={onKeyDown} onBlur={() => setTimeout(() => setSuggestions([]), 150)} />
          <button type="submit">→</button>
        </form>
        {suggestions.length > 0 && (
          <div className="suggestions">
            {suggestions.map((item, i) => (
              <div key={item.symbol} className={"suggestion" + (i === selected ? " active" : "")}
                   onMouseDown={e => { e.preventDefault(); tokens.current.submit++; open(item.symbol); }}>
                <div><strong>{item.symbol}</strong><small>{item.name}</small></div>
                <em>{item.type} · {item.exchange}</em>
              </div>
            ))}
          </div>
        )}
      </div>
      <div id="searchStatus" className={status.error ? "error" : ""}>{status.text}</div>
      {p && (
        <button className="profile-pill" onClick={() => go("profile")}>
          {p.name} profile · {p.score_10}/10 risk · Click to view or edit your answers
        </button>
      )}
      <div className="markets">
        {!overview && <div className="analysis-status">Loading markets…</div>}
        {overview?.failed && <div className="analysis-status">Market overview unavailable right now. Search still works.</div>}
        <MarketSection title="Popular investments" sub="Widely held funds, crypto, gold and the U.S. dollar. Latest trading day." cards={overview?.popular} />
        <MarketSection title="Trending today" sub={overview?.rule} cards={overview?.trending} />
        {overview && !overview.failed && <p className="note">Prices from Yahoo Finance, may be delayed. Click a card to see its details, as if you had searched it.</p>}
      </div>
    </section>
  );
}
