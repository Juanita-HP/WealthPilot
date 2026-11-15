import { useEffect, useRef, useState } from "react";
import { api, pct } from "../lib.js";

// Search limited to investments the devil's advocate can review (stored universe + live assets that pass the data
// rules on the server). Matches without enough data are not offered; their number is shown.
function AssetSearch({ value, onPick }) {
  const [query, setQuery] = useState("");
  const [data, setData] = useState(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const token = useRef(0);

  useEffect(() => {
    const id = ++token.current;
    setLoading(true);
    const timer = setTimeout(() => {
      api("/advocate/search?q=" + encodeURIComponent(query.trim()))
        .then(r => { if (id === token.current) { setData(r); setActive(-1); } })
        .catch(e => { if (id === token.current) setData({ results: [], hidden: 0, note: e.message }); })
        .finally(() => { if (id === token.current) setLoading(false); });
    }, query.trim() ? 350 : 0);
    return () => clearTimeout(timer);
  }, [query]);

  const results = data?.results || [];
  const pick = item => { onPick(item); setQuery(""); setOpen(false); };
  const onKeyDown = e => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (!results.length) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((active + 1) % results.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((active - 1 + results.length) % results.length); }
    else if (e.key === "Enter") { e.preventDefault(); pick(results[active >= 0 ? active : 0]); }
  };
  return (
    <div className="advocate-search">
     <div className="searchbox">
      <div className="searchform compact">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
          <circle cx="10.8" cy="10.8" r="7.2" /><path d="m16.2 16.2 5 5" />
        </svg>
        <input placeholder={value?.symbol ? `${value.symbol}${value.name ? " · " + value.name : ""} (type to change)` : "Search a stock, ETF or crypto"}
               value={query} autoComplete="off" spellCheck="false" aria-label="Search an investment to review"
               onChange={e => { setQuery(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
               onBlur={() => setTimeout(() => setOpen(false), 150)} onKeyDown={onKeyDown} />
      </div>
      {open && (
        <div className="suggestions">
          {loading && !results.length && <div className="suggestion"><small>Checking which matches have enough data…</small></div>}
          {results.map((item, i) => (
            <div key={item.symbol} className={"suggestion" + (i === active ? " active" : "")}
                 onMouseDown={e => { e.preventDefault(); pick(item); }}>
              <div><strong>{item.symbol}</strong><small>{item.name}</small></div>
              <em>{item.type}{item.exchange ? " · " + item.exchange : ""}</em>
            </div>
          ))}
          {!loading && !results.length && <div className="suggestion"><small>No investment with enough data matches “{query}”.</small></div>}
          {(data?.hidden > 0 || data?.note) && (
            <div className="suggestion muted-row">
              <small>
                {data.hidden > 0 && `${data.hidden} other match${data.hidden > 1 ? "es are" : " is"} not offered: not enough data for a reviewed answer. `}
                {data.note}
              </small>
            </div>
          )}
        </div>
      )}
     </div>
      {data?.rules && <p className="muted small" style={{ margin: "8px 2px 0" }}>{data.rules}</p>}
    </div>
  );
}

const METRICS = [["cagr", "Annual return", true], ["volatility", "Volatility", true], ["max_drawdown", "Worst fall", true], ["sharpe", "Sharpe ratio", false]];

function renderInline(text) {
  const parts = String(text).split(/(\*\*[^*]+\*\*|\[R\d+(?:,\s*R\d+)*\]|_[^_]+_)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{renderInline(part.slice(2, -2))}</strong>;
    }
    if (/^\[R\d+(?:,\s*R\d+)*\]$/.test(part)) {
      const ids = part.slice(1, -1).split(",").map(s => s.trim()).filter(Boolean);
      return (
        <span key={i} style={{ display: "inline-flex", gap: 3, marginLeft: 3, verticalAlign: "baseline" }}>
          {ids.map(rid => (
            <button
              key={rid}
              type="button"
              onClick={e => {
                e.preventDefault();
                const el = document.getElementById(`receipt-${rid}`);
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "center" });
                }
              }}
              title={`Verified calculation receipt ${rid} — click to inspect the plain-language summary below`}
              style={{
                fontSize: 11, padding: "1px 6px", borderRadius: 4, textDecoration: "none",
                background: "rgba(23,32,37,0.09)", color: "#2b5876", fontWeight: 700,
                border: "1px solid rgba(43,88,118,0.22)", cursor: "pointer", lineHeight: 1.35,
              }}
            >
              {rid}
            </button>
          ))}
        </span>
      );
    }
    if (part.startsWith("_") && part.endsWith("_") && part.length > 2) {
      return <em key={i} className="muted small">{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function FormattedAnswer({ text }) {
  const lines = String(text || "").split(/\r?\n/);
  const elements = [];
  let listItems = [];
  const flushList = (key) => {
    if (listItems.length > 0) {
      elements.push(
        <ul key={"ul-" + key} style={{ margin: "8px 0 12px 20px", padding: 0, lineHeight: 1.65 }}>
          {listItems.map((item, idx) => <li key={idx} style={{ marginBottom: 6 }}>{renderInline(item)}</li>)}
        </ul>
      );
      listItems = [];
    }
  };
  lines.forEach((raw, idx) => {
    const line = raw.trim();
    if (!line) {
      flushList(idx);
      return;
    }
    if (/^---+$/.test(line)) {
      flushList(idx);
      elements.push(<hr key={idx} style={{ border: "none", borderTop: "1px solid rgba(0,0,0,0.1)", margin: "16px 0" }} />);
      return;
    }
    const hMatch = line.match(/^(#{1,4})\s+(.*)$/);
    if (hMatch) {
      flushList(idx);
      elements.push(
        <h3 key={idx} style={{ fontSize: 16, fontWeight: 700, margin: "16px 0 6px" }}>
          {renderInline(hMatch[2])}
        </h3>
      );
      return;
    }
    const bMatch = line.match(/^[-*•]\s+(.*)$/);
    if (bMatch) {
      listItems.push(bMatch[1]);
      return;
    }
    flushList(idx);
    elements.push(
      <p key={idx} style={{ margin: "8px 0", lineHeight: 1.65 }}>
        {renderInline(line)}
      </p>
    );
  });
  flushList("end");
  return <div style={{ fontSize: 14, marginTop: 16 }}>{elements}</div>;
}

export default function Advocate() {
  // A stock sent from its research page ("Challenge this stock with the Devil's Advocate").
  const [fromResearch] = useState(() => { try { return sessionStorage.getItem("wp_advocate_symbol"); } catch { return null; } });
  const [asset, setAsset] = useState({ symbol: fromResearch || "TSLA", name: fromResearch ? "" : "Tesla" });
  const symbol = asset.symbol;
  const [weight, setWeight] = useState(30);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);

  useEffect(() => { try { sessionStorage.removeItem("wp_advocate_symbol"); } catch { /* storage off */ } }, []);
  const suggested = "Ask the AI agents to analyze how recent news and risks on " + symbol + " affect my profile";

  const run = async (sym = symbol) => {
    setBusy(true); setError("");
    try {
      const r = await api("/advocate", { method: "POST", body: { symbol: sym, weight: weight / 100 } });
      setReview(r);
      if (r.asset) setAsset({ symbol: r.asset.symbol, name: r.asset.name });
    }
    catch (e) { setError(e.message); setReview(null); }
    finally { setBusy(false); }
  };
  useEffect(() => { run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
            <label>I want to put… <b>{symbol}</b>{asset.name ? " · " + asset.name : ""}</label>
            <AssetSearch value={asset} onPick={item => { setAsset(item); run(item.symbol); }} />
          </div>
          <div className="field">
            <label>…this share of my portfolio: {weight}%</label>
            <div className="range-row" style={{ height: 48 }}>
              <input type="range" min="1" max="60" value={weight} onChange={e => setWeight(Number(e.target.value))} />
            </div>
          </div>
        </div>
        <div className="question-actions"><span /><button className="primary-btn" disabled={busy} onClick={() => run()}>{busy ? "Reviewing…" : "Review this idea →"}</button></div>
      </div>
      {error && <div className="error-text">{error}</div>}
      {review && (
        <>
          <div className={"pill " + review.verdict.tone} style={{ fontSize: 16, marginTop: 26 }}>{review.verdict.text}</div>
          {review.asset && (
            <p className="muted small" style={{ marginTop: 10 }}>
              {review.asset.symbol} · {review.asset.name} · {review.asset.type}. Data: {review.asset.basis}.
              {review.asset.liquidity && ` Traded on an average day: about $${Math.round(review.asset.liquidity.adv_cad).toLocaleString("en-CA")} CAD (${review.asset.liquidity.window}).`}
            </p>
          )}
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
        <button type="button" className="quiet-btn" style={{ marginBottom: 12 }} onClick={() => setQuestion(suggested)}>
          {suggested}
        </button>
        <div className="field">
          <textarea placeholder="For example: should I put more into Canadian banks?" value={question} onChange={e => setQuestion(e.target.value)} />
        </div>
        <div className="question-actions"><span /><button className="primary-btn" disabled={!question.trim() || answer?.loading} onClick={ask}>
          {answer?.loading ? "The agents are working…" : "Ask →"}</button></div>
        {answer?.error && <div className="analysis-status">{answer.error}</div>}
        {answer?.text && (
          <>
            <FormattedAnswer text={answer.text} />
            {answer.receipts?.length > 0 && (
              <div
                style={{
                  marginTop: 20,
                  padding: "16px 18px",
                  borderRadius: 12,
                  background: "rgba(43, 88, 118, 0.05)",
                  border: "1px solid rgba(43, 88, 118, 0.18)",
                }}
              >
                <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                  <div>
                    <div className="eyebrow" style={{ marginBottom: 2 }}>BEGINNER'S VERIFICATION GUIDE · CALCULATION RECEIPTS</div>
                    <h3 style={{ margin: 0, fontSize: 16 }}>What do the [R1], [R2] badges mean?</h3>
                  </div>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                    {answer.report && (
                      <span className={"pill " + (answer.report.passed ? "green" : "yellow")} style={{ margin: 0, fontSize: 12 }}>
                        {answer.report.passed
                          ? `✓ ${answer.report.claims?.filter(c => c.status === "verified").length || 0}/${answer.report.claims?.length || 0} figures verified by code`
                          : `Verifier checked ${answer.report.claims?.length || 0} figures`}
                      </span>
                    )}
                    {answer.aws_trace_id && (
                      <span
                        className="pill info"
                        style={{ margin: 0, fontSize: 12 }}
                        title={`Logged in Amazon DynamoDB table ${answer.aws_trace_table || "wealthpilot-traces"}`}
                      >
                        AWS DynamoDB Audit: {answer.aws_trace_id}
                      </span>
                    )}
                  </div>
                </div>
                <p className="small muted" style={{ margin: "8px 0 14px", lineHeight: 1.55 }}>
                  In WealthPilot, AI agents are <b>never allowed to invent or calculate numbers on their own</b>. Every time the
                  Advisor or Devil's Advocate cites a badge like <b>R1</b> or <b>R2</b>, that number comes directly from one of the
                  verified calculator "receipts" summarized in plain language below—and a deterministic code verifier checks every
                  single number before you see the answer.
                </p>
                <div style={{ display: "grid", gap: 10 }}>
                  {answer.receipts.map(r => (
                    <div
                      key={r.id}
                      id={`receipt-${r.id}`}
                      style={{
                        padding: "12px 14px",
                        borderRadius: 8,
                        background: "#fff",
                        border: "1px solid rgba(0,0,0,0.08)",
                      }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                        <div>
                          <span
                            style={{
                              fontSize: 12,
                              padding: "2px 7px",
                              marginRight: 8,
                              borderRadius: 4,
                              background: "rgba(43,88,118,0.12)",
                              color: "#2b5876",
                              fontWeight: 700,
                            }}
                          >
                            {r.id}
                          </span>
                          <strong style={{ fontSize: 14 }}>{r.plain_title || r.tool}</strong>
                        </div>
                        <span className="muted small">{r.agent_label || r.agent} · tool: <code>{r.tool}</code></span>
                      </div>
                      {r.plain_summary && (
                        <p style={{ margin: "6px 0 4px", fontSize: 13.5, lineHeight: 1.5 }}>{r.plain_summary}</p>
                      )}
                      {r.key_facts?.length > 0 && (
                        <ul style={{ margin: "6px 0 0 18px", padding: 0, fontSize: 13, lineHeight: 1.55, color: "#2c3e50" }}>
                          {r.key_facts.map((fact, idx) => (
                            <li key={idx} style={{ marginBottom: 2 }}>{fact}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
                <details style={{ marginTop: 12, fontSize: 12.5 }}>
                  <summary style={{ cursor: "pointer", fontWeight: 600, color: "#4f6d7a" }}>
                    Inspect raw tool JSON receipts & multi-agent execution trace ({answer.receipts.length} receipts)
                  </summary>
                  <pre
                    style={{
                      marginTop: 8,
                      padding: 10,
                      borderRadius: 6,
                      background: "rgba(0,0,0,0.04)",
                      overflowX: "auto",
                      maxHeight: 280,
                      fontSize: 11.5,
                    }}
                  >
                    {JSON.stringify(
                      {
                        aws_dynamodb_table: answer.aws_trace_table || "wealthpilot-traces",
                        aws_turn_id: answer.aws_trace_id || "local",
                        verification_coverage: answer.report?.coverage,
                        trace: answer.trace,
                        receipts: answer.receipts.map(({ id, tool, agent, inputs, output, error }) => ({
                          id, tool, agent, inputs, output, error,
                        })),
                      },
                      null,
                      2
                    )}
                  </pre>
                </details>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}
