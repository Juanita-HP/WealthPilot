import { useEffect, useState } from "react";
import { api, signedPct } from "../lib.js";

const LABEL = { total_return: "Total return", cagr: "Annual return", volatility: "Volatility", sharpe: "Sharpe ratio",
                max_drawdown: "Worst fall", trades: "Trades", costs_paid: "Costs paid" };
const cell = (k, v) => v == null ? "—" : ["trades"].includes(k) ? v : k === "sharpe" ? Number(v).toFixed(2)
  : k === "costs_paid" ? "$" + Math.round(v).toLocaleString("en-CA") : signedPct(v);

export default function Lab() {
  const [universe, setUniverse] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [symbol, setSymbol] = useState("TSLA");
  const [strategy, setStrategy] = useState("ma_crossover");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api("/universe").then(setUniverse).catch(e => setError(e.message));
    api("/lab/strategies").then(setStrategies).catch(() => {});
  }, []);

  const run = async () => {
    setBusy(true); setError("");
    try { setRes(await api("/lab", { method: "POST", body: { symbol, strategy } })); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  const desc = strategies.find(s => s.value === strategy)?.description;
  return (
    <section className="page">
      <div className="page-heading">
        <div className="eyebrow">STRATEGY LAB</div>
        <h1>Test a trading rule, honestly.</h1>
        <p>The rule is tuned on the first 70% of the history, then tested on the rest, which it has never seen, against simply holding. The lab answers "what would have happened?", never "buy now".</p>
      </div>
      <div className="question-card" style={{ marginTop: 0 }}>
        <div className="form-grid">
          <div className="field"><label>Stock or fund</label>
            <select value={symbol} onChange={e => setSymbol(e.target.value)}>
              {universe.map(u => <option key={u.ticker} value={u.ticker}>{u.ticker} · {u.name}</option>)}
            </select></div>
          <div className="field"><label>Rule</label>
            <select value={strategy} onChange={e => setStrategy(e.target.value)}>
              {strategies.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select></div>
        </div>
        {desc && <p className="analysis-status">{desc}</p>}
        <div className="question-actions"><span /><button className="primary-btn" disabled={busy} onClick={run}>{busy ? "Testing…" : "Run the test →"}</button></div>
      </div>
      {error && <div className="error-text">{error}</div>}
      {res && (
        <div className="card" style={{ marginTop: 25 }}>
          <div className="kicker">TEST PERIOD · AFTER {res.split_date}</div>
          <h3 style={{ marginTop: 8 }}>The rule made {signedPct(res.rule)}, against {signedPct(res.hold)} for simply holding.</h3>
          <div className={"pill " + (res.better ? "green" : "red")}>
            {res.better ? "It did better on this period, which is still only one period." : "It did worse than simply holding."}
          </div>
          <ul className="small" style={{ marginTop: 16 }}>{res.findings.map(f => <li key={f}>{f}</li>)}</ul>
          <details className="more">
            <summary>All the numbers</summary>
            <div className="inner">
              <table className="data">
                <thead><tr><th></th><th className="num">Rule (tuning)</th><th className="num">Hold (tuning)</th><th className="num">Rule (test)</th><th className="num">Hold (test)</th></tr></thead>
                <tbody>{res.table.map(r => (
                  <tr key={r.metric}><td>{LABEL[r.metric]}</td><td className="num">{cell(r.metric, r.rule_in)}</td><td className="num">{cell(r.metric, r.hold_in)}</td>
                    <td className="num">{cell(r.metric, r.rule_out)}</td><td className="num">{cell(r.metric, r.hold_out)}</td></tr>))}
                </tbody>
              </table>
              <p className="muted small">{res.combinations} combinations tested · parameters kept: {JSON.stringify(res.params)}</p>
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
