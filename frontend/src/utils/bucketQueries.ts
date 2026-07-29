import type { LiveMetrics } from "../services/metricsService";

export interface LatencyBucket {
  label: string;
  count: number;
  p50: number;
  p95: number;
}

function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const k = ((sorted.length - 1) * p) / 100;
  const lo = Math.floor(k);
  const hi = Math.min(lo + 1, sorted.length - 1);
  return Math.round(sorted[lo] + (k - lo) * (sorted[hi] - sorted[lo]));
}

// Buckets recent_queries (newest-first) into `numBuckets` equal-sized,
// chronologically-ordered groups so a trend reads sensibly even when the
// underlying audit log is sparse or bursty rather than evenly sampled.
export function bucketLatency(queries: LiveMetrics["recent_queries"], numBuckets: number = 12): LatencyBucket[] {
  const chronological = [...queries].reverse().filter((q) => q.latency_ms != null);
  if (chronological.length === 0) return [];

  const size = Math.max(1, Math.ceil(chronological.length / numBuckets));
  const buckets: LatencyBucket[] = [];

  for (let i = 0; i < chronological.length; i += size) {
    const slice = chronological.slice(i, i + size);
    const latencies = slice.map((q) => q.latency_ms as number);
    const lastTs = slice[slice.length - 1].ts;
    buckets.push({
      label: lastTs ? new Date(lastTs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "",
      count: slice.length,
      p50: percentile(latencies, 50),
      p95: percentile(latencies, 95),
    });
  }

  return buckets;
}
