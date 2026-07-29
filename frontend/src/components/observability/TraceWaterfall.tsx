import React from "react";
import type { TraceDetail } from "../../services/traceService";
import { stepColorHex } from "../../utils/stepColors";

interface TraceWaterfallProps {
  trace: TraceDetail;
}

const RULER_TICKS = [0, 0.25, 0.5, 0.75, 1];

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

export function TraceWaterfall({ trace }: TraceWaterfallProps) {
  const total = Math.max(1, trace.total_ms);

  return (
    <div>
      {/* Ruler */}
      <div className="relative h-5 mb-2 ml-[168px] border-b border-gray-100">
        {RULER_TICKS.map((f) => (
          <div
            key={f}
            className="absolute top-0 bottom-0 border-l border-gray-100 text-[10px] text-gray-400 pl-1"
            style={{ left: `${f * 100}%` }}
          >
            {formatMs(total * f)}
          </div>
        ))}
      </div>

      {/* Spans */}
      <div className="space-y-1.5">
        {trace.spans.map((s, i) => {
          const leftPct = (s.start_ms / total) * 100;
          const widthPct = Math.max(0.6, (s.duration_ms / total) * 100);
          const color = stepColorHex(s.step);
          return (
            <div key={i} className="flex items-center gap-2">
              <span className="w-40 shrink-0 text-xs text-gray-600 truncate" title={s.label}>
                {s.label}
              </span>
              <div className="relative flex-1 h-5 bg-gray-50 rounded">
                <div
                  className="absolute top-0.5 bottom-0.5 rounded-full"
                  style={{ left: `${leftPct}%`, width: `${widthPct}%`, backgroundColor: color }}
                  title={`${s.label} · ${formatMs(s.duration_ms)} (starts at ${formatMs(s.start_ms)})`}
                />
              </div>
              <span className="w-14 shrink-0 text-right text-xs text-gray-400 tabular-nums">
                {formatMs(s.duration_ms)}
              </span>
            </div>
          );
        })}
      </div>

      {trace.spans.length === 0 && (
        <p className="text-xs text-gray-400 py-4">No spans recorded for this trace.</p>
      )}
    </div>
  );
}
