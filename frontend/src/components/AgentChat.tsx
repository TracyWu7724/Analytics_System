import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ArrowLeft, Bot, Settings, Upload, FileSpreadsheet, FileText, X, ChevronDown, ExternalLink, Zap, Database, BookOpen, Layers, LogIn } from 'lucide-react';
import UserMenu from './UserMenu';
import { useAuth } from '../hooks/useAuth';
import { QueryOutput } from './Result';
import Sidebar from './Sidebar';
import { DebugPanel } from './DebugPanel';
import TablePreview from './TablePreview';
import { ApiService } from '../services/api';
import { queryHistoryService } from '../services/queryHistoryService';
import type { ChatMessage } from '../types/chat';
import type { QueryResult, TablePreview as TablePreviewType } from '../types/database';

interface AgentChatProps {
  initialQuery?: string;
  uploadedTable?: string;
  initialLlmModel?: string;
}

// ── Route badge ───────────────────────────────────────────────────────────────
const ROUTE_META: Record<string, { label: string; Icon: React.FC<any>; color: string; bg: string }> = {
  sql:  { label: 'Text2SQL',   Icon: Database,  color: 'text-blue-700',  bg: 'bg-blue-50 border-blue-200' },
  rag:  { label: 'Product Manuals RAG',   Icon: BookOpen,  color: 'text-green-700', bg: 'bg-green-50 border-green-200' },
};

const RouteBadge: React.FC<{ route: string; reasoning?: string }> = ({ route, reasoning }) => {
  const meta = ROUTE_META[route] ?? ROUTE_META.sql;
  const { label, Icon, color, bg } = meta;
  return (
    <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium ${bg} ${color}`} title={reasoning}>
      <Icon className="w-3 h-3" />
      {label}
    </div>
  );
};

// ── Component ─────────────────────────────────────────────────────────────────
const AgentChat: React.FC<AgentChatProps> = ({ initialQuery = '', uploadedTable, initialLlmModel }) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [tablePreview, setTablePreview] = useState<TablePreviewType | null>(null);
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadedTableName, setUploadedTableName] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [pendingFileUpload, setPendingFileUpload] = useState<boolean>(false);
  const [kbUpdateMessage, setKbUpdateMessage] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>(initialLlmModel || 'gemini-2.5-flash');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const lastProcessedQuery = useRef<string>('');

  useEffect(() => {
    ApiService.getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      if (!initialLlmModel) setSelectedModel(defaultModel);
    });
  }, []);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    if (initialQuery && initialQuery !== lastProcessedQuery.current) {
      lastProcessedQuery.current = initialQuery;
      handleSendMessage(initialQuery);
      setInputValue('');
    }
  }, [initialQuery]);

  useEffect(() => {
    if (uploadedTable && !tablePreview) {
      ApiService.getTablePreview(uploadedTable).then(preview => {
        setTablePreview(preview);
        setUploadedTableName(uploadedTable);
        const fileName = preview?.original_filename ?? uploadedTable.replace('uploaded_', '') + '.csv';
        const ext = preview?.file_extension ?? '.csv';
        const mime = ext === '.xlsx' || ext === '.xls'
          ? 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
          : 'text/csv';
        setUploadedFile(new File([''], fileName, { type: mime }));
        if (messages.length === 0 && !initialQuery) {
          setMessages([{ id: Date.now().toString(), type: 'user', content: `Using uploaded data: ${fileName}`, timestamp: new Date(), hasFileUpload: true }]);
        }
      }).catch(console.error);
    }
  }, [uploadedTable, messages.length, initialQuery]);

  // ── Agent query ─────────────────────────────────────────────────────────────
  const executeAgentQuery = async (question: string, tableToUse?: string) => {
    setLoadingStep('Routing your question...');
    await new Promise(r => setTimeout(r, 100));

    const history = messages
      .filter(m => !m.isLoading)
      .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.content }))
      .slice(-10);

    const result = await ApiService.executeAgentQuery(question, tableToUse, selectedModel, history);

    setLoadingStep('');
    return result;
  };

  const handleSendMessage = async (messageContent: string = inputValue) => {
    if (!messageContent.trim()) return;

    // Save to local query history and notify sidebar
    try {
      queryHistoryService.addQuery(messageContent.trim());
      window.dispatchEvent(new Event('queryHistoryUpdated'));
    } catch { /* ignore */ }

    const hasUploadedData = !!(uploadedTableName || uploadedTable);
    const isFileUploadQuery = hasUploadedData || pendingFileUpload;
    const tableForQuery = isFileUploadQuery ? (uploadedTableName || uploadedTable) : undefined;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: messageContent.trim(),
      timestamp: new Date(),
      hasFileUpload: isFileUploadQuery,
    };

    setMessages(prev => [...prev.map(m => ({ ...m, hasFileUpload: false })), userMessage]);
    if (pendingFileUpload) setPendingFileUpload(false);

    const loadingMsg: ChatMessage = {
      id: (Date.now() + 1).toString(),
      type: 'assistant',
      content: 'Thinking...',
      timestamp: new Date(),
      isLoading: true,
    };
    setMessages(prev => [...prev, loadingMsg]);
    setInputValue('');
    setIsLoading(true);

    try {
      const data = await executeAgentQuery(messageContent, tableForQuery ?? undefined);

      // Convert sql_rows to QueryResult format for the existing QueryOutput component
      let results: QueryResult[] | undefined;
      if (data.sql_rows && data.sql_rows.length > 0) {
        const columns = Object.keys(data.sql_rows[0]);
        results = [{ columns, values: data.sql_rows.map(row => columns.map(c => row[c])) }];
      }

      // Determine display content
      let content: string;
      if (data.route === 'rag' || data.route === 'both') {
        content = data.final_answer || (data.error ? `Error: ${data.error}` : 'No answer generated.');
      } else if (data.error && !data.final_answer) {
        content = 'I encountered an error processing your request.';
      } else {
        content = results && results[0].values.length > 0
          ? `Found ${results[0].values.length} result${results[0].values.length !== 1 ? 's' : ''}.`
          : data.final_answer || 'Query executed successfully.';
      }

      const assistantMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content,
        timestamp: new Date(),
        route: data.route as any,
        route_reasoning: data.route_reasoning,
        results,
        sql_query: data.sql_query,
        sql_rows: data.sql_rows,
        rag_answer: data.final_answer ?? undefined,
        error: data.error,
        trace_url: data.trace_url,
      };

      setMessages(prev => prev.slice(0, -1).concat(assistantMsg));
    } catch (err) {
      setMessages(prev => prev.slice(0, -1).concat({
        id: (Date.now() + 1).toString(),
        type: 'assistant',
        content: 'An unexpected error occurred.',
        timestamp: new Date(),
        error: 'Connection failed',
      }));
    } finally {
      setIsLoading(false);
      setLoadingStep('');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); }
  };

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'; }
  }, [inputValue]);

  // ── File upload ──────────────────────────────────────────────────────────────
  const getFileIcon = (name: string) => {
    const ext = name.toLowerCase().split('.').pop();
    return (ext === 'xlsx' || ext === 'xls')
      ? <FileSpreadsheet className="w-5 h-5 text-green-600" />
      : <FileText className="w-5 h-5 text-green-600" />;
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    setKbUpdateMessage(null);

    const isPdf = file.name.toLowerCase().endsWith('.pdf');

    try {
      if (isPdf) {
        // PDF → knowledge base update
        const result = await ApiService.uploadPdf(file);
        if (result.success) {
          setKbUpdateMessage(
            `Knowledge base updated: "${result.filename}" — ${result.chunks_added} chunks added (${result.total_vectors} total vectors)`
          );
        } else {
          alert(`PDF indexing failed: ${result.error}`);
        }
      } else {
        // CSV / Excel → data table
        const result = await ApiService.uploadFile(file);
        if (result.success) {
          setUploadedFile(file);
          setUploadedTableName(result.table_name || null);
          if (result.table_name) {
            ApiService.getTablePreview(result.table_name).then(setTablePreview).catch(console.warn);
          }
          setPendingFileUpload(true);
        } else {
          alert(`Upload failed: ${result.error}`);
        }
      }
    } catch { alert('Upload failed. Please try again.'); }
    finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const removeUploadedFile = () => {
    setUploadedFile(null); setUploadedTableName(null); setTablePreview(null); setPendingFileUpload(false);
    setMessages(prev => prev.map(m => ({ ...m, hasFileUpload: false })));
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen bg-white text-gray-900 overflow-hidden">
      <Sidebar />

      <div className="flex-1 flex flex-col">
        {/* Header */}
        <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
          <button onClick={() => navigate('/')} className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ backgroundColor: '#113D73' }}>
              <Zap className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="font-semibold text-gray-900">Decision Agent</h1>
              <p className="text-xs text-gray-400">Automatically routes to SQL or RAG</p>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {availableModels.length > 0 && (
              <div className="relative">
                <select
                  value={selectedModel}
                  onChange={e => setSelectedModel(e.target.value)}
                  className="appearance-none pl-3 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg bg-white text-gray-700 cursor-pointer hover:border-gray-300 focus:outline-none"
                >
                  {availableModels.map(m => (
                    <option key={m.id} value={m.id} disabled={!m.available}>
                      {m.display_name}{!m.available ? ' (no key)' : ''}
                    </option>
                  ))}
                </select>
                <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
              </div>
            )}
            <button onClick={() => setShowDebugPanel(true)} className="p-2 hover:bg-gray-100 rounded-lg transition-colors" title="Debug">
              <Settings className="w-5 h-5 text-gray-600" />
            </button>
            <UserMenu />
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          <AnimatePresence>
            {messages.length === 0 && (
              <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="text-center py-12">
                <div className="w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4" style={{ backgroundColor: '#EBF2FB' }}>
                  <Zap className="w-8 h-8" style={{ color: '#113D73' }} />
                </div>
                <h3 className="text-lg font-medium text-gray-900 mb-2">Decision Agent</h3>
                <p className="text-gray-500 max-w-sm mx-auto">
                  Ask anything. The agent will route data questions to Text2SQL, product manual questions to RAG, complex questions use both.
                </p>
                <div className="flex justify-center gap-3 mt-6">
                  {Object.entries(ROUTE_META).map(([key, { label, Icon, color, bg }]) => (
                    <span key={key} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-medium ${bg} ${color}`}>
                      <Icon className="w-3.5 h-3.5" />{label}
                    </span>
                  ))}
                </div>
              </motion.div>
            )}

            {messages.map(message => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className={`flex ${message.type === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div className="max-w-3xl w-full">
                  {/* Route badge — above assistant messages */}
                  {message.type === 'assistant' && message.route && !message.isLoading && (
                    <div className="mb-1.5">
                      <RouteBadge route={message.route} reasoning={message.route_reasoning} />
                    </div>
                  )}

                  <div
                    className={`rounded-2xl px-4 py-3 ${
                      message.type === 'user' ? 'text-white' : 'bg-white border border-gray-200'
                    }`}
                    style={message.type === 'user' ? { backgroundColor: '#113D73' } : {}}
                  >
                    <p className="whitespace-pre-wrap">
                      {message.isLoading ? (loadingStep || message.content) : message.content}
                    </p>
                    {message.isLoading && (
                      <div className="flex space-x-1 mt-2">
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.3s]" />
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce [animation-delay:-0.15s]" />
                        <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                      </div>
                    )}
                  </div>

                  {/* Table preview for file-upload messages */}
                  {message.type === 'user' && message.hasFileUpload && tablePreview && !message.isLoading && (
                    <TablePreview
                      tableName={tablePreview.table_name || tablePreview.name}
                      columns={tablePreview.columns}
                      rows={tablePreview.rows || []}
                      totalRows={tablePreview.total_rows || 0}
                      fileName={uploadedFile?.name || (uploadedTableName || uploadedTable)?.replace('uploaded_', '') + '.xlsx'}
                    />
                  )}

                  {/* SQL results table — only for SQL routes */}
                  {(message.results || (message.error && message.route !== 'rag')) && !message.isLoading && (
                    <div className="mt-4">
                      <QueryOutput
                        results={message.results || []}
                        error={message.error || ''}
                        sql_query={message.sql_query}
                        onClose={() => setMessages(prev => prev.map(m =>
                          m.id === message.id ? { ...m, results: undefined, error: undefined, sql_query: undefined } : m
                        ))}
                      />
                    </div>
                  )}

                  {/* LangSmith trace link */}
                  {message.trace_url && !message.isLoading && (
                    <div className="mt-2 px-1">
                      <a href={message.trace_url} target="_blank" rel="noopener noreferrer"
                         className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors">
                        <ExternalLink className="w-3 h-3" />
                        View trace in LangSmith
                      </a>
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="border-t border-gray-200 bg-white p-4">
          {/* Knowledge base update banner */}
          {kbUpdateMessage && (
            <div className="max-w-4xl mx-auto mb-3">
              <div className="flex items-center gap-2 bg-green-50 border border-green-200 rounded-lg px-3 py-2 text-sm text-green-800">
                <BookOpen className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1">{kbUpdateMessage}</span>
                <button onClick={() => setKbUpdateMessage(null)} className="p-0.5 text-green-600 hover:text-green-800">
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}

          {/* Data table upload badge */}
          {uploadedFile && (
            <div className="max-w-4xl mx-auto mb-3">
              <div className="inline-flex items-center gap-2 bg-white border border-gray-200 rounded-lg px-3 py-2 shadow-sm">
                {getFileIcon(uploadedFile.name)}
                <div className="flex flex-col min-w-0">
                  <span className="text-sm font-medium text-gray-900 truncate">{uploadedFile.name}</span>
                </div>
                <button onClick={removeUploadedFile} className="p-1 text-gray-400 hover:text-gray-600 rounded">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          <div className="flex items-center gap-4 max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={user ? "Ask me anything — data, knowledge, or both..." : "Please sign in to ask a question..."}
                className="w-full px-4 py-3 pr-12 border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:border-transparent disabled:cursor-not-allowed disabled:bg-gray-50"
                style={{ minHeight: '48px', maxHeight: '120px' }}
                disabled={isLoading || !user}
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isLoading || isUploading}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-2 text-gray-500 hover:text-blue-600 transition-colors disabled:opacity-50"
                title="Upload CSV/Excel for data queries, or PDF to update knowledge base"
              >
                {isUploading
                  ? <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600" />
                  : <Upload className="w-5 h-5" />}
              </button>
              <input ref={fileInputRef} type="file" onChange={handleFileChange} accept=".csv,.xlsx,.xls,.pdf" className="hidden" />
            </div>
            {!user && (
              <div className="flex items-center gap-1.5 px-3 py-2 text-sm text-gray-500 bg-gray-50 border border-gray-200 rounded-lg flex-shrink-0">
                <LogIn className="w-4 h-4" />
                Sign in to query
              </div>
            )}
            <button
              onClick={() => handleSendMessage()}
              disabled={!inputValue.trim() || isLoading || !user}
              className="px-4 py-3 text-white rounded-xl hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
              style={{ backgroundColor: '#113D73', height: '48px' }}
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {showDebugPanel && <DebugPanel onClose={() => setShowDebugPanel(false)} />}
    </div>
  );
};

export default AgentChat;
