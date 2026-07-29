import { request } from './apiClient';

export interface QualityByRoute {
  route: string;
  count: number;
  pct_of_total: number;
  pass_rate: number | null;
}

export interface WorstFaithfulnessRecord {
  faithfulness: number;
  trace_id: string | null;
  question: string | null;
}

export interface QualityStats {
  overall: {
    pass_rate: number | null;
    evaluated: number;
    error_count: number;
  };
  faithfulness: {
    count: number;
    avg: number | null;
    p50: number | null;
    p95: number | null;
    recent: number[];
  } | null;
  human_acceptance: {
    rated: number;
    good: number;
    bad: number;
    acceptance_rate: number | null;
  };
  by_route: QualityByRoute[];
  worst_faithfulness: WorstFaithfulnessRecord[];
}

export async function getQualityStats(): Promise<QualityStats | { error: string }> {
  try {
    return await request<QualityStats>('/quality/stats', {}, 10_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to load quality stats' };
  }
}
