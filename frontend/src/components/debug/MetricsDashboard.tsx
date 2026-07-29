import { Activity } from "lucide-react";
import { useLiveMetrics } from "../../hooks/useLiveMetrics";

const POLL_MS = 5000;

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
  const { data, error, loading } = useLiveMetrics(POLL_MS);

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

  const { queries, latency_ms, feedback, cost } = data;

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
    </div>
  );
}
