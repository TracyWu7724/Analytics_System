import { requestForm } from './apiClient';
import type { UploadFileResponse, UploadPdfResponse } from '../types/api';

export async function uploadFile(file: File): Promise<UploadFileResponse> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const result = await requestForm<any>('/upload', formData);
    return {
      success: true,
      table_name: result.table_name,
      row_count: result.row_count,
      column_count: result.column_count,
      columns: result.columns,
    };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Upload failed' };
  }
}

export async function uploadPdf(file: File): Promise<UploadPdfResponse> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const result = await requestForm<any>('/upload/pdf', formData);
    return {
      success: true,
      filename: result.filename,
      chunks_added: result.chunks_added,
      total_vectors: result.total_vectors,
    };
  } catch (err) {
    return { success: false, error: err instanceof Error ? err.message : 'Upload failed' };
  }
}
