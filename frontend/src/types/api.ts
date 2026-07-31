export interface LlmModel {
  id: string;
  display_name: string;
  provider: string;
  available: boolean;
}

export interface LlmModelsResponse {
  models: LlmModel[];
  default: string;
}

export interface AgentQueryRequest {
  question: string;
  history: { role: string; content: string }[];
  llm_model?: string;
  uploaded_table?: string;
  session_id?: string;
}

export interface RagVerification {
  passed: boolean;
  failed_layer: number;
  layers?: { layer: number; name: string; passed: boolean; score: number; detail: string }[];
}

export interface MdlMetricReferenced {
  name: string;
  expression: string;
  description: string;
}

export interface EntityResolution {
  mention: string;
  resolved_to: string;
  table: string;
  column: string;
}

export interface AgentQueryResponse {
  route?: string;
  route_reasoning?: string;
  final_answer?: string;
  sql_query?: string;
  sql_rows?: Record<string, any>[];
  sql_table?: string;
  rag_chunks?: { text: string; score: number; source: string }[];
  rag_verification?: RagVerification;
  mdl_metrics_referenced?: MdlMetricReferenced[];
  entity_resolutions?: EntityResolution[];
  error?: string;
  trace_url?: string;
}

export interface FeedbackRequest {
  message_id: string;
  question: string;
  sql?: string;
  final_answer?: string;
  rating: 'good' | 'bad';
  comment?: string;
  session_id?: string;
  route?: string;
  history?: { role: string; content: string }[];
}

export interface UploadFileResponse {
  success: boolean;
  table_name?: string;
  row_count?: number;
  column_count?: number;
  columns?: string[];
  error?: string;
}

export interface UploadPdfResponse {
  success: boolean;
  filename?: string;
  chunks_added?: number;
  total_vectors?: number;
  error?: string;
}
