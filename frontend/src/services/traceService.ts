import { request } from './apiClient';

export interface TraceSummary {
  trace_id: string;
  question: string | null;
  route: string | null;
  start_ts: number; // unix seconds
  latency_ms: number | null;
  error: string | null;
  span_count: number;
  complete: boolean;
}

export interface TraceListResult {
  total: number;
  traces: TraceSummary[];
}

export interface TraceSpan {
  step: string;
  label: string;
  start_ms: number;
  duration_ms: number;
}

export interface TraceDetail {
  trace_id: string;
  question: string | null;
  route: string | null;
  llm_model: string | null;
  error: string | null;
  final_answer: string | null;
  sql_query: string | null;
  complete: boolean;
  start_ts: number;
  total_ms: number;
  spans: TraceSpan[];
}

export interface StageStat {
  step: string;
  label: string;
  count: number;
  p50: number;
  p95: number;
  p99: number;
  pct_of_p95: number;
}

export interface RouteLatencyStat {
  route: string;
  count: number;
  pct_of_total: number;
  p50: number;
  p95: number;
  p99: number;
}

export interface SlowestTrace {
  trace_id: string;
  question: string | null;
  route: string | null;
  bottleneck_step: string;
  bottleneck_label: string;
  bottleneck_ms: number;
  total_ms: number | null;
  start_ts: number;
}

export interface LatencyStats {
  overall: {
    p50: number;
    p95: number;
    p99: number;
    avg: number;
    slo_threshold_ms: number;
    slo_compliance_pct: number | null;
  };
  by_route: RouteLatencyStat[];
  by_stage: StageStat[];
  slowest_traces: SlowestTrace[];
}

export interface ListTracesParams {
  limit?: number;
  offset?: number;
  route?: string;
  q?: string;
}

export async function listTraces(params: ListTracesParams = {}): Promise<TraceListResult | { error: string }> {
  try {
    const qs = new URLSearchParams();
    if (params.limit != null) qs.set('limit', String(params.limit));
    if (params.offset != null) qs.set('offset', String(params.offset));
    if (params.route && params.route !== 'all') qs.set('route', params.route);
    if (params.q) qs.set('q', params.q);
    return await request<TraceListResult>(`/traces?${qs.toString()}`, {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load traces' };
  }
}

export async function getTrace(traceId: string): Promise<TraceDetail | { error: string }> {
  try {
    return await request<TraceDetail>(`/traces/${encodeURIComponent(traceId)}`, {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load trace' };
  }
}

export async function getLatencyStats(sloThresholdMs?: number): Promise<LatencyStats | { error: string }> {
  try {
    const qs = sloThresholdMs ? `?slo_threshold_ms=${sloThresholdMs}` : '';
    return await request<LatencyStats>(`/latency/stats${qs}`, {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load latency stats' };
  }
}
