// src/components/debug/types.ts

export type DiagStatus =
  | "ok"
  | "error"
  | "misconfigured"
  | "not_configured"
  | "index_missing";

export type DiagnosticsData = {
  error?: string;

  databricks?: {
    status?: DiagStatus;
    message?: string;
  };

  knowledge_base?: {
    status?: DiagStatus;
    chunk_count?: number;
    embed_model?: string;
    latest_file?: {
      name: string;
      updated: string;
    };
    inverted_index?: {
      schema_tokens?: number;
      value_tokens?: number;
      history_entries?: number;
      ready?: boolean;
    };
  };

  llm_models?: {
    id: string;
    display_name: string;
    provider: string;
    available: boolean;
    reason?: string;
  }[];
};