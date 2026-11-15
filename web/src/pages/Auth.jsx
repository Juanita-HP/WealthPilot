import { useState } from "react";
import { api } from "../lib.js";

export default function Auth({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const demoSignIn = async persona => {
    setError("");
    setBusy(true);
    try {
      const r = await api("/auth/demo/" + persona, { method: "POST" });
      await onSignedIn(r.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const submit = async e => {
    e.preventDefault();
    setError("");
    if (mode === "signup" && password !== confirm) { setError("Passwords do not match."); return; }
    setBusy(true);
    try {
      const r = await api("/auth/" + mode, { method: "POST", body: { username, password } });
      await onSignedIn(r.token);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="onboarding">
      <div className="brand" style={{ cursor: "default" }}>
        <div className="logo"><i></i><i></i><i></i></div>
        <strong>WealthPilot</strong>
      </div>
      <div className="eyebrow" style={{ marginTop: 40 }}>PERSONALIZED INVESTMENT RESEARCH</div>
      <h1 className="intro-title">{mode === "login" ? "Welcome back." : "Create your account."}</h1>
      <p className="intro-sub">
        WealthPilot is an educational simulation: a plan built around your goals, explained step by step.
        Use a <b>fictional</b> account for the demo. Do not use a real password or real banking information.
      </p>
      <form className="question-card" onSubmit={submit}>
        <div className="tabs" style={{ marginTop: 0 }}>
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => { setMode("login"); setError(""); }}>Sign in</button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => { setMode("signup"); setError(""); }}>Create an account</button>
        </div>
        <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input id="username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="password">Password{mode === "signup" ? " (8 characters or more)" : ""}</label>
            <input id="password" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
                   value={password} onChange={e => setPassword(e.target.value)} />
          </div>
          {mode === "signup" && (
            <div className="field">
              <label htmlFor="confirm">Confirm password</label>
              <input id="confirm" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} />
            </div>
          )}
        </div>
        {error && <div className="error-text">{error}</div>}
        <div className="question-actions">
          <span />
          <button className="primary-btn" disabled={busy || !username || !password}>
            {busy ? "Please wait…" : mode === "login" ? "Sign in →" : "Create my account →"}
          </button>
        </div>
      </form>
      <div className="question-card" style={{ marginTop: 18 }}>
        <div className="eyebrow" style={{ marginTop: 0 }}>INSTANT DEMO PERSONAS · 1-CLICK SIGN IN</div>
        <h2 style={{ marginTop: 6, fontSize: 18 }}>Explore a case persona in one click</h2>
        <p className="muted small" style={{ marginTop: 4 }}>
          Skip the 14-question onboarding and jump straight into the plan, time machine, and AI agents with one of the three benchmark personas:
        </p>
        <div className="choices three" style={{ marginTop: 12 }}>
          <button type="button" className="choice" disabled={busy} onClick={() => demoSignIn("Amira")}>
            <strong>Amira · 26 yrs</strong>
            <small>Growth (8/10 risk) · $95k income · Long-term growth (20 yrs) · Tech & crypto</small>
          </button>
          <button type="button" className="choice" disabled={busy} onClick={() => demoSignIn("Mateo")}>
            <strong>Mateo · 41 yrs</strong>
            <small>Balanced (6/10 risk) · $110k income · Children's education & Retirement · Strict ESG (no fossil fuels)</small>
          </button>
          <button type="button" className="choice" disabled={busy} onClick={() => demoSignIn("Robert")}>
            <strong>Robert · 59 yrs</strong>
            <small>Moderate goal cap (4/10 risk) · $140k income · Retirement in 4 yrs · Capital preservation</small>
          </button>
        </div>
      </div>
    </section>
  );
}
