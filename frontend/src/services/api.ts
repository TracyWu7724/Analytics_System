import { API_CONFIG, getApiUrl } from '../config/api';
import type { ApiQueryResponse, ApiError, QueryResult, TablePreview } from '../types/database';

// Helper function to safely convert errors to strings
const formatErrorForDisplay = (error: any): string => {
  if (typeof error === 'string') {
    return error;
  }
  
  if (error && typeof error === 'object') {
    // Handle Pydantic validation errors
    if (error.detail && Array.isArray(error.detail)) {
      return error.detail.map((err: any) => {
        if (typeof err === 'string') return err;
        if (err.msg) return `${err.loc ? err.loc.join('.') + ': ' : ''}${err.msg}`;
        return JSON.stringify(err);
      }).join('; ');
    }
    
    // Handle single validation error objects
    if (error.msg) {
      return `${error.loc ? error.loc.join('.') + ': ' : ''}${error.msg}`;
    }
    
    // Handle general detail field
    if (error.detail) {
      return typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail);
    }
    
    // Fallback to JSON stringify
    return JSON.stringify(error);
  }
  
  return String(error);
};

// Helper function to create fetch with timeout
const fetchWithTimeout = async (url: string, options: RequestInit, timeout: number = API_CONFIG.TIMEOUT): Promise<Response> => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeout}ms`);
    }
    throw error;
  }
};

export class ApiService {
  
  static async uploadFile(file: File): Promise<{ success: boolean; table_name?: string; row_count?: number; column_count?: number; columns?: string[]; error?: string }> {
    console.log(`[API] Starting file upload: "${file.name}"`);
    const startTime = Date.now();
    
    try {
      const formData = new FormData();
      formData.append('file', file);
      
      console.log(`[API] Making upload request to: ${getApiUrl('/upload')}`);
      
      // Don't set Content-Type header for FormData - let browser set it with boundary
      const response = await fetchWithTimeout(getApiUrl('/upload'), {
        method: 'POST',
        body: formData,
      }, 120000); // 2 min — CSV/Excel parsing can be slow for large files

      console.log(`[API] Upload completed in ${Date.now() - startTime}ms`);

      if (!response.ok) {
        console.error(`[API] Upload HTTP Error: ${response.status} ${response.statusText}`);
        const errorText = await response.text();
        return { success: false, error: `Upload failed: ${response.status} - ${errorText}` };
      }

      const result = await response.json();
      console.log(`[API] Upload successful:`, result);
      
      return {
        success: true,
        table_name: result.table_name,
        row_count: result.row_count,
        column_count: result.column_count,
        columns: result.columns
      };
      
    } catch (error) {
      console.error(`[API] Upload error:`, error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown upload error';
      return { success: false, error: errorMessage };
    }
  }
  
  static async uploadPdf(file: File): Promise<{ success: boolean; filename?: string; chunks_added?: number; total_vectors?: number; error?: string }> {
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await fetchWithTimeout(getApiUrl('/upload/pdf'), {
        method: 'POST',
        body: formData,
      }, 120000); // 2 min — PDF parsing can be slow
      if (!response.ok) {
        const errorText = await response.text();
        return { success: false, error: `Upload failed: ${response.status} - ${errorText}` };
      }
      const result = await response.json();
      return { success: true, filename: result.filename, chunks_added: result.chunks_added, total_vectors: result.total_vectors };
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : 'Unknown error' };
    }
  }

  static async executeNaturalLanguageQuery(question: string, uploadedTable?: string, llmModel?: string): Promise<{ results?: QueryResult[], error?: string, warning?: string, sql_query?: string, trace_url?: string }> {
    console.log(`🔍 [API] Starting natural language query: "${question}", uploaded table: "${uploadedTable}"`);
    const startTime = Date.now();
    
    try {
      console.log(`🌐 [API] Making request to: ${getApiUrl('/query')}`);
      
      const requestBody: any = { question };
      if (uploadedTable) {
        requestBody.uploaded_table = uploadedTable;
      }
      if (llmModel) {
        requestBody.llm_model = llmModel;
      }
      
      const response = await fetchWithTimeout(getApiUrl('/query'), {
        method: 'POST',
        headers: API_CONFIG.HEADERS,
        body: JSON.stringify(requestBody),
      }, API_CONFIG.TIMEOUT);

      console.log(`⏱️ [API] Request completed in ${Date.now() - startTime}ms`);

      if (!response.ok) {
        console.error(`[API] HTTP Error: ${response.status} ${response.statusText}`);
        
        // Handle specific timeout errors
        if (response.status === 408) {
          return { error: `Database query timed out. Try:\n• Using more specific filters (e.g., date ranges)\n• Asking for smaller result sets\n• Adding LIMIT to your question\n• Simplifying complex queries` };
        }
        
        const errorData: ApiError = await response.json();
        const errorMessage = formatErrorForDisplay(errorData.detail || errorData);
        return { error: errorMessage || `HTTP error! status: ${response.status}` };
      }

      const data: ApiQueryResponse = await response.json();
      console.log(`✅ [API] Received data:`, { 
        rowCount: data.rows?.length || 0, 
        sql: data.sql_query,
        question: data.question,
        warning: data.warning
      });
      
      // Convert API response to QueryResult format
      if (data.rows && data.rows.length > 0) {
        const columns = Object.keys(data.rows[0]);
        const values = data.rows.map(row => columns.map(col => row[col]));

        const result: { results?: QueryResult[], error?: string, warning?: string, sql_query?: string, trace_url?: string } = {
          results: [{ columns, values }],
          sql_query: data.sql_query,
        };

        if (data.warning) result.warning = data.warning;
        if (data.trace_url) result.trace_url = data.trace_url;

        return result;
      } else {
        console.log(`[API] Query returned no results`);
        const result: { results?: QueryResult[], error?: string, warning?: string, sql_query?: string, trace_url?: string } = {
          results: [{ columns: [], values: [] }],
          sql_query: data.sql_query,
        };

        if (data.warning) result.warning = data.warning;
        if (data.trace_url) result.trace_url = data.trace_url;

        return result;
      }

    } catch (error) {
      const elapsed = Date.now() - startTime;
      console.error(`[API] Error after ${elapsed}ms:`, error);
      
      if (error instanceof Error) {
        if (error.message.includes('timed out')) {
          return { error: `Query timed out after ${API_CONFIG.TIMEOUT/60000} minutes. Try:\n• Simplifying your question\n• Being more specific\n• Breaking complex queries into smaller parts\n• Checking if the backend server is responding\n• The AI model might be experiencing high load` };
        }
        if (error.message.includes('timeout')) {
          return { error: `Database query timed out. Try:\n• Using more specific filters\n• Adding date ranges to limit data\n• Asking for smaller result sets\n• Using LIMIT in your question` };
        }
        if (error.message.includes('fetch')) {
          return { error: 'Cannot connect to the API server. Make sure your FastAPI backend is running on http://localhost:8000' };
        }
        return { error: error.message };
      }
      
      return { 
        error: 'An unexpected error occurred while executing the query'
      };
    }
  }

  static async generateSQL(question: string): Promise<{ sql_query?: string, error?: string }> {
    console.log(` [API] Generating SQL for: "${question}"`);
    
    try {
      const response = await fetchWithTimeout(getApiUrl('/generate_sql'), {
        method: 'POST',
        headers: API_CONFIG.HEADERS,
        body: JSON.stringify({ question }),
      });

             if (!response.ok) {
         const errorData: ApiError = await response.json();
         const errorMessage = formatErrorForDisplay(errorData.detail || errorData);
         return { error: errorMessage || `HTTP error! status: ${response.status}` };
       }

      const data = await response.json();
      console.log(` [API] Generated SQL:`, data.sql_query);
      return { sql_query: data.sql_query };

    } catch (error) {
      console.error(' [API] SQL Generation Error:', error);
      return { 
        error: error instanceof Error ? error.message : 'Network error occurred'
      };
    }
  }



  static async executeAgentQuery(
    question: string,
    uploadedTable?: string,
    llmModel?: string,
    history: { role: string; content: string }[] = [],
    sessionId?: string,
  ): Promise<{
    route?: string;
    route_reasoning?: string;
    final_answer?: string;
    sql_query?: string;
    sql_rows?: Record<string, any>[];
    sql_table?: string;
    rag_chunks?: { text: string; score: number; source: string }[];
    rag_verification?: {
      passed: boolean;
      failed_layer: number;
      layers?: { layer: number; name: string; passed: boolean; score: number; detail: string }[];
    };
    error?: string;
    trace_url?: string;
  }> {
    try {
      const body: any = { question, history };
      if (uploadedTable) body.uploaded_table = uploadedTable;
      if (llmModel) body.llm_model = llmModel;
      if (sessionId) body.session_id = sessionId;

      const token = localStorage.getItem('ds_auth_token');
      const response = await fetchWithTimeout(getApiUrl('/agent/query'), {
        method: 'POST',
        headers: {
          ...API_CONFIG.HEADERS,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      }, API_CONFIG.TIMEOUT);

      if (!response.ok) {
        const errorData: ApiError = await response.json();
        return { error: formatErrorForDisplay(errorData.detail || errorData) };
      }

      const data = await response.json();
      return {
        route: data.route,
        route_reasoning: data.route_reasoning,
        final_answer: data.final_answer,
        sql_query: data.sql_query,
        sql_rows: data.sql_rows,
        sql_table: data.sql_table,
        rag_chunks: data.rag_chunks,
        rag_verification: data.rag_verification,
        error: data.error,
        trace_url: data.trace_url,
      };
    } catch (error) {
      return { error: error instanceof Error ? error.message : 'Network error' };
    }
  }

  static executeAgentQueryStream(
    question: string,
    llmModel: string,
    history: { role: string; content: string }[],
    sessionId: string,
    onProgress: (step: string, label: string) => void,
    onResult: (data: any) => void,
    onError: (message: string) => void,
  ): () => void {
    const token = localStorage.getItem('ds_auth_token');
    const body = JSON.stringify({ question, llm_model: llmModel, history, session_id: sessionId });
    const controller = new AbortController();

    fetch(getApiUrl('/agent/query/stream'), {
      method: 'POST',
      headers: {
        ...API_CONFIG.HEADERS,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body,
      signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok || !response.body) {
        onError(`Request failed: ${response.status}`);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'progress') onProgress(event.step, event.label);
            else if (event.type === 'result')  onResult(event.data);
            else if (event.type === 'error')   onError(event.message);
          } catch { /* malformed line */ }
        }
      }
    }).catch((err) => {
      if (err.name !== 'AbortError') onError(err.message ?? 'Stream error');
    });

    return () => controller.abort();
  }

  static async downloadCSV(): Promise<void> {
    try {
      const response = await fetchWithTimeout(getApiUrl('/download/csv'), {});
      
      if (!response.ok) {
        throw new Error(`Download failed: ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `query_results_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

    } catch (error) {
      console.error('CSV Download Error:', error);
      throw error;
    }
  }

  static async downloadExcel(): Promise<void> {
    try {
      const response = await fetchWithTimeout(getApiUrl('/download/excel'), {});
      
      if (!response.ok) {
        throw new Error(`Download failed: ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `query_results_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

    } catch (error) {
      console.error('Excel Download Error:', error);
      throw error;
    }
  }

  static async getTablePreview(tableName: string, limit: number = 5): Promise<TablePreview> {
    console.log(` [API] Getting table preview for: ${tableName}`);
    
    try {
      const response = await fetchWithTimeout(getApiUrl(`/table/${tableName}/preview?limit=${limit}`), {});
      
      if (!response.ok) {
        throw new Error(`Failed to get table preview: ${response.status}`);
      }

      const result = await response.json();
      console.log(`[API] Table preview fetched:`, { 
        table: result.table_name, 
        columns: result.columns.length, 
        rows: result.preview_count,
        total: result.total_rows 
      });
      return result;

    } catch (error) {
      console.error(' [API] Table Preview Error:', error);
      throw error;
    }
  }

  static async getLlmModels(): Promise<{ models: { id: string; display_name: string; provider: string; available: boolean }[]; default: string }> {
    try {
      const response = await fetchWithTimeout(getApiUrl('/llm-models'), {}, API_CONFIG.QUICK_TIMEOUT);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      console.error('[API] Failed to fetch LLM models:', error);
      return { models: [], default: 'gpt-4o' };
    }
  }

  static async getDiagnostics(): Promise<any> {
    try {
      const response = await fetchWithTimeout(getApiUrl('/diagnostics'), {}, 15000);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      return { error: error instanceof Error ? error.message : 'Failed to run diagnostics' };
    }
  }

  static async submitFeedback(params: {
    message_id: string;
    question: string;
    sql?: string;
    final_answer?: string;
    rating: 'good' | 'bad';
    comment?: string;
    session_id?: string;
    route?: string;
    history?: { role: string; content: string }[];
  }): Promise<void> {
    try {
      const token = localStorage.getItem('ds_auth_token');
      await fetch(getApiUrl('/feedback'), {
        method: 'POST',
        headers: {
          ...API_CONFIG.HEADERS,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
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

  static async healthCheck(): Promise<{ status: string, database: string, tables_count: number, tables: string[] }> {
    console.log(`[API] Running health check...`);
    
    try {
      const response = await fetchWithTimeout(getApiUrl('/health'), {}, API_CONFIG.QUICK_TIMEOUT); // Shorter timeout for health check
      
      if (!response.ok) {
        throw new Error(`Health check failed: ${response.status}`);
      }

      const result = await response.json();
      console.log(` [API] Health check passed:`, result);
      return result;

    } catch (error) {
      console.error(' [API] Health Check Error:', error);
      throw error;
    }
  }
} 
