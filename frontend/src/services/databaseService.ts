import { request } from './apiClient';
import type { TablePreview } from '../types/database';

export async function getTablePreview(tableName: string, limit = 5): Promise<TablePreview> {
  return request<TablePreview>(`/table/${tableName}/preview?limit=${limit}`);
}
