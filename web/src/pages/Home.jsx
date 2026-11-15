// Search page (template): autocomplete from Yahoo, keyboard navigation, ticker verification, invalid-search shake.
import { useEffect, useRef, useState } from "react";
import { YAHOO, api, requestJSON, resolveTicker, verifyTicker, go } from "../lib.js";

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

  useEffect(() => { api("/profile").then(setProfile).catch(() => {}); }, []);

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
            if (!x.symbol || !["EQUITY", "ETF", "MUTUALFUND"].includes(x.quoteType)) return false;
            const symbol = x.symbol.toUpperCase();
            if (seen.has(symbol)) return false;
            seen.add(symbol);
            return true;
          })
          .map(x => ({ symbol: x.symbol.toUpperCase(), name: x.longname || x.shortname || x.symbol, exchange: x.exchDisp || x.exchange || "" }))
          .sort((a, b) => {
            const Q = q.toUpperCase();
            const score = item => (item.symbol === Q ? 100 : 0) + (item.symbol === Q + ".TO" ? 120 : 0) + (item.symbol.startsWith(Q) ? 30 : 0);
            return score(b) - score(a);
          })
          .slice(0, 8);
        setSuggestions(list);
        setStatus({ text: list.length ? "" : "No matching companies found.", error: false });
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
    setStatus({ text: "Verifying stock...", error: false });
    try {
      const result = pick ? await verifyTicker(pick.symbol) : await resolveTicker(q);
      if (id !== tokens.current.submit) return;
      setStatus({ text: "", error: false });
      open(result.symbol);
    } catch {
      if (id !== tokens.current.submit) return;
      setInvalid(n => n + 1);
      setStatus({ text: "Stock not found. Check the ticker symbol.", error: true });
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
      <h1>Research a company.</h1>
      <div className="searchbox">
        <form className="searchform" ref={form} onSubmit={onSubmit}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <circle cx="10.8" cy="10.8" r="7.2" />
            <path d="m16.2 16.2 5 5" />
          </svg>
          <input placeholder="Search company or ticker" autoComplete="off" spellCheck="false" value={query}
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
                <em>{item.exchange}</em>
              </div>
            ))}
          </div>
        )}
      </div>
      <div id="searchStatus" className={status.error ? "error" : ""}>{status.text}</div>
      {p && (
        <button className="profile-pill" onClick={() => go("profile")}>
          {p.name} profile · {p.score_10}/10 · Click to view or edit your answers
        </button>
      )}
    </section>
  );
}
