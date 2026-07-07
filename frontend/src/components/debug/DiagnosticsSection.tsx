import { RefreshCw, XCircle, CheckCircle, Database, Cpu, BookOpen } from "lucide-react";
import DiagRow from "./DiagRow";

interface DiagnosticsSectionProps {
  data: any;
  loading: boolean;
  onRun: () => void;
}

export function DiagnosticsSection({ data, loading, onRun }: DiagnosticsSectionProps) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-gray-400">
        <RefreshCw size={20} className="animate-spin mb-2" />
        <span className="text-sm">Running diagnostics…</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3">
        <p className="text-sm text-gray-500">Click to run a live system check.</p>
        <button
          onClick={onRun}
          className="px-4 py-2 bg-blue-500 text-white text-sm rounded-lg hover:bg-blue-600 transition-colors"
        >
          Run Diagnostics
        </button>
      </div>
    );
  }

  if (data.error) {
    return (
      <div className="flex flex-col items-center py-10 gap-2 text-center">
        <XCircle size={28} className="text-red-400" />
        <p className="text-sm text-gray-600">{data.error}</p>
        <button onClick={onRun} className="text-xs text-blue-500 hover:underline mt-1">Retry</button>
      </div>
    );
  }

  const db = data.databricks ?? {};
  const kb = data.knowledge_base ?? {};
  const llms: any[] = data.llm_models ?? [];
  const availableLlms = llms.filter(m => m.available);
  const unavailableLlms = llms.filter(m => !m.available);

  return (
    <div>
      <DiagRow
        icon={<Database size={15} />}
        label="Databricks"
        status={db.status ?? "error"}
        detail={db.message}
      />

      <DiagRow
        icon={<BookOpen size={15} />}
        label="Knowledge Base (RAG)"
        status={kb.status ?? "not_configured"}
        detail={
          kb.status === "ok"
            ? `${kb.chunk_count ?? 0} chunks · ${kb.embed_model ?? ""}`
            : kb.status === "not_configured"
            ? "RAG_EMBED_DIR not set"
            : kb.status === "index_missing"
            ? "FAISS index missing — re-index PDFs"
            : undefined
        }
      />
      {kb.latest_file && (
        <div className="ml-7 mb-1 text-xs text-gray-400">
          Latest file: <span className="font-medium text-gray-600">{kb.latest_file.name}</span>
          <span className="ml-1">({kb.latest_file.updated})</span>
        </div>
      )}
      {kb.inverted_index && (
        <div className="ml-7 mb-3 mt-1 space-y-0.5">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1">Data Index</p>
          <div className="text-xs text-gray-500 space-y-0.5">
            <div className="flex justify-between">
              <span>Schema tokens</span>
              <span className="font-mono text-gray-700">{(kb.inverted_index.schema_tokens ?? 0).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Value tokens</span>
              <span className="font-mono text-gray-700">{(kb.inverted_index.value_tokens ?? 0).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>History questions</span>
              <span className="font-mono text-gray-700">{(kb.inverted_index.history_entries ?? 0).toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span>Status</span>
              <span className={`font-medium ${kb.inverted_index.ready ? "text-green-600" : "text-amber-500"}`}>
                {kb.inverted_index.ready ? "Ready" : "Building…"}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="py-3 border-b">
        <div className="flex items-center gap-2 mb-2">
          <Cpu size={15} className="text-gray-400" />
          <span className="text-sm font-medium text-gray-700">LLM Availability</span>
        </div>
        <div className="ml-5 space-y-1.5">
          {availableLlms.map(m => (
            <div key={m.id} className="flex items-center gap-2 text-xs text-gray-600">
              <CheckCircle size={12} className="text-green-500 shrink-0" />
              <span className="font-medium">{m.display_name}</span>
              <span className="text-gray-400">({m.provider})</span>
            </div>
          ))}
          {unavailableLlms.map(m => (
            <div key={m.id} className="flex items-center gap-2 text-xs text-gray-400">
              <XCircle size={12} className="text-red-400 shrink-0" />
              <span>{m.display_name}</span>
              <span className="italic">— {m.reason}</span>
            </div>
          ))}
        </div>
      </div>

      <button
        onClick={onRun}
        className="mt-4 w-full text-xs text-blue-500 hover:underline text-center"
      >
        Re-run diagnostics
      </button>
    </div>
  );
}
