import { request } from './apiClient';

export interface LiveMetrics {
  generated_at: string;
  queries: {
    total: number;
    recent: number;
    window_minutes: number;
    by_route: Record<string, number>;
    latest_ts: string | null;
    success_rate: number | null;
    error_count: number;
  };
  latency_ms: {
    avg: number;
    p50: number;
    p95: number;
    recent_avg: number;
  };
  feedback: {
    total: number;
    good: number;
    bad: number;
    satisfaction_rate: number | null;
  };
  cost: {
    calls: number;
    total_tokens: number;
    total_input_tokens: number;
    total_output_tokens: number;
    total_cost_usd: number;
    by_model: Record<string, {
      calls: number;
      input_tokens: number;
      output_tokens: number;
      cost_usd: number;
    }>;
  } | null;
  rag: {
    faithfulness: {
      count: number;
      avg: number | null;
      p50: number | null;
      p95: number | null;
      recent: number[];
    } | null;
  };
  recent_queries: Array<{
    ts: string | null;
    question: string | null;
    route: string;
    latency_ms: number | null;
    llm_model: string | null;
    sql_table: string | null;
  }>;
}

export async function getLiveMetrics(windowMinutes?: number): Promise<LiveMetrics | { error: string }> {
  try {
    const qs = windowMinutes ? `?window_minutes=${windowMinutes}` : '';
    return await request<LiveMetrics>(`/metrics/live${qs}`, {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load live metrics' };
  }
}
