// First-visit questionnaire: one question per page, full screen (second template), amounts in dollars.
import { useEffect, useMemo, useState } from "react";
import { api, dollars, pct } from "../lib.js";

const HINTS = {
  drop_reaction: { sell_all: "Avoid any further loss", sell_some: "Reduce the exposure", hold: "Give it time to recover",
                   buy_more: "Prices are lower, so buy more" },
  goal: { preserve: "Protect the initial amount", income: "Prioritize distributions",
          balanced: "Balance stability and appreciation", max_growth: "Prioritize capital appreciation" },
  experience: { none: "I have never invested", beginner: "Still learning how markets work",
                intermediate: "Familiar with stocks and market risk", advanced: "Comfortable evaluating investments" },
  return_expectation: { lt3: "Close to a savings account", "3to5": "Mostly bonds", "5to7": "A balanced mix",
                        "7to10": "Mostly stocks", gt10: "More than stock markets have averaged" },
  esg: { none: "Financial factors first", prefer: "Use a screened fund where possible", exclude: "Only screened investments" },
  crypto: { no: "Keep crypto out", small: "A small slice at most", open: "Up to the limit of my level" },
  region: { canada: "Canada 60%, U.S. 30%, rest of the developed world 10%",
            balanced: "Canada 40%, U.S. 45%, rest of the developed world 15%",
            us: "U.S. 70%, Canada 20%, rest of the developed world 10%",
            global: "U.S. 45%, Canada 25%, developed world 20%, emerging markets 10%" },
};
const EMPLOYMENT_HINT = { public: "Highest income stability", salaried: "Steady pay", retired: "Pension income",
                          contract: "Income varies", self_employed: "Income varies", student: "Limited income",
                          unemployed: "No employment income" };
const GOAL_HINT = { emergency_fund: "3 to 6 months of expenses, always available", home_purchase: "Down payment for a first home",
                    project: "A date and an amount", retirement: "Income when you stop working",
                    income: "Regular payments from your investments", legacy: "Something to pass on" };

function Choices({ options, value, onPick, hints = {}, cols, multi = false }) {
  return (
    <div className={"choices" + (cols === 3 ? " three" : "")}>
      {options.map(o => {
        const selected = multi ? value.includes(o.value) : value === o.value;
        return (
          <button type="button" key={o.value} className={"choice" + (selected ? " selected" : "")} onClick={() => onPick(o.value)}>
            <strong>{o.label}</strong>
            {(hints[o.value] || o.hint) && <small>{hints[o.value] || o.hint}</small>}
          </button>
        );
      })}
    </div>
  );
}

function Money({ label, value, onChange, hint, step = 100 }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input type="number" min="0" step={step} value={Number.isFinite(value) ? value : ""}
             onChange={e => onChange(e.target.value === "" ? 0 : Number(e.target.value))} />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function defaultGoal(type, fin, label) {
  const expenses = fin.monthly_expenses || 1;
  return {
    name: label, type,
    horizon_years: type === "emergency_fund" ? 0 : type === "retirement" ? Math.max(1, 65 - fin.age) : 5,
    target_amount: type === "emergency_fund" ? Math.round(expenses * (fin.employment === "public" || fin.employment === "salaried" ? 3 : 6) / 100) * 100 : 50000,
    current_amount: 0, monthly_contribution: 0,
  };
}

export default function Onboarding({ editing, onSaved, onCancel }) {
  const [meta, setMeta] = useState(null);
  const [draft, setDraft] = useState(null);
  const [step, setStep] = useState(0);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const m = await api("/meta");
        setMeta(m);
        if (editing) {
          const p = await api("/profile");
          setDraft({ ...p.onboarding, _goalsTouched: true });
        } else {
          setDraft(m.blank);
        }
      } catch (e) { setError(e.message); }
    })();
  }, [editing]);

  const fin = draft?.financials;
  // Until the investor edits the goals, the default goals follow the amounts entered: the emergency fund holds the
  // cash savings and the long-term goal holds the investments, so the plan invests exactly what was declared.
  const set = (section, patch) => setDraft(d => {
    const next = { ...d, [section]: { ...d[section], ...patch } };
    if (section === "financials" && !d._goalsTouched) {
      const f = next.financials;
      next.goals = d.goals.map(g => g.type === "emergency_fund" ? { ...g, current_amount: f.cash_savings }
        : g.type === "retirement" ? { ...g, current_amount: f.investments } : g);
    }
    return next;
  });

  // Live preview of the financial ratios and, on the last step, of the profile.
  useEffect(() => {
    if (!draft) return;
    const t = setTimeout(async () => {
      try { setPreview(await api("/onboarding/preview", { method: "POST", body: { onboarding: draft } })); }
      catch { setPreview(null); }
    }, 250);
    return () => clearTimeout(t);
  }, [draft]);

  const steps = useMemo(() => {
    if (!meta || !draft) return [];
    const goalsList = draft.goals || [];
    const assigned = goalsList.reduce((s, g) => s + (g.current_amount || 0), 0);
    const available = fin.cash_savings + fin.investments;
    // Risk questions talk about the money exposed to markets: what is set aside for goals other than the cushion.
    const invested = goalsList.filter(g => g.type !== "emergency_fund").reduce((s, g) => s + (g.current_amount || 0), 0);
    const amount = Math.max(invested || fin.investments, 1000);
    const goalLabel = Object.fromEntries(meta.goal_types.map(g => [g.value, g.label]));
    const q = meta.questions;
    const goals = draft.goals || [];
    const prefs = draft.preferences;
    const toggleGoal = type => setDraft(d => {
      const has = d.goals.some(g => g.type === type);
      return { ...d, _goalsTouched: true, goals: has ? d.goals.filter(g => g.type !== type) : [...d.goals, defaultGoal(type, d.financials, goalLabel[type])] };
    });
    const setGoal = (type, patch) => setDraft(d => ({ ...d, _goalsTouched: true, goals: d.goals.map(g => g.type === type ? { ...g, ...patch } : g) }));
    const tol = draft.tolerance;
    const choice = (id, title, help, extra = {}) => ({
      title, help, valid: Boolean(tol[id]),
      body: <Choices options={q[id].options} value={tol[id]} hints={HINTS[id]} onPick={v => set("tolerance", { [id]: v })} {...extra} />,
    });
    const f = preview?.financials;
    return [
      {
        title: "How would you like to start?",
        help: "Fill in your own situation, or start from one of the case's personas and adjust it.",
        valid: true,
        body: <Choices options={[{ value: "", label: "My own situation", hint: "Start from typical values" },
                                 ...Object.entries(meta.personas).map(([name, p]) => ({
                                   value: name, label: name,
                                   hint: `${p.financials.age} years old · ${dollars(p.financials.annual_income)} a year · ${p.goals.map(g => g.name).join(", ")}` }))]}
                       value={draft._persona || ""}
                       onPick={v => setDraft(v ? { ...meta.personas[v], _persona: v, _goalsTouched: true } : { ...meta.blank, _persona: "" })} />,
      },
      {
        title: "What is your work situation?",
        help: "Stable income makes it easier to ride out a market decline without selling.",
        valid: Boolean(fin.employment),
        body: <Choices options={meta.employment} value={fin.employment} hints={EMPLOYMENT_HINT} onPick={v => set("financials", { employment: v })} />,
      },
      {
        title: "A little about you.",
        help: "Your age and the people who depend on you shape how much risk you can carry.",
        valid: fin.age >= 18 && fin.age <= 100,
        body: (
          <div className="form-grid">
            <div className="field"><label>Age</label>
              <input type="number" min="18" max="100" value={fin.age} onChange={e => set("financials", { age: Number(e.target.value) })} /></div>
            <div className="field"><label>Province or territory</label>
              <select value={fin.province} onChange={e => set("financials", { province: e.target.value })}>
                {meta.provinces.map(p => <option key={p}>{p}</option>)}</select></div>
            <div className="field"><label>People who depend on you</label>
              <input type="number" min="0" max="10" value={fin.dependents} onChange={e => set("financials", { dependents: Number(e.target.value) })} /></div>
          </div>
        ),
      },
      {
        title: "Your income and spending.",
        help: "Approximate amounts are enough. They measure your capacity to absorb a decline.",
        valid: fin.monthly_expenses > 0,
        body: (
          <>
            <div className="form-grid">
              <Money label="Gross annual income" value={fin.annual_income} step={1000} onChange={v => set("financials", { annual_income: v })} />
              <Money label="Monthly expenses" value={fin.monthly_expenses} onChange={v => set("financials", { monthly_expenses: v })} />
              <Money label="What you can save each month" value={fin.monthly_savings} step={50} onChange={v => set("financials", { monthly_savings: v })} />
            </div>
            {f && <div className="metrics-inline">
              <div><span>Savings rate</span><strong>{pct(f.savings_rate)}</strong></div>
              <div><span>Left after expenses</span><strong>{dollars(fin.annual_income / 12 - fin.monthly_expenses)}</strong></div>
              <div><span>Emergency target</span><strong>{dollars(f.emergency_target)}</strong></div>
            </div>}
            {fin.monthly_savings > fin.annual_income / 12 - fin.monthly_expenses + 1 &&
              <div className="pill yellow">Your savings are higher than your income minus your expenses. Please check the amounts.</div>}
          </>
        ),
      },
      {
        title: "What you own and what you owe.",
        help: "Your net worth and your cash cushion show how much of a decline you could absorb.",
        valid: true,
        body: (
          <>
            <div className="form-grid">
              <Money label="Cash savings (savings account)" value={fin.cash_savings} step={1000} onChange={v => set("financials", { cash_savings: v })} />
              <Money label="Investments you already hold (TFSA, RRSP, funds, stocks)" value={fin.investments} step={1000} onChange={v => set("financials", { investments: v })} />
              <Money label="Other assets, net of mortgage (home, etc.)" value={fin.other_assets} step={1000} onChange={v => set("financials", { other_assets: v })} />
              <Money label="Debts excluding mortgage (student loan, car, cards)" value={fin.debts} step={1000} onChange={v => set("financials", { debts: v })} />
            </div>
            {f && <div className="metrics-inline">
              <div><span>Net worth</span><strong>{dollars(f.net_worth)}</strong></div>
              <div><span>Cash cushion</span><strong>{f.emergency_months.toFixed(1)} months</strong></div>
              <div><span>Debt to income</span><strong>{pct(f.debt_to_income)}</strong></div>
            </div>}
          </>
        ),
      },
      {
        title: "What are you investing for?",
        help: "Each goal has its own horizon, so each gets its own sub-portfolio. Choose one or more.",
        valid: goals.length > 0 && goals.every(g => g.name.trim()) && assigned <= available + 1,
        body: (
          <>
            <Choices multi options={meta.goal_types} value={goals.map(g => g.type)} hints={GOAL_HINT} onPick={toggleGoal} />
            {goals.map(g => (
              <div className="goal-edit" key={g.type}>
                <div className="field" style={{ maxWidth: 380 }}>
                  <label>{goalLabel[g.type]} · name</label>
                  <input value={g.name} onChange={e => setGoal(g.type, { name: e.target.value })} />
                </div>
                <div className="form-grid">
                  {g.type === "emergency_fund"
                    ? <div className="field"><span className="label">Horizon</span><strong style={{ paddingTop: 12 }}>Immediate</strong></div>
                    : <div className="field"><label>In how many years?</label>
                        <input type="number" min="0.5" max="60" step="0.5" value={g.horizon_years}
                               onChange={e => setGoal(g.type, { horizon_years: Number(e.target.value) })} /></div>}
                  <Money label="Target amount" value={g.target_amount} step={1000} onChange={v => setGoal(g.type, { target_amount: v })} />
                  <Money label="Already set aside" value={g.current_amount} step={1000} onChange={v => setGoal(g.type, { current_amount: v })} />
                  <Money label="Per month" value={g.monthly_contribution} step={50} onChange={v => setGoal(g.type, { monthly_contribution: v })} />
                </div>
              </div>
            ))}
            {goals.length > 0 && <>
              <div className="metrics-inline">
                <div><span>Already set aside for your goals (your simulated portfolio)</span><strong>{dollars(assigned)}</strong></div>
                <div><span>Cash savings + investments you hold</span><strong>{dollars(available)}</strong></div>
                <div><span>Planned savings a month</span><strong>{dollars(goals.reduce((s, g) => s + g.monthly_contribution, 0))} of {dollars(fin.monthly_savings)}</strong></div>
              </div>
              {assigned > available + 1 && <div className="pill red">
                The goals count {dollars(assigned - available)} more than your savings and investments. Lower the amounts already set aside.</div>}
              {assigned <= available + 1 && available - assigned > Math.max(1000, 0.05 * available) && <div className="pill yellow">
                {dollars(available - assigned)} of your savings and investments is not assigned to a goal, so the plan will not invest it.</div>}
            </>}
          </>
        ),
      },
      choice("drop_reaction", `Your ${dollars(amount)} of investments are worth ${dollars(amount * 0.8)} after a few months. What do you do?`,
             "There is no right answer: this measures what you would actually live with."),
      {
        title: "Over one year, which range of results would you accept?",
        help: `With ${dollars(amount)} invested. Higher possible gains come with deeper possible losses.`,
        valid: Boolean(tol.range_choice),
        body: <Choices options={q.range_choice.options.map(o => ({
                         value: o.value, label: `Between ${dollars(amount * (1 + meta.ranges[o.value][1]))} and ${dollars(amount * (1 + meta.ranges[o.value][0]))}`,
                         hint: o.label }))}
                       value={tol.range_choice} onPick={v => set("tolerance", { range_choice: v })} />,
      },
      choice("goal", "What matters most to you?", "Different goals may conflict with highly volatile investments."),
      choice("return_expectation", "What average annual return do you expect?", "We compare it with prudent planning assumptions for your level.", { cols: 3 }),
      choice("experience", "How experienced are you with investing?", "This sets the depth of the explanations and which tools are offered."),
      {
        title: "Which themes interest you?",
        help: "Optional. Themes become small positions, always inside the limits of your level.",
        valid: true,
        body: <Choices multi cols={3} options={meta.themes.map(t => ({ value: t.value, label: t.label, hint: t.tickers.join(", ") }))}
                       value={prefs.themes || []}
                       onPick={v => set("preferences", { themes: (prefs.themes || []).includes(v) ? prefs.themes.filter(x => x !== v) : [...(prefs.themes || []), v] })} />,
      },
      {
        title: "Any other preferences?",
        help: "Optional. Preferences apply inside your limits, never above them.",
        valid: true,
        body: (
          <>
            <div className="question"><div className="label">Responsible investing (ESG)</div>
              <Choices cols={3} options={meta.esg} value={prefs.esg} hints={HINTS.esg} onPick={v => set("preferences", { esg: v })} /></div>
            <div className="question"><div className="label">Crypto assets</div>
              <Choices cols={3} options={meta.crypto} value={prefs.crypto} hints={HINTS.crypto} onPick={v => set("preferences", { crypto: v })} /></div>
            <div className="question"><div className="label">Geographic mix</div>
              <Choices options={meta.region} value={prefs.region} hints={HINTS.region} onPick={v => set("preferences", { region: v })} /></div>
            <div className="question"><div className="label">Other</div>
              <Choices multi options={[{ value: "fossil", label: "Exclude fossil fuels", hint: "Leaves out energy companies" },
                                       { value: "simple", label: "Keep it simple", hint: "Fewer funds, easy to follow" }]}
                       value={[...((prefs.values || []).includes("no_fossil_fuels") ? ["fossil"] : []), ...(prefs.simplicity ? ["simple"] : [])]}
                       onPick={v => v === "fossil"
                         ? set("preferences", { values: (prefs.values || []).includes("no_fossil_fuels") ? [] : ["no_fossil_fuels"] })
                         : set("preferences", { simplicity: !prefs.simplicity })} /></div>
          </>
        ),
      },
      {
        title: "Your investor profile.",
        help: "Your level follows the lower of your capacity and your tolerance. Each goal is then adjusted to its horizon.",
        valid: Boolean(preview?.profile),
        body: preview?.profile ? (
          <>
            <div className="analysis-grid" style={{ gridTemplateColumns: "repeat(3,minmax(0,1fr))" }}>
              <div className="analysis-stat"><span>Level from your answers</span><strong>{preview.profile.name} · {preview.profile.score_10}/10 risk</strong></div>
              <div className="analysis-stat"><span>Risk capacity</span><strong>{Math.round(preview.profile.capacity)}/100</strong></div>
              <div className="analysis-stat"><span>Risk tolerance</span><strong>{Math.round(preview.profile.tolerance)}/100</strong></div>
            </div>
            <p className="analysis-status">Suits {preview.profile.suits}.</p>
            {preview.profile.flags.map(fl => <div key={fl.code} className="pill yellow">{fl.text}</div>)}
            <div className="explanation">
              <h3>Your goals</h3>
              <ul>{preview.goals.map(g => <li key={g.name}><b>{g.name}</b>: {g.level}</li>)}</ul>
            </div>
          </>
        ) : <div className="loading">Calculating…</div>,
      },
    ];
  }, [meta, draft, preview, fin]);

  if (error) return <section className="onboarding"><div className="error-text">{error}</div></section>;
  if (!steps.length) return <section className="onboarding"><div className="loading">Loading…</div></section>;

  const s = steps[step];
  const last = step === steps.length - 1;
  const saveNow = async () => {
    setSaving(true);
    try {
      const { _goalsTouched, ...onboarding } = draft;
      await api("/profile", { method: "PUT", body: { onboarding } });
      await onSaved();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };
  const next = async () => {
    if (!last) { setStep(step + 1); window.scrollTo(0, 0); return; }
    await saveNow();
  };

  return (
    <section className="onboarding">
      <div className="eyebrow">PERSONALIZED INVESTMENT RESEARCH</div>
      <h1 className="intro-title">{editing ? "Update your goals." : "Let's understand your goals."}</h1>
      <p className="intro-sub">
        Tell us about your situation, your goals and your comfort with risk. Amounts are fictional and stay in this
        simulation; you can update them anytime. No real trades.
      </p>
      <div className="question-card">
        <div className="question-progress">QUESTION {step + 1} OF {steps.length}</div>
        <div className="progress-track"><div className="progress-fill" style={{ width: ((step + 1) / steps.length * 100) + "%" }} /></div>
        <h2>{s.title}</h2>
        <p>{s.help}</p>
        {s.body}
        <div className="question-actions">
          <div style={{ display: "flex", gap: 10 }}>
            {step > 0 && <button type="button" className="quiet-btn" onClick={() => setStep(step - 1)}>← Previous</button>}
            {onCancel && <button type="button" className="quiet-btn" onClick={onCancel}>Cancel</button>}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {!last && draft?._persona && (
              <button type="button" className="quiet-btn" disabled={saving} onClick={saveNow}>
                {saving ? "Saving…" : `Apply ${draft._persona}'s profile now (skip 14 steps) →`}
              </button>
            )}
            <button type="button" className="primary-btn" disabled={!s.valid || saving} onClick={next}>
              {saving ? "Saving…" : last ? "Save profile & continue →" : "Continue →"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
