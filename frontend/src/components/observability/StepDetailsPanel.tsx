import React from "react";
import { Copy } from "lucide-react";
import type { TraceSpan, StageStat } from "../../services/traceService";
import { stepColorHex } from "../../utils/stepColors";

interface StepDetailsPanelProps {
  span: TraceSpan | null;
  stageStats: StageStat[];
  sqlQuery: string | null;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function StatTile({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={`rounded-lg border px-2.5 py-2 ${highlight ? "border-blue-200 bg-blue-50" : "border-gray-100 bg-gray-50"}`}>
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className="text-sm font-semibold text-gray-800 tabular-nums mt-0.5">{value}</p>
    </div>
  );
}

export function StepDetailsPanel({ span, stageStats, sqlQuery }: StepDetailsPanelProps) {
  if (!span) {
    return (
      <div className="w-72 shrink-0 border-l border-gray-200 bg-white p-4">
        <p className="text-sm text-gray-400">Select a step in the graph to see its details.</p>
      </div>
    );
  }

  const color = stepColorHex(span.step);
  const stats = stageStats.find((s) => s.step === span.step);
  const showSql = sqlQuery && (span.step === "executing" || span.step === "generating");

  return (
    <div className="w-72 shrink-0 border-l border-gray-200 bg-white p-4 overflow-y-auto">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
        <p className="text-sm font-semibold text-gray-800">{span.label}</p>
      </div>
      <p className="text-xs text-gray-400 mb-4">
        {formatMs(span.duration_ms)} · starts at {formatMs(span.start_ms)}
      </p>

      {stats && (
        <div className="mb-4">
          <p className="text-xs font-medium text-gray-600 mb-2">Historical latency ({stats.count} runs)</p>
          <div className="grid grid-cols-3 gap-1.5">
            <StatTile label="P50" value={formatMs(stats.p50)} />
            <StatTile label="P95" value={formatMs(stats.p95)} highlight />
            <StatTile label="P99" value={formatMs(stats.p99)} />
          </div>
        </div>
      )}

      {showSql && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-xs font-medium text-gray-600">SQL query</p>
            <button
              onClick={() => navigator.clipboard.writeText(sqlQuery!)}
              className="text-gray-400 hover:text-gray-600"
              title="Copy"
            >
              <Copy className="w-3 h-3" />
            </button>
          </div>
          <pre className="text-[11px] text-gray-700 bg-gray-50 border border-gray-100 rounded-lg p-2.5 overflow-x-auto whitespace-pre-wrap break-words">
            {sqlQuery}
          </pre>
        </div>
      )}
    </div>
  );
}
