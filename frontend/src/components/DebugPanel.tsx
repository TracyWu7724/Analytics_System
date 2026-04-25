import React, { useState, useEffect } from 'react';
import { ApiService } from '../services/api';
import { RefreshCw, AlertCircle, Clock, CheckCircle, XCircle, Database, Cpu, BookOpen } from 'lucide-react';

interface DebugPanelProps {
  onClose: () => void;
}

// ── Shared helpers ─────────────────────────────────────────────────────────

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const color = pct >= 70 ? 'bg-green-500' : pct >= 40 ? 'bg-yellow-400' : 'bg-red-400';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono w-10 text-right text-gray-700">{value.toFixed(3)}</span>
    </div>
  );
}

function MetricTable({ title, data, isLatency = false }: {
  title: string; data: Record<string, number>; isLatency?: boolean;
}) {
  if (!data || Object.keys(data).length === 0) return null;
  const maxVal = isLatency ? Math.max(...Object.values(data)) : 1;
  return (
    <div className="mb-4">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">{title}</p>
      <div className="space-y-2">
        {Object.entries(data)
          .sort(([, a], [, b]) => (isLatency ? a - b : b - a))
          .map(([label, val]) => (
            <div key={label}>
              <span className="text-xs text-gray-600 font-medium">{label}</span>
              <ScoreBar value={val} max={maxVal} />
            </div>
          ))}
      </div>
    </div>
  );
}

function EmptyTab() {
  return <div className="py-10 text-center text-sm text-gray-400">No data for this section in the latest run.</div>;
}

// ── Eval sections ──────────────────────────────────────────────────────────

function LlmSection({ llmData, agentData }: { llmData: any; agentData: any }) {
  return (
    <div className="space-y-4">
      {llmData && <>
        <MetricTable title="Routing Accuracy by Category" 
          data={Object.fromEntries(
            Object.entries(agentData.routing_accuracy ?? {}).filter(([k]) => k !== 'overall') as [string, number][]
          )} />
        <MetricTable title="RAG Answer Relevance" data={llmData.rag_relevance ?? {}} />
        <MetricTable title="SQL Accuracy" data={llmData.sql_accuracy ?? {}} />
        <MetricTable title="Avg Latency (ms)" data={llmData.avg_latency_ms ?? {}} isLatency />
      </>}
      {/* {agentData && (
        <div className={llmData ? 'pt-4 border-t' : ''}>
          <MetricTable
            title="Routing Accuracy by Category"
            data={Object.fromEntries(
              Object.entries(agentData.routing_accuracy ?? {}).filter(([k]) => k !== 'overall') as [string, number][]
            )}
          />
        </div>
      )} */}
      {!llmData && !agentData && <EmptyTab />}
    </div>
  );
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
      {/* Databricks */}
      <DiagRow
        icon={<Database size={15} />}
        label="Databricks"
        status={db.status ?? 'error'}
        detail={db.message}
      />

      {/* Knowledge base */}
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
      {/* Inverted index stats */}
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

      {/* LLMs */}
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

type Tab = 'diag' | 'llms';

export const DebugPanel: React.FC<DebugPanelProps> = ({ onClose }) => {
  const [evalResults, setEvalResults] = useState<any>(null);
  const [evalLoading, setEvalLoading] = useState(true);
  const [diagData, setDiagData] = useState<any>(null);
  const [diagLoading, setDiagLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>('diag');

  const loadEval = async () => {
    setEvalLoading(true);
    const data = await ApiService.getEvalResults();
    setEvalResults(data);
    setEvalLoading(false);
  };

  const runDiag = async () => {
    setDiagLoading(true);
    const data = await ApiService.getDiagnostics();
    setDiagData(data);
    setDiagLoading(false);
  };

  const handleRefresh = () => {
    if (activeTab === 'diag') runDiag();
    else loadEval();
  };

  useEffect(() => { loadEval(); }, []);

  const tabs: { id: Tab; label: string }[] = [
    { id: 'llms',  label: 'Agent Performance' },
    { id: 'diag',  label: 'Diagnostics' },
  ];

  const evalMeta = activeTab === 'llms' && evalResults && !evalResults.error;

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 overflow-hidden">
      <div className="bg-white rounded-xl shadow-xl flex flex-col w-[520px] max-h-[80vh] overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b">
          <h2 className="font-semibold text-gray-800 text-sm">System Panel</h2>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={diagLoading || evalLoading}
              className="p-1.5 rounded hover:bg-gray-100 text-gray-500 disabled:opacity-40"
              title="Refresh"
            >
              <RefreshCw size={14} className={(diagLoading || evalLoading) ? 'animate-spin' : ''} />
            </button>
            <button onClick={onClose} className="p-1.5 rounded hover:bg-gray-100 text-gray-500 text-lg leading-none">×</button>
          </div>
        </div>

        {/* Eval meta row — only for Agent Performance tab */}
        {evalMeta && (
          <div className="flex items-center gap-3 px-5 py-2 bg-gray-50 border-b text-xs text-gray-500">
            <Clock size={12} />
            <span>{evalResults.timestamp ?? '—'}</span>
            {evalResults.model && <><span className="text-gray-300">|</span><span className="font-medium text-gray-600">{evalResults.model}</span></>}
            {evalResults.mode && <><span className="text-gray-300">|</span><span>mode: {evalResults.mode}</span></>}
          </div>
        )}

        {/* Tabs */}
        <div className="flex border-b px-5">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`py-2.5 px-3 text-xs font-medium border-b-2 whitespace-nowrap mr-1 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5">
          {activeTab === 'diag' && (
            <DiagnosticsSection data={diagData} loading={diagLoading} onRun={runDiag} />
          )}
          {activeTab === 'llms' && (
            evalLoading
              ? <div className="flex items-center justify-center py-16 text-gray-400"><RefreshCw size={20} className="animate-spin mr-2" /><span className="text-sm">Loading…</span></div>
              : evalResults?.error
              ? <EvalError />
              : <div className="pr-1">
                  <LlmSection llmData={evalResults?.eval_llms} agentData={evalResults?.eval_agentic} />
                </div>
          )}

        </div>

      </div>
    </div>
  );
};

function EvalError() {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <AlertCircle size={32} className="text-amber-400 mb-3" />
      <p className="text-sm text-gray-600 mb-1">No eval results found</p>
      <p className="text-xs text-gray-400">Run from the project root:</p>
      <code className="mt-2 text-xs bg-gray-100 px-3 py-1.5 rounded text-gray-700 font-mono">
        python -m scripts.run_eval
      </code>
    </div>
  );
}
