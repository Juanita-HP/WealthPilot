// The investor's plan: one sub-portfolio per goal, the news that move it, and the risks to watch.
import { useEffect, useState } from "react";
import { PALETTE, api, dollars, longDate, pct, signedPct, go } from "../lib.js";
import { Donut } from "../components/Charts.jsx";

const VERDICT = { clear: "clear difference", unclear: "no clear effect", too_few: "too few cases" };
const PUBLISHER = { "Bank of Canada": "Bank of Canada", "Federal Reserve": "U.S. Federal Reserve", "Statistics Canada": "Statistics Canada" };

function GoalCard({ g }) {
  return (
    <div className="card goal-card">
      <div className="kicker">{g.level_text} · horizon {g.horizon}</div>
      <h3>{g.name}</h3>
      <div className="donut"><Donut holdings={g.holdings} /></div>
      <ul className="holdings">
        {g.holdings.map((h, i) => (
          <li key={h.ticker}><span><i style={{ background: PALETTE[i % PALETTE.length] }} />{h.name}</span><b>{pct(h.weight)}</b></li>
        ))}
      </ul>
      <div className={"pill " + g.status.tone}>{g.status.text}</div>
      {g.warnings.map(w => <div key={w} className="pill red">{w}</div>)}
      <p className="small muted">Suggested account: {g.account}</p>
      <details className="more">
        <summary>Why this mix</summary>
        <div className="inner">
          <p>{g.why_level}</p>
          <ul>{g.reasons.map(r => <li key={r.ticker}><b>{r.ticker}</b> {pct(r.weight, 1)}: {r.reason}</li>)}</ul>
          {g.assumption && <p className="muted">{g.assumption}</p>}
        </div>
      </details>
      {g.what_if.length > 0 && (
        <details className="more">
          <summary>What would change this answer</summary>
          <div className="inner"><ul>{g.what_if.map(c => <li key={c.condition}>{c.condition} → {c.effect}</li>)}</ul></div>
        </details>
      )}
    </div>
  );
}

function NewsCard({ it }) {
  const an = it.analog;
  return (
    <div className="card news-card">
      <div className="meta">{longDate(it.published_at)} · {PUBLISHER[it.publisher] || it.publisher} · {it.factor_label}</div>
      <div className="fact">{it.fact}</div>
      <p>{it.message}</p>
      <p className="muted">{it.note}</p>
      <details className="more">
        <summary>The text, the holdings affected and the past</summary>
        <div className="inner">
          <b>What the official text says</b>
          {it.quotes.map(q => (
            <blockquote key={q.text}>{q.text}<small>{q.kind === "fact" ? "fact" : "the source's own forecast"}</small></blockquote>
          ))}
          <p className="muted small">
            Text status: {it.text_status_label}. {pct(it.forward_share)} of the sentences are forecasts by the source.
            Analysis: {it.analyzer}. <a href={it.link} target="_blank" rel="noopener noreferrer">Read the release</a>
          </p>
          {it.exposure.lines.length > 0 && (
            <table className="data">
              <thead><tr><th>Holding</th><th className="num">Share</th><th>Link</th><th>Why</th></tr></thead>
              <tbody>{it.exposure.lines.map(x => (
                <tr key={x.ticker}><td>{x.name}</td><td className="num">{pct(x.weight)}</td><td>{x.channel}</td><td>{x.reason}</td></tr>))}
              </tbody>
            </table>
          )}
          {an ? (
            <>
              <p><b>After {an.n_events} similar events</b> ({longDate(an.first)} to {longDate(an.last)}), over the next {an.horizon_days} business days:</p>
              <table className="data">
                <thead><tr><th>Holding</th><th className="num">Average after</th><th className="num">Usually</th><th className="num">Up in</th><th>Verdict</th></tr></thead>
                <tbody>{an.rows.map(r => (
                  <tr key={r.ticker}><td>{r.name}</td><td className="num">{signedPct(r.mean_after)}</td><td className="num">{signedPct(r.usual)}</td>
                    <td className="num">{pct(r.hit_rate)} of cases</td><td>{VERDICT[r.verdict]}</td></tr>))}
                </tbody>
              </table>
              <p className="muted small">{an.caveat}</p>
            </>
          ) : it.analog_note && <p className="muted small">{it.analog_note}</p>}
          {it.stress && (
            <p><b>Related stress test</b> (hypothesis, not a forecast): {dollars(it.stress.dollars)} ({signedPct(it.stress.portfolio_return)}) — {it.stress.label}.</p>
          )}
        </div>
      </details>
    </div>
  );
}

const pt = x => (x > 0 ? "+" : "") + x.toFixed(2) + " pt";
const pc = x => (Math.abs(x) < 0.05 ? 0 : x).toFixed(1) + "%";
const monthYear = iso => new Date(iso + "T12:00:00").toLocaleDateString("en-CA", { year: "numeric", month: "long" });

// Range bar: the 80% interval, today's inflation and the 2% target on one scale.
function RangeBar({ low, high, value, current, target }) {
  const lo = Math.min(low, current, target) - 0.5, hi = Math.max(high, current, target) + 0.5;
  const x = v => ((v - lo) / (hi - lo)) * 100 + "%";
  return (
    <div className="range-bar">
      <div className="range-track" />
      <div className="range-band" style={{ left: x(low), width: `calc(${x(high)} - ${x(low)})` }} />
      <div className="range-mark target" style={{ left: x(target) }}><span>2% target</span></div>
      <div className="range-mark now" style={{ left: x(current) }}><span>Today {pc(current)}</span></div>
      <div className="range-dot" style={{ left: x(value) }} />
      <span className="range-end" style={{ left: x(low) }}>{pc(low)}</span>
      <span className="range-end" style={{ left: x(high) }}>{pc(high)}</span>
    </div>
  );
}

function InflationCard({ c }) {
  const ml = c.ml;
  const usedIsMl = c.method === "ridge";
  const maxAbs = Math.max(...ml.top.map(t => Math.abs(t.contribution)), 0.01);
  return (
    <div className="card inflation-card">
      <div className="kicker">Canadian inflation · next {c.horizon_months} months</div>
      <div className="infl-head">
        <div>
          <strong className="infl-value">{pc(c.forecast)}</strong>
          <span className="muted"> expected for {monthYear(c.target_month)}</span>
        </div>
        <div className="muted small">80% range: {pc(c.low)} to {pc(c.high)} · today {pc(c.current)} ({monthYear(c.origin_month)} data)</div>
      </div>
      <RangeBar low={c.low} high={c.high} value={c.forecast} current={c.current} target={c.target} />
      <p className="small">
        Method used: {c.method_label}. It had the lowest average error in walk-forward tests
        ({c.mae[c.method].toFixed(2)} pt; the range held the actual value {pc(c.interval_coverage * 100)} of the time).
      </p>
      <div className="ml-panel">
        <div className="kicker">What our machine-learning model sees</div>
        <p className="small" style={{ marginTop: 6 }}>
          Ridge regression on 9 macro variables: <b>{pc(ml.forecast)}</b> (80% range {pc(ml.low)} to {pc(ml.high)}).
          {usedIsMl ? " It is the method used above." :
            ` Its average error in the same tests was ${ml.mae.toFixed(2)} pt, against ${ml.mae_used_method.toFixed(2)} pt for the method used above, so it is shown for transparency, not used for the headline number.`}
        </p>
        <div className="small muted">The 3 variables that weigh most in its prediction (change in inflation they push, in points):</div>
        {ml.top.map(t => (
          <div className="contrib" key={t.feature} title={t.why}>
            <span className="contrib-label">{t.label} <small>(now {t.value.toFixed(2)})</small></span>
            <span className="contrib-bar">
              <i className={t.contribution >= 0 ? "up" : "down"}
                 style={{ width: Math.abs(t.contribution) / maxAbs * 50 + "%", [t.contribution >= 0 ? "left" : "right"]: "50%" }} />
            </span>
            <b className={t.contribution >= 0 ? "up" : "down"}>{pt(t.contribution)}</b>
          </div>
        ))}
      </div>
      <p className="note">
        Forecasts of inflation are uncertain, especially after shocks (errors were about twice as large from 2020 on).
        Your plan uses the long-run planning assumption of {pc(c.long_run_assumption * 100)} (FP Canada / IFP 2026); this
        card shows the near term, for context.
      </p>
    </div>
  );
}

export default function Plan() {
  const [plan, setPlan] = useState(null);
  const [news, setNews] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/plan").then(setPlan).catch(e => setError(e.message));
    api("/news/portfolio").then(setNews).catch(() => setNews({ items: [], notes: ["Official releases are unavailable right now."], sources: [] }));
  }, []);

  if (error) return <section className="page"><div className="error-text">{error}</div></section>;
  if (!plan) return <section className="page"><div className="loading">Building your plan…</div></section>;

  const attention = plan.risks.filter(r => r.level !== "low");
  return (
    <section className="page">
      <div className="page-heading plan-header">
        <div>
          <div className="eyebrow">YOUR PLAN</div>
          <h1>{plan.name} profile · {plan.score_10}/10 risk</h1>
          <p>{dollars(plan.total)} already set aside for {plan.goals.length} goal{plan.goals.length > 1 ? "s" : ""}, each invested according to its own horizon.
            {plan.available - plan.total > 1000 ? ` ${dollars(plan.available - plan.total)} of your savings and investments is not assigned to a goal and is not invested here.` : ""}</p>
        </div>
        <button className="profile-pill" onClick={() => go("profile")}>View or edit your profile</button>
      </div>
      {plan.notes.map(n => <div className="pill yellow" key={n}>{n}</div>)}

      <div className="grid cols-3">{plan.goals.map(g => <GoalCard key={g.name} g={g} />)}</div>

      {plan.inflation && (
        <>
          <h2 className="section-title">Inflation outlook</h2>
          <InflationCard c={plan.inflation} />
        </>
      )}

      <h2 className="section-title">The news and your portfolio</h2>
      {!news && <div className="loading">Reading the latest official releases…</div>}
      {news && news.items.map(it => <NewsCard key={it.id} it={it} />)}
      {news && (
        <p className="note">
          {news.notes?.[0]} {news.sources?.length ? "Sources: " + news.sources.map(s => PUBLISHER[s] || s).join(", ") + "." : ""}{" "}
          News explain what moves your money; they never change your allocation (reacting to news means trying to time the market).
        </p>
      )}

      <h2 className="section-title">Points to watch</h2>
      <div className="card">
        {!attention.length && <p style={{ marginTop: 0 }}>No high or moderate risk stands out.</p>}
        {attention.map(r => (
          <div className="risk-row" key={r.kind}><span className={"dot " + r.level} style={{ marginTop: 7 }} />
            <div><b>{r.label}</b> ({r.level}): {r.text}</div></div>
        ))}
        <details className="more">
          <summary>The six risks in detail</summary>
          <div className="inner">
            {plan.risks.map(r => (
              <div className="risk-row" key={r.kind}><span className={"dot " + r.level} style={{ marginTop: 7 }} />
                <div><b>{r.label}</b>: {r.level} · {r.metric} = {r.value.toFixed(3)}<br /><span className="muted">{r.reason}</span></div></div>
            ))}
          </div>
        </details>
      </div>
    </section>
  );
}
