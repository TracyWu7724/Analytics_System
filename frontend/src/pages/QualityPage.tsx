import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, ShieldCheck, ThumbsUp, RefreshCw, Pause, Play, ExternalLink } from "lucide-react";
import { ObservabilitySidebar } from "../components/observability/ObservabilitySidebar";
import { StatCard } from "../components/observability/StatCard";
import { getQualityStats, type QualityStats } from "../services/qualityService";
import { routeColorTw } from "../utils/routeColors";

const POLL_MS = 10000;

export default function QualityPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<QualityStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);

  const fetchStats = useCallback(async () => {
    const result = await getQualityStats();
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

  const faithfulness = stats?.faithfulness ?? null;

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 overflow-hidden">
      <ObservabilitySidebar />

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Quality</h1>
            <p className="text-xs text-gray-400 mt-0.5">Track answer quality and understand failures.</p>
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
              <CheckCircle2 size={20} className="animate-pulse mb-2" />
              <span className="text-sm">Loading quality stats…</span>
            </div>
          )}
          {error && !stats && <div className="text-sm text-gray-500 py-24 text-center">{error}</div>}

          {stats && (
            <div className="space-y-4 max-w-[1400px]">
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                <StatCard
                  icon={CheckCircle2}
                  iconColor="text-green-600"
                  iconBg="bg-green-50"
                  label="Overall quality (pass rate)"
                  value={stats.overall.pass_rate !== null ? `${stats.overall.pass_rate}%` : "—"}
                  sub={`${stats.overall.evaluated - stats.overall.error_count} / ${stats.overall.evaluated} passed`}
                />
                <StatCard
                  icon={ShieldCheck}
                  iconColor="text-blue-600"
                  iconBg="bg-blue-50"
                  label="RAG faithfulness"
                  value={faithfulness?.avg != null ? `${Math.round(faithfulness.avg * 100)}%` : "—"}
                  sub={faithfulness && faithfulness.count > 0 ? `Evaluated ${faithfulness.count} RAG queries` : "No RAG queries scored yet"}
                />
                <StatCard
                  icon={ThumbsUp}
                  iconColor="text-violet-600"
                  iconBg="bg-violet-50"
                  label="Human acceptance"
                  value={stats.human_acceptance.acceptance_rate !== null ? `${stats.human_acceptance.acceptance_rate}%` : "—"}
                  sub={`${stats.human_acceptance.rated} rated · ${stats.human_acceptance.good} up · ${stats.human_acceptance.bad} down`}
                />
              </div>

              <p className="text-xs text-gray-400">
                Correctness, Groundedness, and Completeness need a reference answer and only run through the offline eval
                driver (<code className="bg-gray-100 px-1 rounded">python -m scripts.run_eval</code>) — not shown here until a run exists.
              </p>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                {/* By route */}
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-3">Quality by route (pass rate)</p>
                  {stats.by_route.length === 0 ? (
                    <p className="text-xs text-gray-400">No queries logged yet.</p>
                  ) : (
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-gray-400 text-left">
                          <th className="font-normal pb-2">Route</th>
                          <th className="font-normal pb-2 text-right">Requests</th>
                          <th className="font-normal pb-2 text-right">% total</th>
                          <th className="font-normal pb-2 text-right">Pass rate</th>
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
                            <td className="py-2 text-right text-gray-800 font-medium tabular-nums">
                              {r.pass_rate !== null ? `${r.pass_rate}%` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>

                {/* Faithfulness distribution */}
                <div className="rounded-xl border border-gray-200 bg-white p-4">
                  <p className="text-sm font-medium text-gray-700 mb-0.5">RAG faithfulness distribution</p>
                  <p className="text-xs text-gray-400 mb-3">Fraction of each answer grounded in retrieved chunks.</p>
                  {!faithfulness || faithfulness.count === 0 ? (
                    <p className="text-xs text-gray-400">No RAG queries scored yet.</p>
                  ) : (
                    <>
                      <div className="grid grid-cols-3 gap-2 mb-3">
                        {(["avg", "p50", "p95"] as const).map((k) => (
                          <div key={k} className="rounded-lg border border-gray-100 bg-gray-50 px-2.5 py-2">
                            <p className="text-[11px] text-gray-500 uppercase">{k}</p>
                            <p className="text-sm font-semibold text-gray-800 tabular-nums mt-0.5">
                              {Math.round((faithfulness[k] ?? 0) * 100)}%
                            </p>
                          </div>
                        ))}
                      </div>
                      <div className="flex items-end gap-0.5 h-10">
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

              {/* Worst faithfulness */}
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <p className="text-sm font-medium text-gray-700 mb-3">Lowest-scoring RAG answers</p>
                {stats.worst_faithfulness.length === 0 ? (
                  <p className="text-xs text-gray-400">No RAG queries scored yet.</p>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-gray-400 text-left">
                        <th className="font-normal pb-2 w-6">#</th>
                        <th className="font-normal pb-2">Query</th>
                        <th className="font-normal pb-2">Faithfulness</th>
                        <th className="font-normal pb-2 w-6"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {stats.worst_faithfulness.map((w, i) => (
                        <tr key={i} className="border-t border-gray-50">
                          <td className="py-2 text-gray-300">{i + 1}</td>
                          <td className="py-2 text-gray-700 max-w-[420px] truncate" title={w.question ?? undefined}>{w.question}</td>
                          <td className="py-2">
                            <div className="flex items-center gap-2">
                              <div className="w-32 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                                <div
                                  className={`h-full rounded-full ${w.faithfulness >= 0.7 ? "bg-green-500" : w.faithfulness >= 0.4 ? "bg-amber-500" : "bg-red-500"}`}
                                  style={{ width: `${w.faithfulness * 100}%` }}
                                />
                              </div>
                              <span className="text-gray-600 tabular-nums">{w.faithfulness.toFixed(2)}</span>
                            </div>
                          </td>
                          <td className="py-2 text-right">
                            {w.trace_id && (
                              <button onClick={() => navigate(`/traces?trace=${w.trace_id}`)} className="text-gray-400 hover:text-gray-600">
                                <ExternalLink className="w-3.5 h-3.5" />
                              </button>
                            )}
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
