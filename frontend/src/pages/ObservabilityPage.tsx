import React, { useMemo, useState } from "react";
import { Activity, Clock, DollarSign, Coins, CheckCircle2, RefreshCw, Pause, Play, ChevronDown } from "lucide-react";
import { ObservabilitySidebar } from "../components/observability/ObservabilitySidebar";
import { StatCard } from "../components/observability/StatCard";
import { DonutChart } from "../components/observability/DonutChart";
import { TrendsChart } from "../components/observability/TrendsChart";
import { QueryTable } from "../components/observability/QueryTable";
import { useLiveMetrics } from "../hooks/useLiveMetrics";
import { bucketLatency } from "../utils/bucketQueries";
import { routeColorHex } from "../utils/routeColors";

const POLL_MS = 5000;
const WINDOW_OPTIONS = [
  { label: "Last 15m", value: 15 },
  { label: "Last 1h", value: 60 },
  { label: "Last 4h", value: 240 },
  { label: "Last 24h", value: 1440 },
];

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

export default function ObservabilityPage() {
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [routeFilter, setRouteFilter] = useState<string>("all");
  const { data, error, loading, paused, setPaused, refresh } = useLiveMetrics(POLL_MS, windowMinutes);

  const filteredQueries = useMemo(() => {
    if (!data) return [];
    return routeFilter === "all" ? data.recent_queries : data.recent_queries.filter((q) => q.route === routeFilter);
  }, [data, routeFilter]);

  const trendBuckets = useMemo(() => bucketLatency(filteredQueries, 12), [filteredQueries]);

  const topSlow = useMemo(
    () => [...filteredQueries].filter((q) => q.latency_ms != null).sort((a, b) => (b.latency_ms ?? 0) - (a.latency_ms ?? 0)).slice(0, 6),
    [filteredQueries]
  );
  const recentTraces = useMemo(() => filteredQueries.slice(0, 8), [filteredQueries]);

  const routeSlices = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.queries.by_route).map(([route, count]) => ({
      key: route,
      label: route,
      value: count,
      color: routeColorHex(route),
    }));
  }, [data]);

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 overflow-hidden">
      <ObservabilitySidebar />

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Overview</h1>
            {data && <p className="text-xs text-gray-400 mt-0.5">last query {relativeTime(data.queries.latest_ts)}</p>}
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <select
                value={windowMinutes}
                onChange={(e) => setWindowMinutes(Number(e.target.value))}
                className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none"
              >
                {WINDOW_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
            </div>
            <div className="relative">
              <select
                value={routeFilter}
                onChange={(e) => setRouteFilter(e.target.value)}
                className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none capitalize"
              >
                <option value="all">All routes</option>
                {data && Object.keys(data.queries.by_route).map((r) => (
                  <option key={r} value={r} className="capitalize">{r}</option>
                ))}
              </select>
              <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
            </div>
            <button
              onClick={() => setPaused((p) => !p)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 hover:border-gray-300 transition-colors"
              title={paused ? "Resume auto-refresh" : "Pause auto-refresh"}
            >
              {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
              {paused ? "Paused" : "Live"}
            </button>
            <button
              onClick={refresh}
              className="p-2 border border-gray-200 rounded-lg bg-white text-gray-500 hover:border-gray-300 transition-colors"
              title="Refresh now"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          {loading && !data && (
            <div className="flex flex-col items-center justify-center py-24 text-gray-400">
              <Activity size={20} className="animate-pulse mb-2" />
              <span className="text-sm">Loading live metrics…</span>
            </div>
          )}

          {error && !data && (
            <div className="flex flex-col items-center py-24 gap-2 text-center text-gray-500 text-sm">{error}</div>
          )}

          {data && (
            <div className="space-y-4 max-w-[1400px]">
              <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
                <StatCard
                  icon={Activity}
                  iconColor="text-blue-600"
                  iconBg="bg-blue-50"
                  label="Total requests"
                  value={data.queries.total.toLocaleString()}
                  sub={`${data.queries.recent} in last ${data.queries.window_minutes}m`}
                />
                <StatCard
                  icon={Clock}
                  iconColor="text-violet-600"
                  iconBg="bg-violet-50"
                  label="Avg latency (P95)"
                  value={`${(data.latency_ms.p95 / 1000).toFixed(2)}s`}
                  sub={`avg ${(data.latency_ms.avg / 1000).toFixed(2)}s`}
                />
                <StatCard
                  icon={DollarSign}
                  iconColor="text-amber-600"
                  iconBg="bg-amber-50"
                  label="Total cost"
                  value={data.cost ? `$${data.cost.total_cost_usd.toFixed(4)}` : "—"}
                  sub={data.cost ? `${data.cost.total_tokens.toLocaleString()} tokens` : "not tracked"}
                />
                <StatCard
                  icon={Coins}
                  iconColor="text-teal-600"
                  iconBg="bg-teal-50"
                  label="Cost / request"
                  value={data.cost && data.queries.total > 0 ? `$${(data.cost.total_cost_usd / data.queries.total).toFixed(5)}` : "—"}
                  sub={data.cost ? `${data.cost.calls.toLocaleString()} LLM calls` : undefined}
                />
                <StatCard
                  icon={CheckCircle2}
                  iconColor="text-green-600"
                  iconBg="bg-green-50"
                  label="Success rate"
                  value={data.queries.success_rate !== null ? `${data.queries.success_rate}%` : "—"}
                  sub={`${data.queries.error_count} failed of ${data.queries.total}`}
                />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <div className="lg:col-span-2 rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-2">Latency trend</p>
                  <TrendsChart buckets={trendBuckets} />
                </div>
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-3">Requests by route</p>
                  <DonutChart slices={routeSlices} centerLabel="Total" centerValue={data.queries.total.toLocaleString()} />
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <QueryTable title="Top slow queries" rows={topSlow} emptyText="No queries logged yet." />
                </div>
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <QueryTable title="Recent traces" rows={recentTraces} emptyText="No queries logged yet." />
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
