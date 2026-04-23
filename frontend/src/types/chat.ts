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
}
