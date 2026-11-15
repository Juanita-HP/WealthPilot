// Doughnut (plan allocations) and line chart (time machine), drawn with Chart.js like the stock chart.
import { useEffect, useRef } from "react";
import Chart from "chart.js/auto";
import { PALETTE, dollars, pct } from "../lib.js";

export function Donut({ holdings }) {
  const canvas = useRef(null);
  useEffect(() => {
    const chart = new Chart(canvas.current, {
      type: "doughnut",
      data: {
        labels: holdings.map(h => h.name),
        datasets: [{ data: holdings.map(h => h.weight), backgroundColor: holdings.map((_, i) => PALETTE[i % PALETTE.length]),
                     borderColor: "#fff", borderWidth: 2 }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: "68%",
        plugins: { legend: { display: false },
                   tooltip: { callbacks: { label: c => ` ${c.label}: ${pct(c.parsed, 1)}` } } },
      },
    });
    return () => chart.destroy();
  }, [holdings]);
  return <canvas ref={canvas} />;
}

// Shades the worst peak-to-trough period.
const band = {
  id: "band",
  beforeDatasetsDraw(c, _args, opts) {
    if (opts.from == null || opts.to == null) return;
    const x = c.scales.x;
    const { ctx, chartArea } = c;
    ctx.save();
    ctx.fillStyle = "rgba(196,84,84,.08)";
    const x1 = x.getPixelForValue(opts.from), x2 = x.getPixelForValue(opts.to);
    ctx.fillRect(x1, chartArea.top, x2 - x1, chartArea.bottom - chartArea.top);
    ctx.restore();
  },
};

export function ValueChart({ dates, value, valueReal, from, to }) {
  const canvas = useRef(null);
  useEffect(() => {
    const datasets = [{ label: "Value", data: value, borderColor: "#172025", borderWidth: 2, pointRadius: 0, tension: .1 }];
    if (valueReal) datasets.push({ label: "After inflation", data: valueReal, borderColor: "#c5ad83", borderWidth: 2,
                                   borderDash: [5, 4], pointRadius: 0, tension: .1 });
    const chart = new Chart(canvas.current, {
      type: "line",
      data: { labels: dates, datasets },
      plugins: [band],
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          band: { from, to },
          legend: { display: Boolean(valueReal), position: "bottom", labels: { boxWidth: 12, color: "#83898b" } },
          tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${dollars(c.parsed.y)}` } },
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 6, maxRotation: 0, color: "#8b9294" } },
          y: { position: "right", grid: { color: "#eae8e3" }, ticks: { maxTicksLimit: 5, color: "#8b9294", callback: v => dollars(v) } },
        },
      },
    });
    return () => chart.destroy();
  }, [dates, value, valueReal, from, to]);
  return <canvas ref={canvas} />;
}
