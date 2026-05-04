import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ArrowLeft, Settings, X, ChevronDown, ExternalLink, Zap, Database, BookOpen, LogIn, ThumbsUp, ThumbsDown } from 'lucide-react';
import UserMenu from './UserMenu';
import { useAuth } from '../hooks/useAuth';
import { QueryOutput } from './Result';
import Sidebar from './Sidebar';
import { DebugPanel } from './DebugPanel';
import { ApiService } from '../services/api';
import { sessionHistoryService } from '../services/queryHistoryService';
import type { ChatMessage } from '../types/chat';
import type { QueryResult } from '../types/database';

interface AgentChatProps {
  initialQuery?: string;
  initialLlmModel?: string;
  sessionIdProp?: string;   // if provided, restore this session from history
}

// ── Route badge ───────────────────────────────────────────────────────────────
const ROUTE_META: Record<string, { label: string; Icon: React.FC<any>; color: string; bg: string }> = {
  sql:    { label: 'Text2SQL',              Icon: Database,  color: 'text-blue-700',   bg: 'bg-blue-50 border-blue-200' },
  rag:    { label: 'Product Manuals RAG',   Icon: BookOpen,  color: 'text-green-700',  bg: 'bg-green-50 border-green-200' },
  both:   { label: 'Text2SQL + RAG',        Icon: Zap,       color: 'text-purple-700', bg: 'bg-purple-50 border-purple-200' },
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
const AgentChat: React.FC<AgentChatProps> = ({ initialQuery = '', initialLlmModel, sessionIdProp }) => {
  const navigate = useNavigate();
  const { user } = useAuth();
  // Stable session ID: restore from URL param, or generate a new one
  const sessionId = useRef<string>(sessionIdProp ?? (
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  ));
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingStep, setLoadingStep] = useState('');
  const [showDebugPanel, setShowDebugPanel] = useState(false);
  const [kbUpdateMessage, setKbUpdateMessage] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState<string>(initialLlmModel || 'gpt-4o');
  const [availableModels, setAvailableModels] = useState<{ id: string; display_name: string; provider: string; available: boolean }[]>([]);
  const [feedbackSent, setFeedbackSent] = useState<Record<string, 'good' | 'bad'>>({});
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const lastProcessedQuery = useRef<string>('');

  useEffect(() => {
    ApiService.getLlmModels().then(({ models, default: defaultModel }) => {
      setAvailableModels(models);
      if (!initialLlmModel) setSelectedModel(defaultModel);
    });
  }, []);

  // Restore session from history when a sessionIdProp is given.
  // If the last assistant message was an error, drop it and queue a retry.
  useEffect(() => {
    if (!sessionIdProp || !user) return;
    const stored = sessionHistoryService.getSession(user.username, sessionIdProp);
    if (!stored || stored.messages.length === 0) return;

    const msgs = stored.messages;
    const lastAssistant = [...msgs].reverse().find(m => m.type === 'assistant' && !m.isLoading);
    const lastUser = [...msgs].reverse().find(m => m.type === 'user');

    if (lastAssistant?.error && lastUser) {
      // Restore everything except the errored assistant reply, then retry
      setMessages(msgs.filter(m => m.id !== lastAssistant.id));
      setRetryMessage(lastUser.content);
    } else {
      setMessages(msgs);
    }
  }, [sessionIdProp, user?.username]);

  // Fire the retry after the restored messages are committed to state
  useEffect(() => {
    if (!retryMessage) return;
    setRetryMessage(null);
    handleSendMessage(retryMessage);
  }, [retryMessage]);

  // Save session to history after each complete exchange (no loading messages)
  useEffect(() => {
    if (!user) return;
    const hasLoading = messages.some(m => m.isLoading);
    if (hasLoading) return;
    const userMsgs = messages.filter(m => m.type === 'user');
    if (userMsgs.length === 0) return;

    sessionHistoryService.upsertSession({
      session_id: sessionId.current,
      user_id: user.username,
      title: userMsgs[0].content.slice(0, 60),
      messages,
      created_at: new Date(userMsgs[0].timestamp ?? Date.now()).toISOString(),
      updated_at: new Date().toISOString(),
    });
    window.dispatchEvent(new Event('queryHistoryUpdated'));

    // Stamp the session ID into the URL so a page refresh restores this conversation
    if (!sessionIdProp) {
      window.history.replaceState(null, '', `/agent?session=${encodeURIComponent(sessionId.current)}`);
    }
  }, [messages, user?.username]);

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    if (initialQuery && initialQuery !== lastProcessedQuery.current) {
      lastProcessedQuery.current = initialQuery;
      handleSendMessage(initialQuery);
      setInputValue('');
    }
  }, [initialQuery]);


  // ── Progress step labels ──────────────────────────────────────────────────
  const STEP_LABELS: Record<string, string> = {
    routing:    'Understanding context...',
    columns:    'Retrieving table and columns...',
    generating: 'Generating SQL...',
    executing:  'Executing SQL...',
    validating: 'Validating result...',
    retrieving: 'Searching knowledge base...',
  };

  // ── Agent query (streaming) ───────────────────────────────────────────────
  const executeAgentQuery = (question: string): Promise<any> => {
    setLoadingStep('Understanding context...');

    const history = messages
      .filter(m => !m.isLoading)
      .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.content }))
      .slice(-10);

    return new Promise((resolve) => {
      ApiService.executeAgentQueryStream(
        question,
        selectedModel,
        history,
        sessionId.current,
        (_step, label) => setLoadingStep(label),
        (data) => { setLoadingStep(''); resolve(data); },
        (errMsg) => { setLoadingStep(''); resolve({ error: errMsg }); },
      );
    });
  };

  const handleSendMessage = async (messageContent: string = inputValue) => {
    if (!messageContent.trim()) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: messageContent.trim(),
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);

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
      const data = await executeAgentQuery(messageContent);

      // Convert sql_rows to QueryResult format for the existing QueryOutput component
      let results: QueryResult[] | undefined;
      if (data.sql_rows && data.sql_rows.length > 0) {
        const columns = Object.keys(data.sql_rows[0]);
        results = [{ columns, values: data.sql_rows.map((row: Record<string, unknown>) => columns.map(c => row[c])) }];
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
        rag_verification: data.rag_verification,
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

                            const submitFeedback = (rating: 'good' | 'bad') => {
                              const msgId = message.id!;
                              setFeedbackSent(prev => ({ ...prev, [msgId]: rating }));
                              ApiService.submitFeedback({
                                message_id:   msgId,
                                question:     pairedQuestion,
                                sql:          message.sql_query ?? undefined,
                                final_answer: message.content,
                                rating,
                                session_id:   sessionId.current,
                                route:        message.route ?? undefined,
                                history:      historySnapshot,
                              });
                            };

                            return (
                              <>
                          <button
                            onClick={() => submitFeedback('good')}
                            className="p-1 rounded text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors"
                            title="Helpful"
                          >
                            <ThumbsUp className="w-3.5 h-3.5" />
                          </button>
                          <button
                            onClick={() => submitFeedback('bad')}
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
