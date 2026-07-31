import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  GitBranch, RefreshCw, AlertCircle, Search, ChevronDown, ChevronLeft, ChevronRight,
  Copy, Pause, Play, CheckCircle2, Loader2,
} from "lucide-react";
import { ObservabilitySidebar } from "../components/observability/ObservabilitySidebar";
import { ErrorBoundary } from "../components/observability/ErrorBoundary";
import { TraceGraph } from "../components/observability/TraceGraph";
import { TraceWaterfall } from "../components/observability/TraceWaterfall";
import { StepDetailsPanel } from "../components/observability/StepDetailsPanel";
import {
  listTraces, getTrace, getLatencyStats,
  type TraceSummary, type TraceDetail, type StageStat,
} from "../services/traceService";
import { routeColorTw, ROUTE_ORDER } from "../utils/routeColors";

const POLL_MS = 5000;
const PAGE_SIZE = 8;

function relativeTime(unixSec: number): string {
  const diffMs = Date.now() - unixSec * 1000;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.round(diffHr / 24)}d ago`;
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

type DetailTab = "graph" | "timeline";

export default function TracesPage() {
  const [searchParams] = useSearchParams();
  const deepLinkedTraceId = searchParams.get("trace");

  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);

  const [search, setSearch] = useState("");
  const [routeFilter, setRouteFilter] = useState("all");
  const [page, setPage] = useState(0);

  const [selectedId, setSelectedId] = useState<string | null>(deepLinkedTraceId);
  const [detail, setDetail] = useState<TraceDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<DetailTab>("graph");
  const [selectedSpanIdx, setSelectedSpanIdx] = useState<number | null>(null);

  const [stageStats, setStageStats] = useState<StageStat[]>([]);

  const fetchTraces = useCallback(async () => {
    const result = await listTraces({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, route: routeFilter, q: search || undefined });
    if ("error" in result) {
      setError(result.error);
    } else {
      setError(null);
      setTraces(result.traces);
      setTotal(result.total);
      setSelectedId((prev) => prev ?? (result.traces.length > 0 ? result.traces[0].trace_id : null));
    }
    setLoading(false);
  }, [page, routeFilter, search]);

  useEffect(() => {
    fetchTraces();
    if (paused) return;
    const timer = setInterval(fetchTraces, POLL_MS);
    return () => clearInterval(timer);
  }, [fetchTraces, paused]);

  useEffect(() => {
    getLatencyStats().then((result) => {
      if (!("error" in result)) setStageStats(result.by_stage);
    });
  }, []);

  useEffect(() => {
    if (!selectedId) { setDetail(null); setDetailLoading(false); return; }
    let cancelled = false;
    setDetailLoading(true);
    getTrace(selectedId).then((result) => {
      if (cancelled) return;
      if ("trace_id" in result) {
        setDetailError(null);
        setDetail(result);
        setSelectedSpanIdx(null);
      } else {
        setDetailError(result.error);
        setDetail(null);
      }
      setDetailLoading(false);
    });
    return () => { cancelled = true; };
  }, [selectedId]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const selectedSpan = useMemo(
    () => (detail && selectedSpanIdx != null ? detail.spans[selectedSpanIdx] : null),
    [detail, selectedSpanIdx]
  );

  return (
    <div className="flex h-screen bg-gray-50 text-gray-900 overflow-hidden">
      <ObservabilitySidebar />

      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between shrink-0">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Traces</h1>
            <p className="text-xs text-gray-400 mt-0.5">Inspect end-to-end executions and drill down into each step.</p>
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
              onClick={fetchTraces}
              className="p-2 border border-gray-200 rounded-lg bg-white text-gray-500 hover:border-gray-300 transition-colors"
              title="Refresh now"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* Trace list */}
          <div className="w-96 shrink-0 border-r border-gray-200 bg-white overflow-y-auto flex flex-col">
            <div className="p-3 border-b border-gray-100 space-y-2 shrink-0">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(0); }}
                  placeholder="Search by question or trace ID..."
                  className="w-full pl-8 pr-2 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-gray-300"
                />
              </div>
              <div className="flex items-center justify-between">
                <div className="relative">
                  <select
                    value={routeFilter}
                    onChange={(e) => { setRouteFilter(e.target.value); setPage(0); }}
                    className="appearance-none pl-2.5 pr-7 py-1 text-xs border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer capitalize"
                  >
                    <option value="all">All routes</option>
                    {ROUTE_ORDER.filter((r) => r !== "unknown").map((r) => (
                      <option key={r} value={r} className="capitalize">{r}</option>
                    ))}
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 -translate-y-1/2 w-3 h-3 text-gray-500" />
                </div>
                <span className="text-xs text-gray-400">{total} traces</span>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {loading && (
                <div className="flex flex-col items-center justify-center py-16 text-gray-400">
                  <GitBranch size={18} className="animate-pulse mb-2" />
                  <span className="text-sm">Loading traces…</span>
                </div>
              )}
              {error && !loading && <div className="p-4 text-sm text-gray-500">{error}</div>}
              {!loading && !error && traces.length === 0 && (
                <div className="p-4 text-sm text-gray-400">No traces recorded yet. Ask the agent a question to generate one.</div>
              )}
              <div className="divide-y divide-gray-100">
                {traces.map((t) => (
                  <button
                    key={t.trace_id}
                    onClick={() => setSelectedId(t.trace_id)}
                    className={`w-full text-left px-4 py-3 transition-colors ${
                      selectedId === t.trace_id ? "bg-blue-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-[11px] text-gray-400 font-mono">tr_{t.trace_id.slice(0, 8)}</span>
                      {t.error ? (
                        <AlertCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                      ) : !t.complete ? (
                        <Loader2 className="w-3.5 h-3.5 text-amber-500 shrink-0 animate-spin" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500 shrink-0" />
                      )}
                      {t.route && (
                        <span className={`shrink-0 px-1.5 py-0.5 rounded text-white text-[10px] capitalize ${routeColorTw(t.route)}`}>
                          {t.route}
                        </span>
                      )}
                      <span className="ml-auto text-[11px] text-gray-400 shrink-0">{relativeTime(t.start_ts)}</span>
                    </div>
                    <p className="text-sm text-gray-700 truncate">{t.question || "(no question)"}</p>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-gray-400">{t.span_count} steps</span>
                      <span className="text-xs text-gray-400">·</span>
                      <span className="text-xs text-gray-400">{t.latency_ms != null ? formatMs(t.latency_ms) : "—"}</span>
                      <span className="ml-auto flex items-center gap-1 text-xs">
                        {t.error ? (
                          <><AlertCircle className="w-3 h-3 text-red-500" /><span className="text-red-500">Failed</span></>
                        ) : !t.complete ? (
                          <span className="text-amber-600">running…</span>
                        ) : (
                          <><span className="w-1.5 h-1.5 rounded-full bg-green-500" /><span className="text-gray-400">Success</span></>
                        )}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between px-3 py-2 border-t border-gray-100 shrink-0">
              <button
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-transparent"
              >
                <ChevronLeft className="w-4 h-4 text-gray-500" />
              </button>
              <span className="text-xs text-gray-400">Page {page + 1} of {totalPages}</span>
              <button
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:hover:bg-transparent"
              >
                <ChevronRight className="w-4 h-4 text-gray-500" />
              </button>
            </div>
          </div>

          {/* Trace detail */}
          <div className="flex-1 flex overflow-hidden">
          <ErrorBoundary>
            <div className="flex-1 overflow-y-auto p-6">
              {!selectedId && (
                <div className="flex items-center justify-center h-full text-sm text-gray-400">
                  Select a trace to view its details.
                </div>
              )}
              {selectedId && detailLoading && !detail && (
                <div className="flex items-center justify-center h-full text-sm text-gray-400">
                  Loading trace…
                </div>
              )}
              {selectedId && detailError && (
                <div className="flex items-center justify-center h-full text-sm text-gray-500">{detailError}</div>
              )}
              {selectedId && detail && (
                <div className="max-w-3xl">
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-sm font-mono text-gray-500">tr_{detail.trace_id.slice(0, 8)}</span>
                      <button onClick={() => navigator.clipboard.writeText(detail.trace_id)} className="text-gray-300 hover:text-gray-500">
                        <Copy className="w-3 h-3" />
                      </button>
                      {detail.route && (
                        <span className={`px-1.5 py-0.5 rounded text-white text-[10px] capitalize ${routeColorTw(detail.route)}`}>
                          {detail.route}
                        </span>
                      )}
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${detail.error ? "bg-red-50 text-red-600" : "bg-green-50 text-green-600"}`}>
                        {detail.error ? "Failed" : detail.complete ? "Success" : "Running"}
                      </span>
                      <span className="text-xs text-gray-400">{formatMs(detail.total_ms)}</span>
                      <span className="text-xs text-gray-400">· {detail.spans.length} steps</span>
                    </div>
                    <p className="text-base text-gray-800">{detail.question}</p>
                    {detail.error && <p className="text-xs text-red-600 mt-1">Error: {detail.error}</p>}
                  </div>

                  <div className="flex items-center gap-4 border-b border-gray-200 mb-4">
                    {(["graph", "timeline"] as DetailTab[]).map((tab) => (
                      <button
                        key={tab}
                        onClick={() => setDetailTab(tab)}
                        className={`pb-2 text-sm font-medium border-b-2 -mb-px capitalize transition-colors ${
                          detailTab === tab ? "border-blue-500 text-blue-600" : "border-transparent text-gray-400 hover:text-gray-600"
                        }`}
                      >
                        {tab}
                      </button>
                    ))}
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4 mb-4">
                    {detailTab === "graph" ? (
                      <TraceGraph spans={detail.spans} route={detail.route} selectedIndex={selectedSpanIdx} onSelect={setSelectedSpanIdx} />
                    ) : (
                      <TraceWaterfall trace={detail} />
                    )}
                  </div>

                  {(detail.question || detail.final_answer) && (
                    <div className="rounded-xl border border-gray-200 bg-white p-4 mb-4">
                      <p className="text-sm font-medium text-gray-700 mb-2">Trace I/O</p>
                      <p className="text-xs text-gray-400 mb-1">User query</p>
                      <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-2.5 mb-3">{detail.question}</p>
                      <p className="text-xs text-gray-400 mb-1">Final answer</p>
                      <p className="text-sm text-gray-700 bg-gray-50 rounded-lg p-2.5 whitespace-pre-wrap">
                        {detail.final_answer || "—"}
                      </p>
                    </div>
                  )}

                  <div className="grid grid-cols-2 gap-3">
                    <div className="rounded-xl border border-gray-200 bg-white p-4">
                      <p className="text-sm font-medium text-gray-700 mb-2">Trace summary</p>
                      <div className="grid grid-cols-2 gap-2 text-xs">
                        <div><p className="text-gray-400">Total latency</p><p className="text-gray-800 font-medium mt-0.5">{formatMs(detail.total_ms)}</p></div>
                        <div><p className="text-gray-400">Total steps</p><p className="text-gray-800 font-medium mt-0.5">{detail.spans.length}</p></div>
                      </div>
                    </div>
                    <div className="rounded-xl border border-gray-200 bg-white p-4">
                      <p className="text-sm font-medium text-gray-700 mb-2">Tags & labels</p>
                      <div className="flex flex-wrap gap-1.5">
                        {detail.route && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">route: {detail.route}</span>
                        )}
                        {detail.llm_model && (
                          <span className="text-[11px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-600">model: {detail.llm_model}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {selectedId && detail && detailTab === "graph" && (
              <StepDetailsPanel
                span={selectedSpan}
                stageStats={stageStats}
                sqlQuery={detail.sql_query}
                sqlTable={detail.sql_table}
                mdlMetricsReferenced={detail.mdl_metrics_referenced}
                entityResolutions={detail.entity_resolutions}
              />
            )}
          </ErrorBoundary>
          </div>
        </div>
      </div>
    </div>
  );
}
