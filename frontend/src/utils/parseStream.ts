export interface StreamCallbacks {
  onProgress: (step: string, label: string) => void;
  onResult: (data: any) => void;
  onError: (message: string) => void;
}

export function parseSSELine(line: string): { type: string; [key: string]: any } | null {
  if (!line.startsWith('data: ')) return null;
  try {
    return JSON.parse(line.slice(6));
  } catch {
    return null;
  }
}

export function processSSEBuffer(
  buffer: string,
  callbacks: StreamCallbacks,
): string {
  const lines = buffer.split('\n');
  const remaining = lines.pop() ?? '';
  for (const line of lines) {
    const event = parseSSELine(line);
    if (!event) continue;
    if (event.type === 'progress') callbacks.onProgress(event.step, event.label);
    else if (event.type === 'result') callbacks.onResult(event.data);
    else if (event.type === 'error') callbacks.onError(event.message);
  }
  return remaining;
}
