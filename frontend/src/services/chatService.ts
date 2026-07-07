import { request, openStream } from './apiClient';
import type { AgentQueryRequest, AgentQueryResponse } from '../types/api';
import type { StreamCallbacks } from '../utils/parseStream';

export async function querySync(req: AgentQueryRequest): Promise<AgentQueryResponse> {
  return request<AgentQueryResponse>('/agent/query', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export function streamQuery(
  req: AgentQueryRequest,
  callbacks: StreamCallbacks,
): () => void {
  return openStream('/agent/query/stream', req, callbacks);
}
