// Semicircle gauge with red / yellow / green zones and a needle.
// zones: [{from, to, tone}] on a 0-100 scale; score: 0-100 or null (no needle).

const TONE = { red: "#c45454", yellow: "#d6a93a", green: "#188263" };
const CX = 150, CY = 150, R = 112, W = 26;

function point(value, radius) {
  const angle = Math.PI * (1 - value / 100);           // 0 -> left, 100 -> right
  return [CX + radius * Math.cos(angle), CY - radius * Math.sin(angle)];
}

function arc(from, to) {
  const [x1, y1] = point(from, R);
  const [x2, y2] = point(to, R);
  return `M ${x1} ${y1} A ${R} ${R} 0 0 1 ${x2} ${y2}`;
}

export default function Gauge({ score, zones, label }) {
  const has = typeof score === "number" && Number.isFinite(score);
  const value = has ? Math.max(0, Math.min(100, score)) : 0;
  const rotation = -90 + value * 1.8;                   // needle drawn pointing up, rotated around the hub
  const gap = 0.7;
  return (
    <svg className="gauge" viewBox="0 0 300 172" role="img"
         aria-label={has ? `${label}: ${Math.round(value)} out of 100` : `${label}: not available`}>
      <path d={arc(0, 100)} stroke="#eeece7" strokeWidth={W} fill="none" />
      {zones.map(z => (
        <path key={z.from} d={arc(z.from + (z.from ? gap : 0), z.to - (z.to < 100 ? gap : 0))}
              stroke={TONE[z.tone]} strokeOpacity={has ? 0.9 : 0.25} strokeWidth={W} fill="none" />
      ))}
      {[0, 50, 100].map(t => {
        const [x, y] = point(t, R - W / 2 - 14);
        return <text key={t} x={x} y={y + 4} fontSize="11" fill="#9a9da0" textAnchor="middle">{t}</text>;
      })}
      {has && (
        <g className="needle" style={{ transform: `rotate(${rotation}deg)`, transformOrigin: `${CX}px ${CY}px` }}>
          <path d={`M ${CX - 5} ${CY} L ${CX} ${CY - R + 6} L ${CX + 5} ${CY} Z`} fill="#172025" />
        </g>
      )}
      <circle cx={CX} cy={CY} r="11" fill="#172025" />
      <circle cx={CX} cy={CY} r="4" fill="#c5ad83" />
    </svg>
  );
}

export function GaugeLegend({ zones, names }) {
  return (
    <div className="gauge-legend">
      {zones.map((z, i) => (
        <span key={z.from}><i style={{ background: TONE[z.tone] }} />{names[i]} ({z.from}–{z.to})</span>
      ))}
    </div>
  );
}
