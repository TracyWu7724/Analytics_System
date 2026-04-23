export interface QueryResult {
  columns: string[];
  values: any[][];
  warning?: string;
}

export interface ApiQueryResponse {
  question: string;
  sql_query: string;
  rows: Record<string, any>[];
  count: number;
  raw_result: string;
  warning?: string;
}

export interface ApiError {
  detail: string;
}

export interface TablePreview {
  name: string;
  table_name?: string;
  columns: string[];
  sample_data?: any[][];
  rows?: any[][];
  total_rows?: number;
  original_filename?: string;
  file_extension?: string;
} 