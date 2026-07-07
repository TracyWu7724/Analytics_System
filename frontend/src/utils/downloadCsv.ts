export function downloadBlob(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}

export function timestampedFilename(prefix: string, ext: string): string {
  return `${prefix}_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.${ext}`;
}
