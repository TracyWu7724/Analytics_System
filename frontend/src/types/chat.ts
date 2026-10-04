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
  route?: 'sql' | 'rag' | 'both' | 'schema';
  route_reasoning?: string;
  rag_answer?: string;
  rag_chunks?: { text: string; score: number; source: string }[];
  sql_rows?: Record<string, any>[];
  sql_table?: string;
  mdl_metrics_referenced?: { name: string; expression: string; description: string }[];
  entity_resolutions?: { mention: string; resolved_to: string; table: string; column: string }[];
  rag_verification?: {
    passed: boolean;
    failed_layer: number;
    layers?: { layer: number; name: string; passed: boolean; score: number; detail: string }[];
  };
}
