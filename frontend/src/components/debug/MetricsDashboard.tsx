import React, { useEffect, useRef, useState } from "react";
import { Activity } from "lucide-react";
import { getLiveMetrics, type LiveMetrics } from "../../services/metricsService";

const POLL_MS = 5000;

// Fixed categorical order — never reassigned by rank, so a route keeps its
// color as other routes come and go.
const ROUTE_COLORS: Record<string, string> = {
  sql: "bg-blue-500",
  rag: "bg-violet-500",
  both: "bg-teal-500",
  schema: "bg-amber-500",
  unknown: "bg-gray-400",
};

function routeColor(route: string): string {
  return ROUTE_COLORS[route] ?? "bg-gray-400";
}

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  return `${Math.round(diffMin / 60)}h ago`;
}

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-lg font-semibold text-gray-800 tabular-nums leading-tight mt-0.5">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export function MetricsDashboard() {
  const [data, setData] = useState<LiveMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchMetrics = async () => {
      const result = await getLiveMetrics();
      if (cancelled) return;
      if ("error" in result) {
        setError(result.error);
      } else {
        setError(null);
        setData(result);
      }
      setLoading(false);
    };

    fetchMetrics();
    timerRef.current = setInterval(fetchMetrics, POLL_MS);

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
        <Activity size={20} className="animate-pulse mb-2" />
        <span className="text-sm">Loading live metrics…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center py-10 gap-2 text-center">
        <p className="text-sm text-gray-600">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const { queries, latency_ms, feedback, cost, rag } = data;
  const routeEntries = Object.entries(queries.by_route).sort((a, b) => b[1] - a[1]);
  const maxRouteCount = Math.max(1, ...routeEntries.map(([, c]) => c));
  const faithfulness = rag?.faithfulness ?? null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-1.5">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
          </span>
          <span className="text-xs font-medium text-gray-500">Live · updates every {POLL_MS / 1000}s</span>
        </div>
        <span className="text-xs text-gray-400">last query {relativeTime(queries.latest_ts)}</span>
      </div>

      <div className="grid grid-cols-2 gap-2 mb-4">
        <StatTile
          label="Total queries"
          value={queries.total.toLocaleString()}
          sub={`${queries.recent} in last ${queries.window_minutes}m`}
        />
        <StatTile
          label="Avg latency"
          value={`${latency_ms.avg.toLocaleString()} ms`}
          sub={`p95 ${latency_ms.p95.toLocaleString()} ms`}
        />
        <StatTile
          label="Satisfaction"
          value={feedback.satisfaction_rate !== null ? `${feedback.satisfaction_rate}%` : "—"}
          sub={`${feedback.good} up · ${feedback.bad} down`}
        />
        <StatTile
          label="Est. cost"
          value={cost ? `$${cost.total_cost_usd.toFixed(4)}` : "—"}
          sub={cost ? `${cost.total_tokens.toLocaleString()} tokens` : "not tracked"}
        />
      </div>

      <div className="py-3 border-t">
        <p className="text-sm font-medium text-gray-700 mb-2">Queries by route</p>
        {routeEntries.length === 0 ? (
          <p className="text-xs text-gray-400">No queries logged yet.</p>
        ) : (
          <div className="space-y-1.5">
            {routeEntries.map(([route, count]) => (
              <div key={route} className="flex items-center gap-2">
                <span className="w-14 shrink-0 text-xs text-gray-500 capitalize">{route}</span>
                <div className="flex-1 h-2 rounded-full bg-gray-100 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${routeColor(route)}`}
                    style={{ width: `${(count / maxRouteCount) * 100}%` }}
                  />
                </div>
                <span className="w-6 shrink-0 text-xs text-gray-500 text-right tabular-nums">{count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="py-3 border-t">
        <p className="text-sm font-medium text-gray-700 mb-0.5">RAG faithfulness</p>
        <p className="text-xs text-gray-400 mb-2">
          Fraction of each answer grounded in retrieved chunks — scored live on every RAG query.
        </p>
        {!faithfulness || faithfulness.count === 0 ? (
          <p className="text-xs text-gray-400">No RAG queries scored yet.</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2 mb-2">
              <StatTile label="Avg" value={`${Math.round((faithfulness.avg ?? 0) * 100)}%`} />
              <StatTile label="P50" value={`${Math.round((faithfulness.p50 ?? 0) * 100)}%`} />
              <StatTile label="P95" value={`${Math.round((faithfulness.p95 ?? 0) * 100)}%`} />
            </div>
            <div className="flex items-end gap-0.5 h-8">
              {faithfulness.recent.map((v, i) => (
                <div
                  key={i}
                  className="flex-1 bg-blue-500 rounded-t-sm min-w-[2px]"
                  style={{ height: `${Math.max(4, v * 100)}%` }}
                  title={`${Math.round(v * 100)}%`}
                />
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-1">last {faithfulness.recent.length} scored queries</p>
          </>
        )}
      </div>
    </div>
  );
}
