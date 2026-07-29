import React from "react";

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  color: string; // hex
}

interface DonutChartProps {
  slices: DonutSlice[];
  centerLabel: string;
  centerValue: string;
}

const SIZE = 160;
const STROKE = 22;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const GAP_DEG = 2.5; // surface gap between segments, in degrees

export function DonutChart({ slices, centerLabel, centerValue }: DonutChartProps) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const nonZero = slices.filter((s) => s.value > 0);

  let cursorDeg = -90; // start at 12 o'clock

  return (
    <div className="flex items-center gap-4">
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="shrink-0">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="#f3f4f6" strokeWidth={STROKE} />
        {total > 0 &&
          nonZero.map((s) => {
            const fraction = s.value / total;
            const arcDeg = Math.max(0, fraction * 360 - GAP_DEG);
            const dashLength = (arcDeg / 360) * CIRCUMFERENCE;
            const rotate = cursorDeg;
            cursorDeg += fraction * 360;
            return (
              <circle
                key={s.key}
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke={s.color}
                strokeWidth={STROKE}
                strokeDasharray={`${dashLength} ${CIRCUMFERENCE - dashLength}`}
                strokeLinecap="round"
                transform={`rotate(${rotate} ${SIZE / 2} ${SIZE / 2})`}
              >
                <title>{`${s.label} · ${s.value.toLocaleString()} (${Math.round(fraction * 100)}%)`}</title>
              </circle>
            );
          })}
        <text x={SIZE / 2} y={SIZE / 2 - 6} textAnchor="middle" className="fill-gray-800" style={{ fontSize: 22, fontWeight: 600 }}>
          {centerValue}
        </text>
        <text x={SIZE / 2} y={SIZE / 2 + 14} textAnchor="middle" className="fill-gray-400" style={{ fontSize: 11 }}>
          {centerLabel}
        </text>
      </svg>

      {total === 0 ? (
        <p className="text-xs text-gray-400">No data yet.</p>
      ) : (
        <div className="space-y-1.5 min-w-0">
          {slices.map((s) => (
            <div key={s.key} className="flex items-center gap-2 text-xs">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
              <span className="text-gray-600 capitalize truncate">{s.label}</span>
              <span className="text-gray-400 tabular-nums whitespace-nowrap">
                {s.value.toLocaleString()} ({total > 0 ? Math.round((s.value / total) * 100) : 0}%)
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
