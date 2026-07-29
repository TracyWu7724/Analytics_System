import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Clock, Gauge, Timer, ShieldCheck, RefreshCw, Pause, Play, ExternalLink, CheckCircle2, AlertTriangle } from "lucide-react";
import { ObservabilitySidebar } from "../components/observability/ObservabilitySidebar";
import { StatCard } from "../components/observability/StatCard";
import { getLatencyStats, type LatencyStats } from "../services/traceService";
import { routeColorTw } from "../utils/routeColors";
import { stepColorHex } from "../utils/stepColors";

const POLL_MS = 10000;
const SLO_THRESHOLD_MS = 2000;

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function relativeTime(unixSec: number): string {
  const diffMs = Date.now() - unixSec * 1000;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

export default function LatencyPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<LatencyStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);

  const fetchStats = useCallback(async () => {
    const result = await getLatencyStats(SLO_THRESHOLD_MS);
    if ("error" in result) {
      setError(result.error);
    } else {
      setError(null);
      setStats(result);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchStats();
    if (paused) return;
    const timer = setInterval(fetchStats, POLL_MS);
    return () => clearInterval(timer);
  }, [fetchStats, paused]);

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 overflow-hidden">
      <ObservabilitySidebar />

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Latency</h1>
            <p className="text-xs text-gray-400 mt-0.5">Track response times and identify performance bottlenecks across your system.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPaused((p) => !p)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 hover:border-gray-300 transition-colors"
            >
              {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
              {paused ? "Paused" : "Live"}
            </button>
            <button
              onClick={fetchStats}
              className="p-2 border border-gray-200 rounded-lg bg-white text-gray-500 hover:border-gray-300 transition-colors"
              title="Refresh now"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto p-6">
          {loading && !stats && (
            <div className="flex flex-col items-center justify-center py-24 text-gray-400">
              <Clock size={20} className="animate-pulse mb-2" />
              <span className="text-sm">Loading latency stats…</span>
            </div>
          )}
          {error && !stats && <div className="text-sm text-gray-500 py-24 text-center">{error}</div>}

          {stats && (
            <div className="space-y-4 max-w-[1400px]">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <StatCard icon={Gauge} iconColor="text-blue-600" iconBg="bg-blue-50" label="P50 latency" value={formatMs(stats.overall.p50)} sub={`avg ${formatMs(stats.overall.avg)}`} />
                <StatCard icon={Clock} iconColor="text-violet-600" iconBg="bg-violet-50" label="P95 latency" value={formatMs(stats.overall.p95)} />
                <StatCard icon={Timer} iconColor="text-amber-600" iconBg="bg-amber-50" label="P99 latency" value={formatMs(stats.overall.p99)} />
                <StatCard
                  icon={ShieldCheck}
                  iconColor="text-green-600"
                  iconBg="bg-green-50"
                  label={`SLO compliance (≤ ${formatMs(stats.overall.slo_threshold_ms)})`}
                  value={stats.overall.slo_compliance_pct !== null ? `${stats.overall.slo_compliance_pct}%` : "—"}
                />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* By route */}
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-3">Latency by route (P95)</p>
                  {stats.by_route.length === 0 ? (
                    <p className="text-xs text-gray-400">No queries logged yet.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-400 text-left">
                          <th className="font-normal pb-2">Route</th>
                          <th className="font-normal pb-2 text-right">Requests</th>
                          <th className="font-normal pb-2 text-right">% total</th>
                          <th className="font-normal pb-2 text-right">P50</th>
                          <th className="font-normal pb-2 text-right">P95</th>
                          <th className="font-normal pb-2 text-right">P99</th>
                          <th className="font-normal pb-2 text-right">SLO</th>
                        </tr>
                      </thead>
                      <tbody>
                        {stats.by_route.map((r) => (
                          <tr key={r.route} className="border-t border-gray-50">
                            <td className="py-2">
                              <span className={`px-1.5 py-0.5 rounded text-white text-[10px] capitalize ${routeColorTw(r.route)}`}>{r.route}</span>
                            </td>
                            <td className="py-2 text-right text-gray-600 tabular-nums">{r.count}</td>
                            <td className="py-2 text-right text-gray-400 tabular-nums">{r.pct_of_total}%</td>
                            <td className="py-2 text-right text-gray-600 tabular-nums">{formatMs(r.p50)}</td>
                            <td className="py-2 text-right text-gray-800 font-medium tabular-nums">{formatMs(r.p95)}</td>
                            <td className="py-2 text-right text-gray-600 tabular-nums">{formatMs(r.p99)}</td>
                            <td className="py-2 text-right">
                              {r.p95 <= SLO_THRESHOLD_MS ? (
                                <CheckCircle2 className="w-3.5 h-3.5 text-green-500 inline" />
                              ) : (
                                <AlertTriangle className="w-3.5 h-3.5 text-amber-500 inline" />
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* By stage */}
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-3">Latency by pipeline stage (P95)</p>
                  {stats.by_stage.length === 0 ? (
                    <p className="text-xs text-gray-400">No traces recorded yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {stats.by_stage.map((s) => (
                        <div key={s.step} className="flex items-center gap-2 text-xs">
                          <span className="w-28 shrink-0 text-gray-600 truncate" title={s.label}>{s.label.replace(/\.\.\.$/, "")}</span>
                          <div className="flex-1 h-2 rounded-full bg-gray-50 overflow-hidden">
                            <div
                              className="h-full rounded-full"
                              style={{ width: `${s.pct_of_p95}%`, backgroundColor: stepColorHex(s.step) }}
                              title={`P50 ${formatMs(s.p50)} · P95 ${formatMs(s.p95)} · P99 ${formatMs(s.p99)} (${s.count} runs)`}
                            />
                          </div>
                          <span className="w-14 shrink-0 text-right text-gray-500 tabular-nums">{formatMs(s.p95)}</span>
                          <span className="w-10 shrink-0 text-right text-gray-400 tabular-nums">{s.pct_of_p95}%</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Slowest traces */}
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-sm font-medium text-gray-700 mb-3">Slowest traces (by bottleneck stage)</p>
                {stats.slowest_traces.length === 0 ? (
                  <p className="text-xs text-gray-400">No traces recorded yet.</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-400 text-left">
                        <th className="font-normal pb-2 w-6">#</th>
                        <th className="font-normal pb-2">Query</th>
                        <th className="font-normal pb-2">Route</th>
                        <th className="font-normal pb-2">Bottleneck stage</th>
                        <th className="font-normal pb-2 text-right">Bottleneck</th>
                        <th className="font-normal pb-2 text-right">Total latency</th>
                        <th className="font-normal pb-2 text-right">Started</th>
                        <th className="font-normal pb-2 w-6"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.slowest_traces.map((t, i) => (
                        <tr key={t.trace_id} className="border-t border-gray-50">
                          <td className="py-2 text-gray-300">{i + 1}</td>
                          <td className="py-2 text-gray-700 max-w-[260px] truncate" title={t.question ?? undefined}>{t.question}</td>
                          <td className="py-2">
                            {t.route && (
                              <span className={`px-1.5 py-0.5 rounded text-white text-[10px] capitalize ${routeColorTw(t.route)}`}>{t.route}</span>
                            )}
                          </td>
                          <td className="py-2 text-gray-600">{t.bottleneck_label.replace(/\.\.\.$/, "")}</td>
                          <td className="py-2 text-right text-gray-800 font-medium tabular-nums">{formatMs(t.bottleneck_ms)}</td>
                          <td className="py-2 text-right text-gray-500 tabular-nums">{t.total_ms != null ? formatMs(t.total_ms) : "—"}</td>
                          <td className="py-2 text-right text-gray-400 tabular-nums">{relativeTime(t.start_ts)}</td>
                          <td className="py-2 text-right">
                            <button onClick={() => navigate(`/traces?trace=${t.trace_id}`)} className="text-gray-400 hover:text-gray-600">
                              <ExternalLink className="w-3.5 h-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
