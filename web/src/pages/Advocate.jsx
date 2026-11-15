import { useEffect, useState } from "react";
import { api, pct } from "../lib.js";

const METRICS = [["cagr", "Annual return", true], ["volatility", "Volatility", true], ["max_drawdown", "Worst fall", true], ["sharpe", "Sharpe ratio", false]];

export default function Advocate() {
  const [universe, setUniverse] = useState([]);
  const [symbol, setSymbol] = useState("TSLA");
  const [weight, setWeight] = useState(30);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);

  useEffect(() => { api("/universe").then(setUniverse).catch(e => setError(e.message)); }, []);

  const run = async () => {
    setBusy(true); setError("");
    try { setReview(await api("/advocate", { method: "POST", body: { symbol, weight: weight / 100 } })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  useEffect(() => { if (universe.length) run(); }, [universe.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const ask = async () => {
    setAnswer({ loading: true });
    try { setAnswer(await api("/ask", { method: "POST", body: { question } })); }
    catch (e) { setAnswer({ error: e.message }); }
  };

  const ba = review?.before_after;
  return (
    <section className="page">
      <div className="page-heading">
        <div className="eyebrow">DEVIL'S ADVOCATE</div>
        <h1>Challenge an idea.</h1>
        <p>Say what you would like to do. The devil's advocate checks it against your profile and your plan, names the bias or risk, and gives the honest counterpoint when the data supports you.</p>
      </div>
      <div className="question-card" style={{ marginTop: 0 }}>
        <div className="form-grid">
          <div className="field">
            <label>I want to put…</label>
            <select value={symbol} onChange={e => setSymbol(e.target.value)}>
              {universe.map(u => <option key={u.ticker} value={u.ticker}>{u.ticker} · {u.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>…this share of my portfolio: {weight}%</label>
            <div className="range-row" style={{ height: 48 }}>
              <input type="range" min="1" max="60" value={weight} onChange={e => setWeight(Number(e.target.value))} />
            </div>
          </div>
        </div>
        <div className="question-actions"><span /><button className="primary-btn" disabled={busy} onClick={run}>{busy ? "Reviewing…" : "Review this idea →"}</button></div>
      </div>
      {error && <div className="error-text">{error}</div>}
      {review && (
        <>
          <div className={"pill " + review.verdict.tone} style={{ fontSize: 16, marginTop: 26 }}>{review.verdict.text}</div>
          <div style={{ marginTop: 16 }}>
            {review.challenges.length === 0 && <div className="card"><p style={{ marginTop: 0 }}>Nothing deserves a challenge here.</p></div>}
            {review.challenges.map(c => (
              <div className={"card challenge " + c.severity} key={c.code}>
                <h3>{c.title}</h3>
                <p>{c.claim}</p>
                {c.counterpoint && <p className="muted"><b>{c.code === "RECENT_NEWS" ? "Grain of salt:" : "Counterpoint:"}</b> {c.counterpoint}</p>}
                <p><b>Question for you:</b> {c.question}</p>
              </div>
            ))}
          </div>
          {ba && (
            <details className="more card" style={{ marginTop: 12 }}>
              <summary>Before and after, on the historical data</summary>
              <div className="inner">
                <table className="data">
                  <thead><tr><th></th><th className="num">Before</th><th className="num">After</th></tr></thead>
                  <tbody>{METRICS.map(([k, label, isPct]) => (
                    <tr key={k}><td>{label}</td><td className="num">{isPct ? pct(ba.before[k], 1) : ba.before[k]?.toFixed(2)}</td>
                      <td className="num">{isPct ? pct(ba.after[k], 1) : ba.after[k]?.toFixed(2)}</td></tr>))}
                  </tbody>
                </table>
                <p className="muted small">History {ba.window}, in Canadian dollars.</p>
              </div>
            </details>
          )}
        </>
      )}
      <h2 className="section-title">Ask the advisor</h2>
      <div className="card">
        <p style={{ marginTop: 0 }} className="muted small">
          Claude agents on Amazon Bedrock: an advisor, a devil's advocate and a verifier that checks every number against the calculations.
        </p>
        <div className="field">
          <textarea placeholder="For example: should I put more into Canadian banks?" value={question} onChange={e => setQuestion(e.target.value)} />
        </div>
        <div className="question-actions"><span /><button className="primary-btn" disabled={!question.trim() || answer?.loading} onClick={ask}>
          {answer?.loading ? "The agents are working…" : "Ask →"}</button></div>
        {answer?.error && <div className="analysis-status">{answer.error}</div>}
        {answer?.text && <div style={{ whiteSpace: "pre-wrap", fontSize: 14, lineHeight: 1.7, marginTop: 16 }}>{answer.text}</div>}
      </div>
    </section>
  );
}
