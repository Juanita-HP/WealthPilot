// Price chart of the research page: same behaviour as the template (periods, hover readout, guide line).
import { useEffect, useRef, useState } from "react";
import Chart from "chart.js/auto";
import { RANGES, candles, fmt, getChart, num } from "../lib.js";

const chartGuide = {
  id: "guide",
  afterDatasetsDraw(c) {
    const i = c.$hoverIndex;
    if (i == null) return;
    const point = c.getDatasetMeta(0).data[i];
    if (!point) return;
    const { ctx, chartArea } = c;
    ctx.save();
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#b2b7b5";
    ctx.beginPath();
    ctx.moveTo(point.x, chartArea.top);
    ctx.lineTo(point.x, chartArea.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(point.x, point.y, 5, 0, Math.PI * 2);
    ctx.fillStyle = "#fff";
    ctx.fill();
    ctx.strokeStyle = c.data.datasets[0].borderColor;
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.restore();
  },
};

const PERIODS = [["1d", "1D"], ["5d", "5D"], ["1mo", "1M"], ["3mo", "3M"], ["6mo", "6M"], ["ytd", "YTD"], ["1y", "1Y"], ["5y", "5Y"], ["max", "MAX"]];

export default function StockChart({ ticker, currency }) {
  const canvas = useRef(null);
  const chart = useRef(null);
  const [range, setRange] = useState("1d");
  const [readout, setReadout] = useState({ price: "—", date: "Hover to inspect historical prices" });
  const [status, setStatus] = useState("");

  useEffect(() => { setRange("1d"); }, [ticker]);

  useEffect(() => {
    let cancelled = false;
    const money = v => num(v) ? fmt(v) + (currency ? " " + currency : "") : "Unavailable";
    setStatus("Loading chart...");
    (async () => {
      try {
        const [period, interval] = RANGES[range];
        const r = await getChart(ticker, period, interval);
        let data = candles(r);
        if (cancelled) return;
        if (!data.length) throw Error("No price history");
        if (range === "1d") {
          const meta = r.meta || {};
          const sessionOpen = num(meta.regularMarketOpen) ? meta.regularMarketOpen : data.find(x => num(x.open))?.open;
          if (num(sessionOpen)) data = [{ t: data[0].t - 1, close: sessionOpen, isOpeningPoint: true }, ...data];
        }
        if (chart.current) { chart.current.destroy(); chart.current = null; }
        const rising = data.at(-1).close >= data[0].close;
        const color = rising ? "#188263" : "#c45454";
        const intraday = ["1d", "5d"].includes(range);
        const labels = data.map(p => p.isOpeningPoint ? "Market Open" : new Date(p.t).toLocaleString("en-CA", intraday
          ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
          : { year: "numeric", month: "short", day: "numeric" }));
        const update = i => data[i] && setReadout({ price: money(data[i].close), date: labels[i] });
        update(data.length - 1);
        chart.current = new Chart(canvas.current, {
          type: "line",
          data: {
            labels,
            datasets: [{
              data: data.map(p => p.close), borderColor: color,
              backgroundColor: rising ? "rgba(24,130,99,.05)" : "rgba(196,84,84,.05)",
              borderWidth: 2, pointRadius: 0, pointHoverRadius: 0, tension: .12, fill: true,
            }],
          },
          plugins: [chartGuide],
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            interaction: { mode: "index", intersect: false },
            onHover: (event, items, c) => {
              const index = items[0]?.index;
              if (index == null) return;
              if (c.$hoverIndex !== index) { c.$hoverIndex = index; update(index); c.draw(); }
            },
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: {
              x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0, color: "#8b9294" } },
              y: { position: "right", grid: { color: "#eae8e3" }, ticks: { maxTicksLimit: 5, color: "#8b9294" } },
            },
          },
        });
        canvas.current.onmouseleave = () => {
          if (!chart.current) return;
          chart.current.$hoverIndex = null;
          update(data.length - 1);
          chart.current.draw();
        };
        setStatus("");
      } catch (err) {
        if (!cancelled) setStatus("Chart unavailable: " + err.message);
      }
    })();
    return () => { cancelled = true; };
  }, [ticker, range, currency]);

  useEffect(() => () => { if (chart.current) chart.current.destroy(); }, []);

  return (
    <div className="chart-section">
      <div className="periods">
        {PERIODS.map(([value, label]) => (
          <button key={value} className={range === value ? "active" : ""} onClick={() => setRange(value)}>{label}</button>
        ))}
      </div>
      <div className="chart-readout">
        <strong>{readout.price}</strong>
        <span>{readout.date}</span>
      </div>
      <div className="chart-area"><canvas ref={canvas} /></div>
      <div className="chart-status">{status}</div>
    </div>
  );
}
