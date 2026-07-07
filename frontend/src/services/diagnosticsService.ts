import { request } from './apiClient';

export async function getDiagnostics(): Promise<any> {
  try {
    return await request<any>('/diagnostics', {}, 15_000);
  } catch (err) {
    return { error: err instanceof Error ? err.message : 'Failed to run diagnostics' };
  }
}
