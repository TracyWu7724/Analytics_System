import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ArrowLeft, Settings, X, ChevronDown, ExternalLink, Zap, BookOpen, LogIn, ThumbsUp, ThumbsDown, Check, Loader2, Activity, FileText } from 'lucide-react';
import UserMenu from './UserMenu';
import { useAuth } from '../hooks/useAuth';
import { useChat } from '../hooks/useChat';
import { useLlmModels } from '../hooks/useLlmModels';
import { QueryOutput } from './Result';
import Sidebar from './Sidebar';
import { DebugPanel } from './debug/DebugPanel';
import { RouteBadge, ROUTE_META } from './chat/RouteBadge';
import type { ChatMessage } from '../types/chat';

interface AgentChatProps {
  initialQuery?: string;
  initialLlmModel?: string;
  sessionIdProp?: string;   // if provided, restore this session from history
}

// ── Component ─────────────────────────────────────────────────────────────────
const AgentChat: React.FC<AgentChatProps> = ({ initialQuery = '', initialLlmModel, sessionIdProp }) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { selectedModel, setSelectedModel, availableModels } = useLlmModels();
  const {
    messages,
    isLoading,
    loadingStep,
    progressSteps,
    feedbackSent,
    sessionId,
    sendMessage,
    sendFeedback,
    dismissResult,
  } = useChat({ initialQuery, initialLlmModel, sessionIdProp });

  const [inputValue, setInputValue] = useState('');
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [kbUpdateMessage, setKbUpdateMessage] = useState<string | null>(null);
  const messagesEndRef = React.useRef<HTMLDivElement>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    const ta = textareaRef.current;
    if (ta) { ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight, 120) + 'px'; }
  }, [inputValue]);

  const handleSendMessage = (messageContent: string = inputValue) => {
    if (!messageContent.trim()) return;
    setInputValue('');
    sendMessage(messageContent);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendMessage(); }
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
              <h1 className="font-semibold text-gray-900">Analytics Agent</h1>
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
            <button onClick={() => navigate('/observability')} className="p-2 hover:bg-gray-100 rounded-lg transition-colors" title="Observability">
              <Activity className="w-5 h-5 text-gray-600" />
            </button>
            <button onClick={() => setShowDebugPanel(true)} className="p-2 hover:bg-gray-100 rounded-lg transition-colors" title="Settings">
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
                <h3 className="text-lg font-medium text-gray-900 mb-2">Analytics Agent</h3>
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
                    <div className="mb-1.5 flex items-center gap-2 flex-wrap">
                      <RouteBadge route={message.route} reasoning={message.route_reasoning} />
                      {message.rag_verification && !message.rag_verification.passed && (
                        <span
                          title={`Verification gate ${message.rag_verification.failed_layer} triggered`}
                          className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-700"
                        >
                          <span>⚠</span>
                          {message.rag_verification.failed_layer === 1 && 'Product not found'}
                          {message.rag_verification.failed_layer === 2 && 'Low retrieval quality'}
                          {message.rag_verification.failed_layer === 3 && 'Low grounding'}
                        </span>
                      )}
                    </div>
                  )}

                  <div
                    className={`rounded-2xl px-4 py-3 ${
                      message.type === 'user' ? 'text-white' : 'bg-white border border-gray-200'
                    }`}
                    style={message.type === 'user' ? { backgroundColor: '#113D73' } : {}}
                  >
                    {message.isLoading && progressSteps.length > 0 ? (
                      <div className="space-y-1.5">
                        {progressSteps.map((step, i) => {
                          const isCurrent = i === progressSteps.length - 1;
                          return (
                            <div
                              key={i}
                              className={`flex items-center gap-2 text-sm ${isCurrent ? 'text-gray-700' : 'text-gray-400'}`}
                            >
                              {isCurrent ? (
                                <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin" />
                              ) : (
                                <Check className="w-3.5 h-3.5 shrink-0 text-emerald-500" />
                              )}
                              <span>{step}</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <>
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
                      </>
                    )}
                  </div>

                  {/* SQL results table — only for SQL routes */}
                  {(message.results || (message.error && message.route !== 'rag')) && !message.isLoading && (
                    <div className="mt-4">
                      <QueryOutput
                        results={message.results || []}
                        error={message.error || ''}
                        sql_query={message.sql_query}
                        sql_table={message.sql_table}
                        mdl_metrics_referenced={message.mdl_metrics_referenced}
                        entity_resolutions={message.entity_resolutions}
                        onClose={() => dismissResult(message.id!)}
                      />
                    </div>
                  )}

                  {/* RAG sources — dedupe by source file, keep highest score per source */}
                  {(message.route === 'rag' || message.route === 'both') &&
                    !message.isLoading && message.rag_chunks && message.rag_chunks.length > 0 && (
                      <div className="mt-2 px-1 flex flex-wrap items-center gap-1.5">
                        <span className="text-xs text-gray-400">Sources:</span>
                        {Object.values(
                          message.rag_chunks.reduce((acc, chunk) => {
                            const existing = acc[chunk.source];
                            if (!existing || chunk.score > existing.score) acc[chunk.source] = chunk;
                            return acc;
                          }, {} as Record<string, { text: string; score: number; source: string }>)
                        )
                          .sort((a, b) => b.score - a.score)
                          .map((chunk) => (
                            <span
                              key={chunk.source}
                              title={chunk.text}
                              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-green-50 border border-green-200 text-green-700"
                            >
                              <FileText className="w-3 h-3" />
                              {chunk.source.replace(/\.pdf$/i, '')}
                            </span>
                          ))}
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

                  {/* Feedback buttons — assistant messages only */}
                  {message.type === 'assistant' && !message.isLoading && message.id && (
                    <div className="mt-2 flex items-center gap-1.5 px-1">
                      {feedbackSent[message.id] ? (
                        <span className="text-xs text-gray-400">
                          {feedbackSent[message.id] === 'good' ? 'Marked helpful' : 'Marked not helpful'} — thanks!
                        </span>
                      ) : (
                        <>
                          {(() => {
                            // Build feedback context once for both buttons.
                            // Find the index of this assistant message, then walk
                            // backwards to find the paired user message and the
                            // last N completed turns for the history snapshot.
                            const msgIdx = messages.indexOf(message);
                            const pairedQuestion = messages
                              .slice(0, msgIdx)
                              .filter(m => m.type === 'user')
                              .at(-1)?.content ?? '';
                            const historySnapshot = messages
                              .slice(0, msgIdx)
                              .filter(m => !m.isLoading)
                              .slice(-6)
                              .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.content }));

                            const handleFeedback = (rating: 'good' | 'bad') => {
                              sendFeedback({
                                message_id:   message.id!,
                                question:     pairedQuestion,
                                sql:          message.sql_query ?? undefined,
                                final_answer: message.content,
                                rating,
                                session_id:   sessionId,
                                route:        message.route ?? undefined,
                                history:      historySnapshot,
                              });
                            };

                            return (
                              <>
                          <button
                            onClick={() => handleFeedback('good')}
                            className="p-1 rounded text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors"
                            title="Helpful"
                          >
                            <ThumbsUp className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => handleFeedback('bad')}
                            className="p-1 rounded text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                            title="Not helpful"
                          >
                            <ThumbsDown className="w-3.5 h-3.5" />
                          </button>
                              </>
                            );
                          })()}
                        </>
                      )}
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

          <div className="flex items-center gap-4 max-w-4xl mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={e => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={user ? "Ask me anything — data, knowledge, or both..." : "Please sign in to ask a question..."}
                className="w-full px-4 py-3 border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:border-transparent disabled:cursor-not-allowed disabled:bg-gray-50"
                style={{ minHeight: '48px', maxHeight: '120px' }}
                disabled={isLoading || !user}
              />
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
