import React, { useState } from 'react';
import { ApiService } from '../services/api';
import { RefreshCw, AlertCircle, CheckCircle, XCircle, Database, Cpu, BookOpen } from 'lucide-react';

interface DebugPanelProps {
  onClose: () => void;
}

// ── Diagnostics section ────────────────────────────────────────────────────

type DiagStatus = 'ok' | 'error' | 'misconfigured' | 'not_configured' | 'index_missing';

function StatusDot({ status }: { status: DiagStatus | boolean }) {
  const ok = status === 'ok' || status === true;
  const warn = status === 'misconfigured' || status === 'not_configured' || status === 'index_missing';
  if (ok) return <CheckCircle size={14} className="text-green-500 shrink-0" />;
  if (warn) return <AlertCircle size={14} className="text-amber-400 shrink-0" />;
  return <XCircle size={14} className="text-red-500 shrink-0" />;
}

function DiagRow({ icon, label, status, detail }: {
  icon: React.ReactNode; label: string; status: DiagStatus | boolean; detail?: string;
}) {
  return (
    <div className="flex items-start gap-3 py-3 border-b last:border-0">
      <div className="mt-0.5 text-gray-400">{icon}</div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-gray-700">{label}</span>
          <StatusDot status={status} />
        </div>
        {detail && <p className="text-xs text-gray-500 mt-0.5 truncate">{detail}</p>}
      </div>
    </div>
  );
}

function DiagnosticsSection({ data, loading, onRun }: { data: any; loading: boolean; onRun: () => void }) {
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
        status={db.status ?? 'error'}
        detail={db.message}
      />

      <DiagRow
        icon={<BookOpen size={15} />}
        label="Knowledge Base (RAG)"
        status={kb.status ?? 'not_configured'}
        detail={
          kb.status === 'ok'
            ? `${kb.chunk_count ?? 0} chunks · ${kb.embed_model ?? ''}`
            : kb.status === 'not_configured'
            ? 'RAG_EMBED_DIR not set'
            : kb.status === 'index_missing'
            ? 'FAISS index missing — re-index PDFs'
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
              <span className={`font-medium ${kb.inverted_index.ready ? 'text-green-600' : 'text-amber-500'}`}>
                {kb.inverted_index.ready ? 'Ready' : 'Building…'}
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

// ── Main panel ─────────────────────────────────────────────────────────────

export const DebugPanel: React.FC<DebugPanelProps> = ({ onClose }) => {
  const [diagData, setDiagData] = useState<any>(null);
  const [diagLoading, setDiagLoading] = useState(false);

  const runDiag = async () => {
    setDiagLoading(true);
    const data = await ApiService.getDiagnostics();
    setDiagData(data);
    setDiagLoading(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 overflow-hidden">
      <div className="bg-white rounded-xl shadow-xl flex flex-col w-[520px] max-h-[80vh] overflow-hidden">

        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-800 text-sm">System Diagnostics</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={runDiag}
              disabled={diagLoading}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw size={14} className={diagLoading ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 text-gray-500 text-lg leading-none">×</button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          <DiagnosticsSection data={diagData} loading={diagLoading} onRun={runDiag} />
        </div>

      </div>
    </div>
  );
};
