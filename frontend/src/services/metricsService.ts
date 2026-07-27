import { request } from './apiClient';

export interface LiveMetrics {
  generated_at: string;
  queries: {
    total: number;
    recent: number;
    window_minutes: number;
    by_route: Record<string, number>;
    latest_ts: string | null;
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
    total_cost_usd: number;
  } | null;
}

export async function getLiveMetrics(): Promise<LiveMetrics | { error: string }> {
  try {
    return await request<LiveMetrics>('/metrics/live', {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load live metrics' };
  }
}
