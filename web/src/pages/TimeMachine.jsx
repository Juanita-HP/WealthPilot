import { useEffect, useMemo, useState } from "react";
import { PALETTE, api, dollars, pct, signedPct, go } from "../lib.js";
import { GrowthChart, ValueChart } from "../components/Charts.jsx";

// The plan's holdings and the plan itself against the rise in the cost of living, over the same five years.
function VsInflation({ v }) {
  const series = useMemo(() => [
    { label: "Cost of living (CPI)", values: v.inflation.growth, color: "#c45454", dash: [6, 4], width: 2.4, order: 0 },
    { label: "Your plan", values: v.plan.growth, color: "#172025", width: 3, order: 0 },
    ...v.holdings.map((h, i) => ({ label: h.ticker, values: h.growth, color: PALETTE[(i + 1) % PALETTE.length], width: 1.2 })),
  ], [v]);
  const beat = v.holdings.filter(h => h.beats_inflation).length;
  return (
    <>
      <h2 className="section-title">Our investments vs inflation</h2>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          Over {v.start} to {v.end}, the cost of living rose <b>{pct(v.inflation.total, 1)}</b> ({pct(v.inflation.annual, 1)} a year).
          Your plan grew <b>{signedPct(v.plan.total_return, 1)}</b>, that is <b className={v.plan.beats_inflation ? "up" : "down"}>
          {signedPct(v.plan.real_annual_return, 1)} a year above inflation</b>. {beat} of its {v.holdings.length} holdings beat inflation.
        </p>
        <div className="chart-area" style={{ height: 340 }}><GrowthChart dates={v.dates} series={series} /></div>
        <p className="muted small">Growth of 100 invested at the start. Click a name in the legend to hide or show it.</p>
        <table className="data">
          <thead><tr><th>Holding</th><th className="num">Share of plan</th><th className="num">Total</th>
            <th className="num">Per year</th><th className="num">Per year after inflation</th><th>Beat inflation?</th></tr></thead>
          <tbody>
            {[v.plan, ...v.holdings].map(h => (
              <tr key={h.ticker || "plan"} style={h.ticker ? undefined : { fontWeight: 700 }}>
                <td>{h.ticker ? <><b>{h.ticker}</b> · {h.name}</> : "Your plan"}</td>
                <td className="num">{pct(h.weight)}</td>
                <td className="num">{signedPct(h.total_return, 1)}</td>
                <td className="num">{signedPct(h.annual_return, 1)}</td>
                <td className={"num " + (h.beats_inflation ? "up" : "down")}>{signedPct(h.real_annual_return, 1)}</td>
                <td>{h.beats_inflation ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted small">
          {v.note} Bond and short-term funds are in the plan to cushion falls, not to beat inflation by much: judge them
          with the worst fall above, not only with this table. Inflation: {v.inflation.source}.
        </p>
      </div>
    </>
  );
}

export default function TimeMachine() {
  const [d, setD] = useState(null);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState("");

  useEffect(() => { api("/time-machine").then(setD).catch(e => setError(e.message)); }, []);

  if (error) return <section className="page"><div className="error-text">{error}</div></section>;
  if (!d) return <section className="page"><div className="loading">Replaying the last five years…</div></section>;

  const nearest = iso => d.dates.findIndex(x => x >= iso);
  return (
    <section className="page">
      <div className="page-heading">
        <div className="eyebrow">TIME MACHINE</div>
        <h1>Would you have held on?</h1>
        <p>Your plan, replayed over the last five years with your {dollars(d.amount)}, in Canadian dollars. Past results do not predict future returns.</p>
      </div>
      <div className="chart-section">
        <div className="chart-readout"><strong>{dollars(d.final_value)}</strong><span>value at the end ({d.end})</span></div>
        <div className="chart-area"><ValueChart dates={d.dates} value={d.value} valueReal={d.value_real}
                                                from={nearest(d.worst.peak_date)} to={nearest(d.worst.trough_date)} /></div>
        <div className="chart-status">Shaded: the worst fall, from {d.worst.peak_date} to {d.worst.trough_date}.</div>
      </div>
      <div className="question-card">
        <p style={{ fontSize: 15, color: "var(--ink)" }}>{d.summary}</p>
        <h2 style={{ marginTop: 16 }}>Would you have held on?</h2>
        <div className="choices">
          <button className={"choice" + (answer === "yes" ? " selected" : "")} onClick={() => setAnswer("yes")}>
            <strong>Yes</strong><small>I would have waited for the recovery</small></button>
          <button className={"choice" + (answer === "no" ? " selected" : "")} onClick={() => setAnswer("no")}>
            <strong>No</strong><small>I would have sold, at least in part</small></button>
        </div>
        {answer === "no" && (
          <div className="pill yellow">
            Good to know: your real tolerance may be lower. In your profile you can choose a more cautious level.{" "}
            <button className="inline-link" onClick={() => go("profile")}>Open my profile</button>
          </div>
        )}
        {answer === "yes" && <div className="pill green">Then this plan matches what you would live with. Remember it if markets fall.</div>}
      </div>
      <div className="analysis-grid" style={{ marginTop: 25 }}>
        <div className="analysis-stat"><span>Final value</span><strong>{dollars(d.final_value)}</strong></div>
        <div className="analysis-stat"><span>After inflation</span><strong>{dollars(d.final_value_real)}</strong></div>
        <div className="analysis-stat"><span>Worst fall</span><strong>{signedPct(-Math.abs(d.worst.drawdown))}</strong></div>
        <div className="analysis-stat"><span>Worst 12 months</span><strong>{signedPct(d.worst_12_months.return)}</strong></div>
      </div>
      {d.vs_inflation && <VsInflation v={d.vs_inflation} />}
      <h2 className="section-title">Hypothetical scenarios</h2>
      <div className="card">
        <p style={{ marginTop: 0 }} className="muted small">Stylized shocks to test the plan. Hypotheses, not forecasts.</p>
        <table className="data">
          <thead><tr><th>Scenario</th><th className="num">Effect</th><th className="num">In dollars</th><th>Basis</th></tr></thead>
          <tbody>{d.shocks.map(s => (
            <tr key={s.label}><td>{s.label}</td><td className="num">{signedPct(s.return)}</td><td className="num">{dollars(s.dollars)}</td><td>{s.basis}</td></tr>))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
