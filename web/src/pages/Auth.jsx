import { useState } from "react";
import { api } from "../lib.js";

export default function Auth({ onSignedIn }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
    </section>
  );
}
