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
  const growth = v.holdings.filter(h => h.role === "Growth");
  const stability = v.holdings.filter(h => h.role === "Stability");
  const y = v.yields;
  return (
    <>
      <h2 className="section-title">Our investments vs inflation</h2>
      <div className="card">
        <p style={{ marginTop: 0 }}>
          Over {v.start} to {v.end}, the cost of living rose <b>{pct(v.inflation.total, 1)}</b> ({pct(v.inflation.annual, 1)} a year).
          Your plan grew <b>{signedPct(v.plan.total_return, 1)}</b>: <b className={v.plan.beats_inflation ? "up" : "down"}>
          {signedPct(v.plan.real_annual_return, 1)} a year {v.plan.beats_inflation ? "above" : "below"} inflation</b>.
          {growth.length > 0 && <> All {growth.length} growth funds beat inflation.</>}
          {v.plan.expected_real_return != null && <> Looking ahead, the planning guidelines expect about{" "}
            <b>{signedPct(v.plan.expected_real_return, 1)} a year above inflation</b> for the {pct(v.plan.expected_coverage)} of the plan they cover.</>}
        </p>
        <div className="chart-area" style={{ height: 340 }}><GrowthChart dates={v.dates} series={series} /></div>
        <p className="muted small">Growth of 100 invested at the start. Click a name in the legend to hide or show it.</p>
        <table className="data">
          <thead><tr><th>Holding</th><th>Role</th><th className="num">Share of plan</th>
            <th className="num">Per year, last 5 years</th><th className="num">After inflation, last 5 years</th>
            <th className="num">Expected after inflation</th></tr></thead>
          <tbody>
            {[v.plan, ...v.holdings].map(h => (
              <tr key={h.ticker || "plan"} style={h.ticker ? undefined : { fontWeight: 700 }}>
                <td>{h.ticker ? <><b>{h.ticker}</b> · {h.name}</> : "Your plan"}</td>
                <td>{h.role}</td>
                <td className="num">{pct(h.weight)}</td>
                <td className="num">{signedPct(h.annual_return, 1)}</td>
                <td className={"num " + (h.beats_inflation ? "up" : "down")}>{signedPct(h.real_annual_return, 1)}</td>
                <td className="num">{h.expected_real_return != null ? signedPct(h.expected_real_return, 1) : "No assumption"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {stability.some(h => !h.beats_inflation) && y && (
          <div className="analysis-status">
            <b>Why the bond funds lost to inflation here.</b> This window starts when Canada's 10-year bond yield was
            only {y.start.toFixed(2)}%. Rates then rose as high as {y.max.toFixed(2)}%, and bond
            prices fall when rates rise. Today they start from {y.latest.toFixed(2)}% ({y.latest_date}), and a bond
            fund's starting yield is the main driver of its next years' return: that is why the planning guidelines
            expect bonds to beat inflation from here. Their job in the plan is to soften falls and keep money that is
            needed soon: the plan holds more of them for short goals, matched to each goal's horizon.
          </div>
        )}
        <p className="muted small">
          {v.note} "Expected after inflation": {v.assumptions.source} ({pct(v.assumptions.inflation, 1)} inflation),
          a planning assumption, not a forecast; none exists for gold, crypto or single stocks. Inflation: {v.inflation.source}.
          {y && <> Yields: {y.source}.</>}
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
