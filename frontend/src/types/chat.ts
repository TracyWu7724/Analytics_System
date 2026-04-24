import type { QueryResult } from './database';

export interface ChatMessage {
  id?: string;
  type: 'user' | 'assistant';
  role?: 'user' | 'assistant';
  content: string;
  timestamp?: number | Date;
  isLoading?: boolean;
  hasFileUpload?: boolean;
  results?: QueryResult[];
  error?: string;
  sql_query?: string;
  warning?: string;
  trace_url?: string;
  // Agent-specific fields
  route?: 'sql' | 'rag' | 'both';
  route_reasoning?: string;
  rag_answer?: string;
  sql_rows?: Record<string, any>[];
}
