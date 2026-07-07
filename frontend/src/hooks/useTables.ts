import { useState, useCallback } from 'react';
import { getTablePreview } from '../services/databaseService';
import type { TablePreview } from '../types/database';

export function useTables() {
  const [preview, setPreview] = useState<TablePreview | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadPreview = useCallback(async (tableName: string, limit = 5) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getTablePreview(tableName, limit);
      setPreview(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load table preview');
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { preview, isLoading, error, loadPreview };
}
