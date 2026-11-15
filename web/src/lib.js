// Shared helpers: API client, formatting, Yahoo market-data calls (from the template), watchlist storage.

const TOKEN_KEY = "wealthpilot_token_v1";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}
export function setToken(token) {
  try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage off */ }
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, signal } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers.Authorization = "Bearer " + token;
  const response = await fetch("/api" + path, { method, headers, signal, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const detail = data?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : "Request failed (" + response.status + ").");
  }
  return data;
}

// ---------------------------------------------------------------- formatting

export const num = x => typeof x === "number" && Number.isFinite(x);

export const fmt = x => num(x)
  ? x.toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  : "Unavailable";

export function compact(x) {
  if (!num(x)) return "Unavailable";
  for (const [size, suffix] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]]) {
    if (Math.abs(x) >= size) return (x / size).toFixed(2) + suffix;
  }
  return fmt(x);
}

export const dollars = x => num(x) ? (x < 0 ? "−$" : "$") + Math.abs(Math.round(x)).toLocaleString("en-CA") : "—";
export const pct = (x, digits = 0) => num(x) ? (x * 100).toFixed(digits) + "%" : "—";
export const signedPct = (x, digits = 1) => num(x) ? (x > 0 ? "+" : "") + (x * 100).toFixed(digits) + "%" : "—";

export function longDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T12:00:00" : iso);
  return d.toLocaleDateString("en-CA", { year: "numeric", month: "long", day: "numeric" });
}

export const PALETTE = ["#172025", "#c5ad83", "#188263", "#7a8b99", "#d6a93a", "#c45454", "#4f6d7a", "#a3b18a", "#8d6e63", "#b8c1c6", "#6c5b7b", "#e0c9a6"];

// ---------------------------------------------------------------- Yahoo market data (template logic)
// The browser cannot call Yahoo directly (CORS), so the WealthPilot API relays these requests server side.

export const YAHOO = "/api/yahoo/q1";
export const YAHOO2 = "/api/yahoo/q2";

export async function requestJSON(url, signal) {
  const response = await fetch(url, { signal });
  if (!response.ok) throw Error("HTTP " + response.status);
  return await response.json();
}

export function chartURL(s, range, interval, extra = {}) {
  return YAHOO + "/v8/finance/chart/" + encodeURIComponent(s) + "?" +
    new URLSearchParams({ range, interval, includePrePost: "false", ...extra });
}

export async function getChart(s, range, interval, extra = {}) {
  const data = await requestJSON(chartURL(s, range, interval, extra));
  if (data.chart?.error) throw Error(data.chart.error.description || "Yahoo chart error");
  const result = data.chart?.result?.[0];
  if (!result) throw Error("No stock data returned");
  return result;
}

export function candles(r) {
  const q = r.indicators?.quote?.[0] || {};
  return (r.timestamp || []).map((t, i) => ({
    t: t * 1000, open: q.open?.[i], high: q.high?.[i],
    low: q.low?.[i], close: q.close?.[i], volume: q.volume?.[i],
  })).filter(x => num(x.close));
}

export const RANGES = {
  "1d": ["1d", "5m"], "5d": ["5d", "15m"], "1mo": ["1mo", "1d"],
  "3mo": ["3mo", "1d"], "6mo": ["6mo", "1d"], "ytd": ["ytd", "1d"],
  "1y": ["1y", "1d"], "5y": ["5y", "1wk"], "max": ["max", "1mo"],
};

export async function verifyTicker(symbol) {
  const result = await getChart(symbol, "5d", "1d");
  const meta = result.meta || {};
  const bars = candles(result);
  if (!num(meta.regularMarketPrice) && bars.length === 0) throw Error("No valid market data");
  return { symbol: (meta.symbol || symbol).toUpperCase(), name: meta.longName || meta.shortName || symbol };
}

export async function resolveTicker(input) {
  const q = input.trim().toUpperCase();
  if (!q) throw Error("Enter a ticker.");
  const candidates = q.includes(".") ? [q] : [q + ".TO", q];
  for (const candidate of candidates) {
    try { return await verifyTicker(candidate); }
    catch (err) { console.warn("Ticker verification failed:", candidate, err.message); }
  }
  throw Error("Stock not found.");
}

// ---------------------------------------------------------------- watchlist (browser storage, as in the template)

const WATCHLIST_KEY = "wealthpilot_watchlist_v1";

export function getWatchlist() {
  try {
    const saved = JSON.parse(localStorage.getItem(WATCHLIST_KEY) || "[]");
    return Array.isArray(saved)
      ? saved.filter(item => item && typeof item.symbol === "string" && typeof item.name === "string")
      : [];
  } catch {
    return [];
  }
}

export function saveWatchlist(items) {
  try {
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(items));
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- navigation (hash routes)

export function go(page, arg = "") {
  window.location.hash = "/" + page + (arg ? "/" + encodeURIComponent(arg) : "");
}
