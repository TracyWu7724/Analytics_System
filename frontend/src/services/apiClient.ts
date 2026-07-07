import { API_CONFIG, getApiUrl } from '../config/api';
import { processSSEBuffer, type StreamCallbacks } from '../utils/parseStream';

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('ds_auth_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  timeout: number = API_CONFIG.TIMEOUT,
): Promise<T> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(getApiUrl(path), {
      ...options,
      headers: {
        ...API_CONFIG.HEADERS,
        ...authHeaders(),
        ...(options.headers as Record<string, string> | undefined),
      },
      signal: controller.signal,
    });
    clearTimeout(id);

    if (!response.ok) {
      let detail: string;
      try {
        const body = await response.json();
        detail = body?.detail
          ? (Array.isArray(body.detail)
              ? body.detail.map((e: any) => e.msg ?? JSON.stringify(e)).join('; ')
              : String(body.detail))
          : `HTTP ${response.status}`;
      } catch {
        detail = `HTTP ${response.status}`;
      }
      throw new Error(detail);
    }

    return response.json() as Promise<T>;
  } catch (err) {
    clearTimeout(id);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeout}ms`);
    }
    throw err;
  }
}

export async function requestBlob(
  path: string,
  timeout: number = API_CONFIG.TIMEOUT,
): Promise<Blob> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(getApiUrl(path), {
      headers: authHeaders(),
      signal: controller.signal,
    });
    clearTimeout(id);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.blob();
  } catch (err) {
    clearTimeout(id);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error(`Download timed out after ${timeout}ms`);
    }
    throw err;
  }
}

export async function requestForm<T>(
  path: string,
  formData: FormData,
  timeout: number = 120_000,
): Promise<T> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(getApiUrl(path), {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
      signal: controller.signal,
    });
    clearTimeout(id);
    if (!response.ok) {
      const text = await response.text().catch(() => `HTTP ${response.status}`);
      throw new Error(text);
    }
    return response.json() as Promise<T>;
  } catch (err) {
    clearTimeout(id);
    if (err instanceof Error && err.name === 'AbortError') {
      throw new Error(`Upload timed out after ${timeout}ms`);
    }
    throw err;
  }
}

export function openStream(
  path: string,
  body: unknown,
  callbacks: StreamCallbacks,
): () => void {
  const controller = new AbortController();

  fetch(getApiUrl(path), {
    method: 'POST',
    headers: {
      ...API_CONFIG.HEADERS,
      ...authHeaders(),
    },
    body: JSON.stringify(body),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok || !response.body) {
      callbacks.onError(`Request failed: ${response.status}`);
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = processSSEBuffer(buffer, callbacks);
    }
  }).catch((err) => {
    if (err?.name !== 'AbortError') callbacks.onError(err?.message ?? 'Stream error');
  });

  return () => controller.abort();
}
