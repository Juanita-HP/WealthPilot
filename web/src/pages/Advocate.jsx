import { useEffect, useState } from "react";
import { LabPanel } from "./Lab.jsx";
import { api, pct } from "../lib.js";

const METRICS = [["cagr", "Annual return", true], ["volatility", "Volatility", true], ["max_drawdown", "Worst fall", true], ["sharpe", "Sharpe ratio", false]];

export default function Advocate() {
  const [universe, setUniverse] = useState([]);
  // A stock sent from its research page ("Challenge this stock with the Devil's Advocate").
  const [fromResearch] = useState(() => { try { return sessionStorage.getItem("wp_advocate_symbol"); } catch { return null; } });
  const [symbol, setSymbol] = useState(fromResearch || "TSLA");
  const [weight, setWeight] = useState(30);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [timing, setTiming] = useState(null);

  useEffect(() => { api("/universe").then(setUniverse).catch(e => setError(e.message)); }, []);
  useEffect(() => { api("/timing").then(setTiming).catch(() => setTiming({ available: false })); }, []);
  useEffect(() => { try { sessionStorage.removeItem("wp_advocate_symbol"); } catch { /* storage off */ } }, []);
  const suggested = "Ask the AI agents to analyze how recent news and risks on " + symbol + " affect my profile";

  const run = async () => {
    setBusy(true); setError("");
    try { setReview(await api("/advocate", { method: "POST", body: { symbol, weight: weight / 100 } })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  useEffect(() => {
    if (!universe.length) return;
    if (!universe.some(u => u.ticker === symbol)) {
      setError(`${symbol} is not in the simulation's asset universe yet: the devil's advocate reviews listed assets only.`);
      setSymbol("TSLA");
      return;
    }
    run();
  }, [universe.length]); // eslint-disable-line react-hooks/exhaustive-deps

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
      {timing?.available && (
        <>
          <h2 className="section-title">Thinking of timing the market?</h2>
          <div className="card">
            <p style={{ marginTop: 0 }}>
              We tested a real machine-learning timing model ({timing.source.toLowerCase()}): it estimates the chance of a
              2% rise over the next 5 days and buys when that chance is high enough. Each year from 2010 was a test it had
              never seen, with realistic costs ({(timing.costs.main.per_side * 100).toFixed(2)}% per trade side: $0
              commission at Wealthsimple or Questrade, plus the bid-ask spread).
            </p>
            <table className="data">
              <thead><tr><th>Asset</th><th className="num">Years it beat holding</th><th className="num">Total, model</th>
                <th className="num">Total, holding</th><th className="num">Skill (AUC)</th><th>Shown as a signal?</th></tr></thead>
              <tbody>{timing.assets.map(a => (
                <tr key={a.ticker}><td>{a.ticker}</td><td className="num">{a.wins_sharpe} of {a.tests}</td>
                  <td className="num">{pct(a.model_compounded)}</td><td className="num">{pct(a.hold_compounded)}</td>
                  <td className="num">{a.auc?.toFixed(2)}</td><td>{a.usable ? "Yes" : "No: fails the test"}</td></tr>))}
              </tbody>
            </table>
            <p className="small muted">
              A signal is shown only if, after costs, it beats holding in at least {pct(timing.gate.win_share_sharpe)} of the
              years on the Sharpe ratio and the gap is significant (p &lt; {timing.gate.p_value}). The model reads short-term
              moves a little better than chance, but being out of the market on a few of the best days costs more than the
              losses it avoids. Results from {timing.trained_on}.
            </p>
            {["intermediate", "advanced"].includes(timing.experience) ? (
              <details className="more">
                <summary>Test a trading rule yourself</summary>
                <div className="inner"><LabPanel /></div>
              </details>
            ) : (
              <p className="small" style={{ marginBottom: 0 }}>
                For most investors, buying regularly and holding a diversified portfolio has beaten trying to pick the moment.
              </p>
            )}
          </div>
        </>
      )}

      <h2 className="section-title">Ask the advisor</h2>
      <div className="card">
        <p style={{ marginTop: 0 }} className="muted small">
          Claude agents on Amazon Bedrock: an advisor, a devil's advocate and a verifier that checks every number against the calculations.
        </p>
        <button type="button" className="quiet-btn" style={{ marginBottom: 12 }} onClick={() => setQuestion(suggested)}>
          {suggested}
        </button>
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
