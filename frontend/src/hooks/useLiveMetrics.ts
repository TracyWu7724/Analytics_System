import { useEffect, useRef, useState, useCallback } from "react";
import { getLiveMetrics, type LiveMetrics } from "../services/metricsService";

export function useLiveMetrics(pollMs: number = 5000, windowMinutes?: number) {
  const [data, setData] = useState<LiveMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [paused, setPaused] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchMetrics = useCallback(async () => {
    const result = await getLiveMetrics(windowMinutes);
    if ("error" in result) {
      setError(result.error);
    } else {
      setError(null);
      setData(result);
    }
    setLoading(false);
  }, [windowMinutes]);

  useEffect(() => {
    fetchMetrics();
    if (paused) return;
    timerRef.current = setInterval(fetchMetrics, pollMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [fetchMetrics, pollMs, paused]);

  return { data, error, loading, paused, setPaused, refresh: fetchMetrics };
}
