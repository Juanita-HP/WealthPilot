import { useEffect, useState } from "react";
import { api, dollars, pct, go } from "../lib.js";

export default function Profile({ username, onChanged, onSignOut, onDeleted }) {
  const [p, setP] = useState(null);
  const [error, setError] = useState("");
  const [switching, setSwitching] = useState("");

  const load = () => api("/profile").then(setP).catch(e => setError(e.message));
  useEffect(() => { load(); }, []);

  const chooseLevel = async level => {
    await api("/profile/level", { method: "PUT", body: { level } });
    await load();
    onChanged();
  };
  const switchPersona = async persona => {
    setSwitching(persona);
    setError("");
    try {
      await api("/profile/persona/" + persona, { method: "POST" });
      await load();
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setSwitching("");
    }
  };
  const remove = async () => {
    if (!window.confirm("Delete your investor profile? You will answer the questionnaire again.")) return;
    await api("/profile", { method: "DELETE" });
    await onDeleted();
  };

  if (error) return <section className="page"><div className="error-text">{error}</div></section>;
  if (!p) return <section className="page"><div className="loading">Loading your profile…</div></section>;
  const pr = p.profile, f = p.financials;
  return (
    <section className="page">
      <div className="page-heading">
        <div className="eyebrow">INVESTOR PROFILE · {p.persona ? `${p.persona} (Demo Persona)` : username}</div>
        <h1>{pr.name} · {pr.score_10}/10 risk</h1>
        <p>Recommended level. Suits {pr.suits}.</p>
      </div>
      <div className="analysis-grid" style={{ marginTop: 0 }}>
        <div className="analysis-stat"><span>Risk capacity (what your finances allow)</span><strong>{Math.round(pr.capacity)}/100</strong></div>
        <div className="analysis-stat"><span>Risk tolerance (what you would live with)</span><strong>{Math.round(pr.tolerance)}/100</strong></div>
        <div className="analysis-stat"><span>Net worth</span><strong>{dollars(f.net_worth)}</strong></div>
        <div className="analysis-stat"><span>Cash cushion</span><strong>{f.emergency_months.toFixed(1)} months</strong></div>
      </div>
      <p className="note">Your level follows the lower of your capacity and your tolerance. Each goal is then adjusted to its horizon.</p>
      <div className="pill-stack">{pr.flags.map(fl => <div key={fl.code} className={"pill " + (fl.severity === "warning" ? "yellow" : "info")} title={fl.detail}>{fl.text}</div>)}</div>

      <div className="analysis-card">
        <div className="eyebrow">YOUR CHOICE</div>
        <h2>Prefer a more cautious level?</h2>
        <p className="analysis-status" style={{ marginTop: 0 }}>You can always choose a level below the recommended one, never above it.</p>
        <div className="choices three">
          {p.levels.map(l => (
            <button key={l.level} className={"choice" + (p.chosen_level === l.level ? " selected" : "")} onClick={() => chooseLevel(l.level)}>
              <strong>{l.name}</strong><small>Level {l.level}{l.level === pr.level ? " · recommended" : ""}</small>
            </button>
          ))}
        </div>
        <details className="more">
          <summary>Where your capacity comes from</summary>
          <div className="inner"><ul>{pr.capacity_reasons.map(r => <li key={r.label}>{r.label}: {r.points.toFixed(1)} points</li>)}</ul>
            <p className="muted">Savings rate {pct(f.savings_rate)} · debt to income {pct(f.debt_to_income)}.</p></div>
        </details>
      </div>

      <div className="analysis-card" style={{ marginTop: 18 }}>
        <div className="eyebrow">DEMO PERSONAS · 1-CLICK SWITCH</div>
        <h2>Switch to a benchmark persona</h2>
        <p className="analysis-status" style={{ marginTop: 0 }}>
          Instantly load Amira, Mateo, or Robert to compare how WealthPilot adapts the goals, portfolio, and Devil's Advocate checks.
        </p>
        <div className="choices three">
          {[
            ["Amira", "26 yrs · Growth (8/10 risk) · Long-term growth (20 yrs) · Tech & crypto"],
            ["Mateo", "41 yrs · Balanced (6/10 risk) · Education & Retirement · Strict ESG"],
            ["Robert", "59 yrs · Moderate goal cap (4/10 risk) · Retirement in 4 yrs"],
          ].map(([name, desc]) => (
            <button
              key={name}
              type="button"
              className={"choice" + (p.persona === name ? " selected" : "")}
              disabled={Boolean(switching)}
              onClick={() => switchPersona(name)}
            >
              <strong>{switching === name ? `Loading ${name}…` : p.persona === name ? `${name} (Active)` : `Load ${name}`}</strong>
              <small>{desc}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="btn-row">
        <button className="primary-btn" onClick={() => go("onboarding")}>Edit investor profile →</button>
        <button className="quiet-btn" onClick={onSignOut}>Sign out</button>
        <button className="quiet-btn danger" onClick={remove}>Delete my profile</button>
      </div>
    </section>
  );
}
