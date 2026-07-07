import { request } from './apiClient';
import { API_CONFIG } from '../config/api';
import type { LlmModelsResponse } from '../types/api';

export async function getLlmModels(): Promise<LlmModelsResponse> {
  try {
    return await request<LlmModelsResponse>('/llm-models', {}, API_CONFIG.QUICK_TIMEOUT);
  } catch {
    return { models: [], default: 'gpt-4o' };
  }
}
