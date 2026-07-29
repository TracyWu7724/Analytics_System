import React from "react";
import type { LiveMetrics } from "../../services/metricsService";
import { routeColorTw } from "../../utils/routeColors";

type QueryRow = LiveMetrics["recent_queries"][number];

interface QueryTableProps {
  title: string;
  rows: QueryRow[];
  emptyText: string;
  showTime?: boolean;
}

function relativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

function truncate(text: string | null, max = 42): string {
  if (!text) return "—";
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function QueryTable({ title, rows, emptyText, showTime = true }: QueryTableProps) {
  return (
    <div>
      <p className="text-sm font-medium text-gray-700 mb-2">{title}</p>
      {rows.length === 0 ? (
        <p className="text-xs text-gray-400">{emptyText}</p>
      ) : (
        <div className="space-y-2">
          {rows.map((r, i) => (
            <div key={i} className="flex items-center gap-2 text-xs">
              <span className="w-4 shrink-0 text-gray-300 tabular-nums">{i + 1}</span>
              <span className="flex-1 min-w-0 text-gray-700 truncate" title={r.question ?? undefined}>
                {truncate(r.question)}
              </span>
              <span className={`shrink-0 px-1.5 py-0.5 rounded text-white text-[10px] capitalize ${routeColorTw(r.route)}`}>
                {r.route}
              </span>
              <span className="w-14 shrink-0 text-right text-gray-500 tabular-nums">
                {r.latency_ms != null ? `${(r.latency_ms / 1000).toFixed(2)}s` : "—"}
              </span>
              {showTime && (
                <span className="w-16 shrink-0 text-right text-gray-400 tabular-nums">{relativeTime(r.ts)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
