import { request } from './apiClient';
import type { FeedbackRequest } from '../types/api';

export async function submitFeedback(params: FeedbackRequest): Promise<void> {
  try {
    await request<void>('/feedback', {
      method: 'POST',
      body: JSON.stringify({
        message_id:   params.message_id,
        question:     params.question,
        sql:          params.sql ?? null,
        final_answer: params.final_answer ?? null,
        rating:       params.rating,
        comment:      params.comment ?? '',
        session_id:   params.session_id ?? '',
        route:        params.route ?? '',
        history:      params.history ?? [],
      }),
    });
  } catch {
    // best-effort
  }
}
