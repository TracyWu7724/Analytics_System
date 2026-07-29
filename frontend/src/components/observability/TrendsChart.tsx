import React from "react";
import type { LatencyBucket } from "../../utils/bucketQueries";

interface TrendsChartProps {
  buckets: LatencyBucket[];
}

const WIDTH = 640;
const HEIGHT = 200;
const PAD_L = 40;
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 24;

const P50_COLOR = "#3b82f6"; // blue-500
const P95_COLOR = "#f97316"; // orange-500

function buildPath(values: number[], max: number, plotW: number, plotH: number): string {
  if (values.length === 0) return "";
  const stepX = values.length > 1 ? plotW / (values.length - 1) : 0;
  return values
    .map((v, i) => {
      const x = PAD_L + i * stepX;
      const y = PAD_T + plotH - (max > 0 ? (v / max) * plotH : 0);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function TrendsChart({ buckets }: TrendsChartProps) {
  if (buckets.length === 0) {
    return <p className="text-xs text-gray-400 py-8 text-center">Not enough query volume yet to chart a trend.</p>;
  }

  const plotW = WIDTH - PAD_L - PAD_R;
  const plotH = HEIGHT - PAD_T - PAD_B;
  const maxLatency = Math.max(1, ...buckets.map((b) => b.p95));
  const yTicks = [0, 0.5, 1].map((f) => Math.round(maxLatency * f));

  const p50Path = buildPath(buckets.map((b) => b.p50), maxLatency, plotW, plotH);
  const p95Path = buildPath(buckets.map((b) => b.p95), maxLatency, plotW, plotH);

  const lastP50 = buckets[buckets.length - 1].p50;
  const lastP95 = buckets[buckets.length - 1].p95;

  return (
    <div>
      <div className="flex items-center gap-4 mb-1 text-xs text-gray-500">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded-full shrink-0" style={{ backgroundColor: P50_COLOR }} />
          P50
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 rounded-full shrink-0" style={{ backgroundColor: P95_COLOR }} />
          P95
        </span>
      </div>
      <svg width="100%" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="xMidYMid meet">
        {yTicks.map((t, i) => {
          const y = PAD_T + plotH - (maxLatency > 0 ? (t / maxLatency) * plotH : 0);
          return (
            <g key={i}>
              <line x1={PAD_L} y1={y} x2={WIDTH - PAD_R} y2={y} stroke="#e5e7eb" strokeWidth={1} />
              <text x={PAD_L - 6} y={y + 3} textAnchor="end" className="fill-gray-400" style={{ fontSize: 10 }}>
                {t.toLocaleString()}
              </text>
            </g>
          );
        })}

        <path d={p95Path} fill="none" stroke={P95_COLOR} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        <path d={p50Path} fill="none" stroke={P50_COLOR} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {buckets.map((b, i) => {
          const stepX = buckets.length > 1 ? plotW / (buckets.length - 1) : 0;
          const x = PAD_L + i * stepX;
          return (
            <g key={i}>
              <circle cx={x} cy={PAD_T + plotH - (b.p50 / maxLatency) * plotH} r={2.5} fill={P50_COLOR} stroke="#fff" strokeWidth={1.5}>
                <title>{`${b.label} · P50 ${b.p50.toLocaleString()}ms (${b.count} queries)`}</title>
              </circle>
              <circle cx={x} cy={PAD_T + plotH - (b.p95 / maxLatency) * plotH} r={2.5} fill={P95_COLOR} stroke="#fff" strokeWidth={1.5}>
                <title>{`${b.label} · P95 ${b.p95.toLocaleString()}ms (${b.count} queries)`}</title>
              </circle>
            </g>
          );
        })}

        <text x={WIDTH - PAD_R} y={PAD_T + plotH - (lastP50 / maxLatency) * plotH - 6} textAnchor="end" className="fill-gray-600" style={{ fontSize: 10, fontWeight: 600 }}>
          {lastP50.toLocaleString()}ms
        </text>
        <text x={WIDTH - PAD_R} y={PAD_T + plotH - (lastP95 / maxLatency) * plotH - 6} textAnchor="end" className="fill-gray-600" style={{ fontSize: 10, fontWeight: 600 }}>
          {lastP95.toLocaleString()}ms
        </text>

        <text x={PAD_L} y={HEIGHT - 4} textAnchor="start" className="fill-gray-400" style={{ fontSize: 10 }}>
          {buckets[0].label}
        </text>
        <text x={WIDTH - PAD_R} y={HEIGHT - 4} textAnchor="end" className="fill-gray-400" style={{ fontSize: 10 }}>
          {buckets[buckets.length - 1].label}
        </text>
      </svg>
    </div>
  );
}
