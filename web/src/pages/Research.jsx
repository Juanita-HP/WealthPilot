// Research page: template quote, chart and fundamentals, plus the two WealthPilot scores as gauges,
// the explanation behind them, and recent news with their status (fact or opinion, text read or not).
import { useEffect, useState } from "react";
import { YAHOO, YAHOO2, api, candles, compact, fmt, getChart, getWatchlist, num, pct, requestJSON, saveWatchlist, signedPct, go } from "../lib.js";
import StockChart from "../components/StockChart.jsx";
import Gauge, { GaugeLegend } from "../components/Gauge.jsx";

const METRICS = [["openingPrice", "Opening price"], ["closingPrice", "Previous close"], ["tradingVolume", "Trading volume"],
                 ["marketCap", "Market capitalization"], ["dividendYield", "Dividend yield (TTM)"]];
const loading = { value: "Loading...", source: "Yahoo Finance" };

function extractRaw(value) {
  if (num(value)) return value;
  if (num(value?.raw)) return value.raw;
  if (num(value?.reportedValue?.raw)) return value.reportedValue.raw;
  return NaN;
}

function findTimeseriesValue(data, key) {
  const values = [];
  for (const item of data.timeseries?.result || []) {
    for (const entry of Array.isArray(item[key]) ? item[key] : []) {
      const value = extractRaw(entry);
      if (num(value) && value > 0) values.push({ value, date: entry.asOfDate ? Date.parse(entry.asOfDate) : 0 });
    }
  }
  values.sort((a, b) => b.date - a.date);
  return values[0]?.value ?? NaN;
}

function useQuote(ticker) {
  const [state, setState] = useState({ name: "", exchange: "", currency: "", price: NaN, change: null, time: "", error: "",
                                       metrics: Object.fromEntries(METRICS.map(([k]) => [k, loading])) });
  useEffect(() => {
    let alive = true;
    const metric = (key, value, source) => alive && setState(s => ({ ...s, metrics: { ...s.metrics, [key]: { value, source } } }));
    (async () => {
      let currency = "", price = NaN;
      const money = v => num(v) ? fmt(v) + (currency ? " " + currency : "") : "Unavailable";
      try {
        const r = await getChart(ticker, "1d", "5m");
        if (!alive) return;
        const meta = r.meta || {};
        const bars = candles(r);
        currency = meta.currency || "";
        price = num(meta.regularMarketPrice) ? meta.regularMarketPrice : bars.at(-1)?.close;
        const prev = num(meta.chartPreviousClose) ? meta.chartPreviousClose : meta.previousClose;
        const opening = num(meta.regularMarketOpen) ? meta.regularMarketOpen : bars.find(x => num(x.open))?.open;
        let change = null;
        if (num(price) && num(prev) && prev !== 0) {
          const diff = price - prev, sign = diff > 0 ? "+" : "";
          change = { text: sign + money(diff) + " (" + sign + (diff / prev * 100).toFixed(2) + "%)", up: diff >= 0 };
        }
        let time = "";
        if (num(meta.regularMarketTime)) {
          const date = new Date(meta.regularMarketTime * 1000);
          try { time = date.toLocaleString("en-CA", { dateStyle: "medium", timeStyle: "short", timeZone: meta.exchangeTimezoneName || "America/New_York" }); }
          catch { time = date.toLocaleString("en-CA"); }
        }
        setState(s => ({ ...s, name: meta.longName || meta.shortName || "", exchange: meta.fullExchangeName || "", currency, price, change,
                         time: time ? "Last quoted: " + time + " · May be delayed" : "" }));
        metric("openingPrice", money(opening), "Yahoo · regular session open");
        metric("closingPrice", money(prev), "Yahoo · previous session close");
        const volume = meta.regularMarketVolume;
        if (num(volume)) metric("tradingVolume", Math.round(volume).toLocaleString("en-CA"), "Yahoo · session volume");
        else {
          try {
            const latest = candles(await getChart(ticker, "5d", "1d")).at(-1);
            metric("tradingVolume", num(latest?.volume) ? Math.round(latest.volume).toLocaleString("en-CA") : "Unavailable", "Yahoo · latest daily volume");
          } catch { metric("tradingVolume", "Unavailable", "Yahoo · volume unavailable"); }
        }
      } catch (err) {
        if (!alive) return;
        setState(s => ({ ...s, error: "Yahoo quote request failed: " + err.message }));
        ["openingPrice", "closingPrice", "tradingVolume"].forEach(k => metric(k, "Unavailable", "Yahoo · request failed"));
      }
      // Dividend yield (trailing 12 months)
      try {
        const now = Math.floor(Date.now() / 1000), cutoff = now - 365 * 86400;
        const url = YAHOO + "/v8/finance/chart/" + encodeURIComponent(ticker) + "?" + new URLSearchParams({
          period1: String(cutoff - 35 * 86400), period2: String(now + 86400), interval: "1d", events: "div", includePrePost: "false" });
        const r = (await requestJSON(url)).chart?.result?.[0];
        if (!r) throw Error("No dividend data");
        const events = r.events?.dividends;
        const payments = events ? Object.values(events).filter(d => num(d.amount) && d.amount > 0 && num(d.date) && d.date >= cutoff && d.date <= now) : [];
        const sharePrice = num(price) && price > 0 ? price : r.meta?.regularMarketPrice;
        if (!events) metric("dividendYield", "Unavailable", "Yahoo · no dividend events returned");
        else if (!num(sharePrice) || sharePrice <= 0) metric("dividendYield", "Unavailable", "Share price unavailable");
        else if (!payments.length) metric("dividendYield", "Unavailable", "No confirmed dividend payments");
        else metric("dividendYield", (payments.reduce((s, d) => s + d.amount, 0) / sharePrice * 100).toFixed(2) + "%", "Yahoo · trailing 12-month dividends");
      } catch { metric("dividendYield", "Unavailable", "Yahoo · dividend request failed"); }
      // Market capitalization: quote, then valuation series, then share count x price
      const setCap = (v, source) => { if (!num(v) || v <= 0) return false; metric("marketCap", compact(v) + (currency ? " " + currency : ""), source); return true; };
      try {
        const q = (await requestJSON(YAHOO + "/v7/finance/quote?" + new URLSearchParams({ symbols: ticker })))
          .quoteResponse?.result?.find(x => x.symbol?.toUpperCase() === ticker);
        if (q && (setCap(q.marketCap, "Yahoo · reported market cap") || (num(q.sharesOutstanding) && setCap(q.sharesOutstanding * price, "Yahoo · price × shares")))) return;
      } catch { /* quote endpoint often restricted */ }
      const now = Math.floor(Date.now() / 1000);
      try {
        const data = await requestJSON(YAHOO2 + "/ws/fundamentals-timeseries/v1/finance/timeseries/" + encodeURIComponent(ticker) + "?" +
          new URLSearchParams({ symbol: ticker, type: "trailingMarketCap,quarterlyMarketCap", period1: String(now - 400 * 86400), period2: String(now + 86400) }));
        if (setCap(findTimeseriesValue(data, "trailingMarketCap"), "Yahoo · valuation series")) return;
        if (setCap(findTimeseriesValue(data, "quarterlyMarketCap"), "Yahoo · quarterly valuation")) return;
      } catch { /* try share count */ }
      try {
        const data = await requestJSON(YAHOO2 + "/ws/fundamentals-timeseries/v1/finance/timeseries/" + encodeURIComponent(ticker) + "?" +
          new URLSearchParams({ symbol: ticker, period1: String(now - 550 * 86400), period2: String(now + 86400) }));
        const shares = [];
        for (const item of data.timeseries?.result || []) (item.shares_out || []).forEach((v, i) => num(v) && v > 0 && shares.push({ v, t: item.timestamp?.[i] || 0 }));
        shares.sort((a, b) => b.t - a.t);
        if (num(shares[0]?.v) && num(price) && setCap(shares[0].v * price, "Yahoo · share count × price")) return;
      } catch { /* fall through */ }
      metric("marketCap", "Unavailable", "Yahoo · valuation access restricted");
    })();
    return () => { alive = false; };
  }, [ticker]);
  return state;
}

function ScoreCard({ kicker, title, score, label, sentence, zones, names, note, fallback, needle }) {
  return (
    <div className="score-card">
      <div className="kicker">{kicker}</div>
      <h3>{title}</h3>
      <Gauge score={needle ?? score} zones={zones} label={title} />
      <div className="gauge-value">
        {num(score) ? <><strong>{Math.round(score)}</strong><span>/ 100</span></> : <strong>{fallback || "—"}</strong>}
      </div>
      <div className="gauge-label">{label}</div>
      <GaugeLegend zones={zones} names={names} />
      <div className="score-text">{sentence}</div>
      {note && <div className="analysis-disclaimer">{note}</div>}
    </div>
  );
}

function FactorTable({ score, labels }) {
  if (!score?.factors?.length) return null;
  return (
    <table className="data">
      <thead><tr><th>Factor</th><th className="num">Value</th><th className="num">Score (0–1)</th><th className="num">Weight</th><th>Rule</th></tr></thead>
      <tbody>{score.factors.map(f => (
        <tr key={f.name}>
          <td>{labels[f.name] || f.name}</td>
          <td className="num">{num(f.value) ? Number(f.value.toPrecision(3)) : "—"}</td>
          <td className="num">{num(f.score) ? f.score.toFixed(2) : "—"}</td>
          <td className="num">{f.weight}</td>
          <td>{f.explanation}</td>
        </tr>))}
      </tbody>
    </table>
  );
}

export default function Research({ symbol }) {
  const ticker = symbol.toUpperCase();
  const quote = useQuote(ticker);
  const [ins, setIns] = useState(null);
  const [insError, setInsError] = useState("");
  const [newsData, setNewsData] = useState(null);
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(getWatchlist().some(i => i.symbol === ticker));

  useEffect(() => {
    let alive = true;
    api(`/stocks/${encodeURIComponent(ticker)}/insights`).then(r => alive && setIns(r)).catch(e => alive && setInsError(e.message));
    api(`/stocks/${encodeURIComponent(ticker)}/news`).then(r => alive && setNewsData(r)).catch(() => alive && setNewsData({ available: false, note: "News unavailable right now." }));
    return () => { alive = false; };
  }, [ticker]);

  const name = quote.name || ins?.name || ticker;
  const toggleStar = () => {
    const items = getWatchlist();
    const index = items.findIndex(i => i.symbol === ticker);
    if (index >= 0) items.splice(index, 1); else items.push({ symbol: ticker, name });
    if (saveWatchlist(items)) setSaved(index < 0);
  };
  const googleTicker = ticker.endsWith(".TO") ? ticker.slice(0, -3) + ":TSE" : ticker;
  const dg = newsData?.digest;
  const headlines = dg ? [...dg.top_descriptive.map(h => ({ ...h, kind: "fact" })), ...dg.top_predictive.map(h => ({ ...h, kind: "opinion" }))]
    .sort((a, b) => b.published_at.localeCompare(a.published_at)) : [];

  return (
    <section>
      <button className="back" onClick={() => go("stocks")}>← Back to search</button>
      <div className="stock-heading">
        <h1 className="stock-title">{name}</h1>
        <button className={"watchlist-star" + (saved ? " saved" : "")} type="button" onClick={toggleStar}
                aria-label={saved ? "Remove from watchlist" : "Add to watchlist"} aria-pressed={saved}>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 2.8 14.85 8.6l6.4.93-4.63 4.51 1.09 6.37L12 17.4l-5.71 3.01 1.09-6.37L2.75 9.53l6.4-.93L12 2.8Z" />
          </svg>
        </button>
      </div>
      <div className="symbol">{ticker}{quote.exchange ? " · " + quote.exchange : ""}</div>
      <div className="price">{num(quote.price) ? fmt(quote.price) + (quote.currency ? " " + quote.currency : "") : quote.error ? "Unavailable" : "Loading..."}</div>
      <div className={"change " + (quote.change ? (quote.change.up ? "up" : "down") : "")}>{quote.change?.text || ""}</div>
      <div className="timestamp">{quote.time}</div>

      <div className="research-layout">
        <StockChart ticker={ticker} currency={quote.currency} />
        <aside className="fundamentals">
          {METRICS.map(([key, label]) => {
            const m = quote.metrics[key];
            return (
              <div className="metric-row" key={key}>
                <div className="metric-top">
                  <span className="metric-label">{label}</span>
                  <strong className={"metric-value" + (m.value === "Unavailable" || m.value === "Loading..." ? " empty" : "")}>{m.value}</strong>
                </div>
                <div className="metric-source">{m.source}</div>
              </div>
            );
          })}
        </aside>
      </div>

      <section className="analysis-card">
        <div className="analysis-head">
          <div>
            <div className="eyebrow">INVESTOR PROFILE ANALYSIS</div>
            <h2>How well does this stock fit?</h2>
            <p>Two separate scores: one against your saved investor profile, one on the company alone, without bias.</p>
            <button type="button" className="inline-link" onClick={() => go("profile")}>Edit investor profile</button>
          </div>
          <button type="button" className="score-button" disabled={!ins} onClick={() => setOpen(!open)}>
            {open ? "Hide explanation ↑" : "View explanation ↓"}
            <small>Factors, weights and rules</small>
          </button>
        </div>
        {insError && <div className="analysis-status">Unable to calculate the scores: {insError}</div>}
        {!ins && !insError && <div className="analysis-status">Preparing analysis…</div>}
        {ins && (
          <>
            <div className="scores">
              <ScoreCard kicker="For your profile" title="Profile fit" score={ins.fit.score} label={ins.fit.label}
                         sentence={ins.fit.sentence} zones={ins.fit.zones} names={["Poor fit", "Possible", "Good fit"]} />
              <ScoreCard kicker="Unbiased potential" title="Measured growth" score={ins.potential.score}
                         label={ins.potential.long_run_assumption ? "Diversified fund" : ins.potential.label}
                         fallback={ins.potential.long_run_assumption ? pct(ins.potential.long_run_assumption.annual_return, 1) + " / yr" : "—"}
                         needle={ins.potential.score ?? ins.potential.assumption_score}
                         sentence={ins.potential.sentence} zones={ins.potential.zones} names={["Weak", "Moderate", "Strong"]}
                         note={ins.potential.score == null && ins.potential.long_run_assumption
                           ? "Planning assumption for the fund's market (FP Canada / IFP 2026): not a forecast, not your profile."
                           : "Measured data only: no analyst opinions, no news, not your profile."} />
            </div>
            <div className="analysis-grid">
              <div className="analysis-stat"><span>Annualized volatility</span><strong>{pct(ins.stats.volatility, 1)}</strong></div>
              <div className="analysis-stat"><span>Maximum drawdown (5 years)</span><strong>{num(ins.stats.max_drawdown) ? "−" + pct(ins.stats.max_drawdown, 1) : "—"}</strong></div>
              <div className="analysis-stat"><span>1-year return</span><strong>{signedPct(ins.stats.return_1y)}</strong></div>
              <div className="analysis-stat"><span>Price swings</span><strong style={{ textTransform: "capitalize" }}>{ins.stats.swings}</strong></div>
            </div>
            {ins.note && <div className="analysis-status">{ins.note}</div>}
            {open && (
              <div className="explanation">
                <h3>Why these scores?</h3>
                <p className="analysis-status" style={{ marginTop: 0 }}><b>Profile fit</b> · {ins.fit.label}</p>
                <FactorTable score={ins.fit} labels={ins.factor_labels} />
                <ul>{ins.fit.notes.map(n => <li key={n}>{n}</li>)}</ul>
                <p className="analysis-status"><b>Measured growth</b> · {ins.potential.label}</p>
                <FactorTable score={ins.potential} labels={ins.factor_labels} />
                <ul>
                  {ins.potential.notes.map(n => <li key={n}>{n}</li>)}
                  {num(ins.analyst_upside) && <li>For information, analysts target {signedPct(ins.analyst_upside, 0)} on average: an opinion, left out of the potential score.</li>}
                  <li>Method: each factor is mapped to 0–1 by a stated rule, then weighted. Factors without data are left out, not guessed; below 50% coverage no score is shown.</li>
                  <li>Source: {ins.data.source}. {ins.data.price_basis}.</li>
                </ul>
              </div>
            )}
          </>
        )}
        <div className="analysis-disclaimer">
          Educational simulation, not personalized financial advice. Historical data cannot predict future returns.
          Scores follow stated rules and exclude unverified factors. Missing or insufficient data means no score.
        </div>
      </section>

      <section className="analysis-card">
        <div className="eyebrow">MARKET INFORMATION</div>
        <h2>Recent company news</h2>
        <p className="analysis-status">
          Facts and opinions are labeled separately. Verify the original article, date and publisher: headlines are context, not predictive signals.
        </p>
        {!newsData && <div className="analysis-status">Loading available headlines...</div>}
        {newsData && !newsData.available && <div className="analysis-status">{newsData.note}</div>}
        {dg && dg.n === 0 && <div className="analysis-status">No recent headline is really about this company.</div>}
        {dg && dg.n > 0 && (
          <>
            <div className="analysis-status">
              Of {dg.n} recent headlines, <b>{dg.n - Math.round(dg.share_predictive * dg.n)} report facts</b> and{" "}
              <b>{Math.round(dg.share_predictive * dg.n)} are opinions or forecasts</b>
              {dg.hype_share >= 0.4 ? ", many from low-trust sources." : "."}
            </div>
            {headlines.map(h => (
              <div className="news-item" key={h.link || h.title}>
                <span className={"tag " + h.kind}>{h.kind === "fact" ? "Fact" : "Opinion"}</span>
                <a href={h.link} target="_blank" rel="noopener noreferrer">{h.title}</a>
                <small>{h.publisher} · {new Date(h.published_at).toLocaleDateString("en-CA")} · source trust {h.trust.toFixed(2)}</small>
              </div>
            ))}
            <div className="analysis-disclaimer">{newsData.texts_note}</div>
            {newsData.quotes?.map(q => <blockquote key={q}>{q}</blockquote>)}
          </>
        )}
        <div className="source-links">
          <a href={"https://finance.yahoo.com/quote/" + encodeURIComponent(ticker) + "/news/"} target="_blank" rel="noopener noreferrer">Yahoo Finance</a>
          <a href={"https://news.google.com/search?q=" + encodeURIComponent(ticker + " stock")} target="_blank" rel="noopener noreferrer">Google News</a>
        </div>
      </section>

      {quote.error && <div className="page-error">{quote.error}</div>}
      <div className="source-box">
        <strong>Data sources & limitations</strong>
        <div>
          Opening price, previous close, volume and chart prices come from Yahoo Finance. Dividend yield uses recorded
          trailing dividends. Market cap uses Yahoo valuation or share-count information when accessible. Scores use
          five years of adjusted prices and company statements{ins && !ins.live ? " (offline dataset)" : ""}.
        </div>
        <div className="source-links">
          <a href={"https://finance.yahoo.com/quote/" + encodeURIComponent(ticker) + "/"} target="_blank" rel="noopener noreferrer">Yahoo Finance</a>
          <a href={"https://www.google.com/finance/quote/" + encodeURIComponent(googleTicker)} target="_blank" rel="noopener noreferrer">Google Finance</a>
        </div>
      </div>
      <p className="note">
        Market information may be delayed. WealthPilot uses unofficial Yahoo Finance endpoints, relayed by its own server.
        Some advanced financial fields may be unavailable when Yahoo restricts access.
        Watchlist entries are stored locally in this browser.
      </p>
    </section>
  );
}
