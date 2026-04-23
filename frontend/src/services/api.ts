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
      }, API_CONFIG.QUICK_TIMEOUT); // Use shorter timeout for uploads

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
  
  static async executeNaturalLanguageQuery(question: string, uploadedTable?: string, llmModel?: string): Promise<{ results?: QueryResult[], error?: string, warning?: string, sql_query?: string }> {
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
        
        const result: { results?: QueryResult[], error?: string, warning?: string, sql_query?: string } = {
          results: [{
            columns,
            values
          }],
          sql_query: data.sql_query
        };
        
        // Include warning if present
        if (data.warning) {
          result.warning = data.warning;
        }
        
        return result;
      } else {
        console.log(`[API] Query returned no results`);
        const result: { results?: QueryResult[], error?: string, warning?: string, sql_query?: string } = {
          results: [{
            columns: [],
            values: []
          }],
          sql_query: data.sql_query
        };
        
        // Include warning even for empty results
        if (data.warning) {
          result.warning = data.warning;
        }
        
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
      return { models: [], default: 'gemini-1.5-pro' };
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
